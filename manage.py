#!/usr/bin/env python3
"""コマンドライン入口。

  python manage.py import samples/*.eml        .eml ファイルを取り込む
  python manage.py imap [--watch 120]          IMAP から取り込む（環境変数で接続設定）
  python manage.py reparse                     保存済みメールを再解析
  python manage.py serve [--port 8000]         ダッシュボードを起動
  python manage.py export-demo                 静的デモ用データを public/demo-data.json に書き出す
"""
import argparse
import glob
import os
import sys
import time

from mail_dashboard import db, demo, mailio, server


def _print_result(name, lead_id, result, lead):
    if result == "duplicate":
        print(f"  skip  {name}（取込済み #{lead_id}）")
    else:
        print(f"  add   {name} → #{lead_id} [{lead['source_code']}] "
              f"{lead.get('customer_name') or '-'} / {lead.get('phone') or '-'}")


def cmd_import(args):
    con = db.connect(args.db)
    paths = [p for pat in args.files for p in (glob.glob(pat) or [pat])]
    for p in paths:
        with open(p, "rb") as fh:
            _print_result(os.path.basename(p), *db.ingest_raw(con, fh.read()))


def cmd_imap(args):
    con = db.connect(args.db)
    host, user, pw = (os.environ.get(k) for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"))
    if not (host and user and pw):
        sys.exit("IMAP_HOST / IMAP_USER / IMAP_PASSWORD を環境変数で設定してください")
    while True:
        known = {r["message_id"] for r in con.query("SELECT message_id FROM leads")}
        n = 0
        for raw in mailio.fetch_imap(host, user, pw, folder=os.environ.get("IMAP_FOLDER", "INBOX"),
                                     days=args.days, mark_seen=args.mark_seen, known_ids=known):
            lead_id, result, lead = db.ingest_raw(con, raw)
            if result == "inserted":
                n += 1
                _print_result("imap", lead_id, result, lead)
        print(f"{time.strftime('%H:%M:%S')} 新着 {n} 件")
        if not args.watch:
            break
        time.sleep(args.watch)


def main():
    ap = argparse.ArgumentParser(description="受信メール → 案件ダッシュボード")
    ap.add_argument("--db", default=None, help="SQLite ファイル（既定: ./leads.db）")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("import", help=".eml を取り込む")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_import)

    p = sp.add_parser("imap", help="IMAP から取り込む")
    p.add_argument("--days", type=int, default=7, help="何日前まで遡るか")
    p.add_argument("--watch", type=int, default=0, help="N 秒ごとに繰り返す")
    p.add_argument("--mark-seen", action="store_true", help="取得したメールを既読にする")
    p.set_defaults(func=cmd_imap)

    p = sp.add_parser("reparse", help="保存済みメールを再解析")
    p.set_defaults(func=lambda a: print(f"{db.reparse_all(db.connect(a.db))} 件を再解析"))

    p = sp.add_parser("initdb", help="DB のテーブルを作成（DATABASE_URL があれば PostgreSQL）")
    p.set_defaults(func=lambda a: (db.connect(a.db).close(), print("OK")))

    p = sp.add_parser("export-demo", help="サンプルから静的デモ用データ public/demo-data.json を作る")
    p.add_argument("--samples", default="samples")
    p.add_argument("--out", default=os.path.join("public", "demo-data.json"))
    p.set_defaults(func=lambda a: print(f"{demo.export(a.samples, a.out)} 件を {a.out} に書き出しました"))

    p = sp.add_parser("serve", help="ダッシュボードを起動")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=lambda a: server.serve(a.host, a.port, a.db))

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
