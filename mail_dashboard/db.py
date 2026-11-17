"""ストレージ層。

- 環境変数 DATABASE_URL（postgres://...）があれば PostgreSQL（Vercel + Neon 等の本番用）
- 無ければローカルの SQLite（leads.db）
生メールも保存するので、パーサー改修後に再パース可能。
"""
import json
import os
import re
import sqlite3
import ssl
from datetime import datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

from .mailio import JST, read_message
from .parsers import parse_email_text

DB_PATH = os.environ.get("MAIL_DASHBOARD_DB", os.path.join(os.getcwd(), "leads.db"))

LEAD_COLS = [
    "source_code", "source_label", "source_detail", "brand", "case_no", "detail_url",
    "inquired_at", "inquired_iso", "customer_name", "customer_kana", "phone", "phone2",
    "email", "address", "area", "work_type", "scale", "desired_at", "contact_deadline",
    "deadline_iso", "deadline_basis", "contract_type", "note", "flags", "fields_json",
]


def _schema(pg: bool):
    return [
        f"""CREATE TABLE IF NOT EXISTS leads (
          id {"SERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"},
          message_id TEXT UNIQUE,
          subject TEXT, sender TEXT, received_at TEXT,
          {", ".join(c + " TEXT" for c in LEAD_COLS)},
          status TEXT DEFAULT '未対応', memo TEXT DEFAULT '',
          raw {"BYTEA" if pg else "BLOB"}, created_at TEXT, updated_at TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_leads_deadline ON leads(deadline_iso)",
        "CREATE INDEX IF NOT EXISTS idx_leads_received ON leads(received_at)",
    ]


class DB:
    """SQLite / PostgreSQL の差を吸収する薄いラッパー。SQL は `?` プレースホルダで書く。"""

    def __init__(self, url=None, path=None):
        url = url if url is not None else (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "")
        self.pg = url.startswith(("postgres://", "postgresql://"))
        if self.pg:
            import pg8000.dbapi  # 純 Python 実装（Vercel でもビルド不要）

            u = urlparse(url)
            q = parse_qs(u.query)
            ctx = None
            if q.get("sslmode", ["require"])[0] != "disable":
                ctx = ssl.create_default_context()
            self.con = pg8000.dbapi.connect(
                user=unquote(u.username or ""), password=unquote(u.password or ""),
                host=u.hostname, port=u.port or 5432, database=u.path.lstrip("/"),
                ssl_context=ctx,
            )
        else:
            self.con = sqlite3.connect(path or DB_PATH, check_same_thread=False)
        self._migrate()

    def _sql(self, sql):
        return re.sub(r"\?", "%s", sql) if self.pg else sql

    def query(self, sql, args=()):
        cur = self.con.cursor()
        cur.execute(self._sql(sql), list(args))
        if cur.description is None:
            return []
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def run(self, sql, args=()):
        cur = self.con.cursor()
        cur.execute(self._sql(sql), list(args))
        rows = cur.fetchall() if cur.description else []
        self.con.commit()
        return rows

    def close(self):
        self.con.close()

    def _migrate(self):
        for stmt in _schema(self.pg):
            self.run(stmt)
        if self.pg:
            have = {r["column_name"] for r in self.query(
                "SELECT column_name FROM information_schema.columns WHERE table_name='leads'")}
        else:
            have = {r["name"] for r in self.query("PRAGMA table_info(leads)")}
        for c in LEAD_COLS:  # 旧バージョンの DB に列を追加
            if c not in have:
                self.run(f"ALTER TABLE leads ADD COLUMN {c} TEXT")


def connect(path=None, url=None):
    return DB(url=url, path=path)


def _now():
    return datetime.now(JST).replace(tzinfo=None).isoformat(timespec="seconds")


def _lead_values(lead):
    vals = dict(lead)
    vals["fields_json"] = json.dumps(vals.pop("fields", {}), ensure_ascii=False)
    vals["flags"] = json.dumps(vals.get("flags", []), ensure_ascii=False)
    return [str(vals.get(c) or "") for c in LEAD_COLS]


def ingest_raw(db: DB, raw: bytes):
    """生メール1通を取り込む。戻り値: (id, 'inserted'|'duplicate', lead)"""
    info = read_message(raw)
    found = db.query("SELECT id FROM leads WHERE message_id=?", (info["message_id"],))
    if found:
        return found[0]["id"], "duplicate", None
    lead = parse_email_text(info["body"], info)
    cols = ["message_id", "subject", "sender", "received_at", *LEAD_COLS, "raw",
            "created_at", "updated_at"]
    vals = [info["message_id"], info["subject"], info["sender"],
            info["received_at"].isoformat(timespec="minutes"), *_lead_values(lead),
            raw, _now(), _now()]
    rows = db.run(
        f"INSERT INTO leads ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
        "ON CONFLICT (message_id) DO NOTHING RETURNING id", vals)
    if not rows:  # 同時に同じメールが届いた場合
        return None, "duplicate", None
    return rows[0][0], "inserted", lead


def reparse_all(db: DB):
    """保存済みの生メールを現在のパーサーで再解析（ステータス・メモは維持）。"""
    n = 0
    for row in db.query("SELECT id, raw FROM leads"):
        info = read_message(bytes(row["raw"]))
        lead = parse_email_text(info["body"], info)
        sets = ",".join(f"{c}=?" for c in LEAD_COLS)
        db.run(f"UPDATE leads SET {sets} WHERE id=?", [*_lead_values(lead), row["id"]])
        n += 1
    return n


def row_to_dict(row):
    d = {k: v for k, v in row.items() if k != "raw"}
    d["flags"] = json.loads(d.get("flags") or "[]")
    d["fields"] = json.loads(d.pop("fields_json", None) or "{}")
    return d


def list_leads(db: DB, days=None, source=None, status=None, q=None):
    sql, args = "SELECT * FROM leads WHERE 1=1", []
    if days:
        cutoff = datetime.now(JST).replace(tzinfo=None) - timedelta(days=int(days))
        sql += " AND received_at >= ?"
        args.append(cutoff.isoformat(timespec="minutes"))
    if source:
        sql += " AND source_code=?"
        args.append(source)
    if status:
        sql += " AND status=?"
        args.append(status)
    if q:
        like = f"%{q}%"
        sql += (" AND (customer_name LIKE ? OR phone LIKE ? OR area LIKE ? OR work_type LIKE ?"
                " OR case_no LIKE ? OR note LIKE ? OR memo LIKE ?)")
        args += [like] * 7
    sql += " ORDER BY received_at DESC"
    return [row_to_dict(r) for r in db.query(sql, args)]


def update_lead(db: DB, lead_id, status=None, memo=None):
    if status is not None:
        db.run("UPDATE leads SET status=?, updated_at=? WHERE id=?", (status, _now(), lead_id))
    if memo is not None:
        db.run("UPDATE leads SET memo=?, updated_at=? WHERE id=?", (memo, _now(), lead_id))
