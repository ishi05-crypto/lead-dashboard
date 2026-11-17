"""HTTP ハンドラー（標準ライブラリのみ）。ローカルサーバーと Vercel Functions で共用。

GET  /                 ダッシュボード画面（ローカルのみ。Vercel では public/ から静的配信）
GET  /api/leads        案件一覧 JSON（?days=&source=&status=&q=）
POST /api/leads        {"id": 1, "status": "...", "memo": "..."} を更新
POST /api/ingest       受信メールを取り込む（生メール / CloudMailin / Postmark / SendGrid 形式）

環境変数
  DATABASE_URL         postgres://...（無ければローカル SQLite）
  INGEST_TOKEN         /api/ingest の合言葉。?token=… / X-Ingest-Token / Basic 認証のパスワードで渡す
  DASHBOARD_USER / DASHBOARD_PASSWORD   ダッシュボード（/api/leads）の Basic 認証
  REQUIRE_SECRETS=1    上の2つが未設定なら API を拒否する（Vercel では自動で有効）
"""
import base64
import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from . import config, db
from .inbound import extract_raw

PUBLIC = Path(__file__).resolve().parent.parent / "public"


def _require_secrets():
    return os.environ.get("REQUIRE_SECRETS") == "1" or bool(os.environ.get("VERCEL"))


class Handler(BaseHTTPRequestHandler):
    db_path = None  # ローカル実行時の SQLite パス

    def log_message(self, fmt, *args):
        pass

    # ------------------------------------------------------------ helpers
    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _basic(self):
        h = self.headers.get("Authorization", "")
        if not h.startswith("Basic "):
            return None, None
        try:
            user, _, pw = base64.b64decode(h[6:]).decode().partition(":")
            return user, pw
        except Exception:
            return None, None

    def _dashboard_ok(self):
        user, pw = os.environ.get("DASHBOARD_USER"), os.environ.get("DASHBOARD_PASSWORD")
        if not pw:
            if _require_secrets():
                self._send(500, {"error": "DASHBOARD_PASSWORD が未設定です（Vercel の環境変数に設定してください）"})
                return False
            return True
        u, p = self._basic()
        if u is not None and hmac.compare_digest(u, user or "") and hmac.compare_digest(p, pw):
            return True
        self._send(401, {"error": "ログインが必要です"},
                   headers={"WWW-Authenticate": 'Basic realm="dashboard", charset="UTF-8"'})
        return False

    def _ingest_ok(self, qs):
        token = os.environ.get("INGEST_TOKEN")
        if not token:
            if _require_secrets():
                self._send(500, {"error": "INGEST_TOKEN が未設定です"})
                return False
            return True
        given = (qs.get("token", [""])[0] or self.headers.get("X-Ingest-Token", "")
                 or (self._basic()[1] or ""))
        if hmac.compare_digest(given, token):
            return True
        self._send(403, {"error": "トークンが違います"})
        return False

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _db(self):
        return db.connect(path=self.db_path)

    # ------------------------------------------------------------ routes
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html"):
            return self._send(200, (PUBLIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path.rstrip("/") == "/api/leads":
            if not self._dashboard_ok():
                return
            p = {k: v[0] for k, v in parse_qs(query).items()}
            d = self._db()
            try:
                leads = db.list_leads(d, days=p.get("days") or None, source=p.get("source") or None,
                                            status=p.get("status") or None, q=p.get("q") or None)
            finally:
                d.close()
            return self._send(200, {
                "leads": leads,
                "statuses": config.STATUSES,
                "deadline_soon_hours": config.DEADLINE_SOON_HOURS,
                "elapsed_alert_hours": config.ELAPSED_ALERT_HOURS,
                "sources": {k: v["label"] for k, v in config.SOURCES.items()},
            })
        if path.rstrip("/") == "/api/ingest":
            return self._send(200, {"ok": True, "hint": "メールは POST で送ってください"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path, _, query = self.path.partition("?")
        path = path.rstrip("/")
        if path == "/api/ingest":
            if not self._ingest_ok(parse_qs(query)):
                return
            try:
                raw = extract_raw(self._body(), self.headers.get("Content-Type", ""))
            except (ValueError, json.JSONDecodeError) as e:
                return self._send(400, {"error": str(e)})
            d = self._db()
            try:
                lead_id, result, lead = db.ingest_raw(d, raw)
            finally:
                d.close()
            return self._send(200, {"id": lead_id, "result": result,
                                    "source": lead and lead["source_code"]})

        m = re.fullmatch(r"/api/leads(?:/(\d+))?", path)
        if m:
            if not self._dashboard_ok():
                return
            data = json.loads(self._body() or b"{}")
            lead_id = int(m.group(1) or data.get("id") or 0)
            status = data.get("status")
            if not lead_id:
                return self._send(400, {"error": "id がありません"})
            if status is not None and status not in config.STATUSES:
                return self._send(400, {"error": "unknown status"})
            d = self._db()
            try:
                db.update_lead(d, lead_id, status=status, memo=data.get("memo"))
            finally:
                d.close()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


def serve(host="127.0.0.1", port=8000, db_path=None):
    Handler.db_path = db_path
    db.connect(path=db_path).close()  # スキーマ作成
    httpd = ThreadingHTTPServer((host, port), Handler)
    where = "PostgreSQL (DATABASE_URL)" if os.environ.get("DATABASE_URL") else (db_path or db.DB_PATH)
    print(f"ダッシュボード: http://{host}:{port}/  (DB: {where})")
    httpd.serve_forever()
