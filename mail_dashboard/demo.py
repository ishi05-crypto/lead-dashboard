"""静的デモ用データの書き出し。

samples/*.eml を解析し、ダッシュボードがそのまま読める JSON（public/demo-data.json）にする。
データベースを使わない静的デモ（Vercel で画面だけ公開する場合）で使う。
画面側（public/index.html）は、閲覧時の日時に合わせて日付を自動でずらして表示する。
"""
import glob
import json
import os

from . import config
from .mailio import read_message
from .parsers import parse_email_text

# デモで「作業中」らしく見せるための初期ステータスとメモ（ファイル名 → 値）
PRESETS = {
    "a1_share_tech.eml": ("対応中", "1回目の電話済み。折り返し待ち"),
    "b2_epark.eml": ("アポ確定", "現地調査の日程を調整済み"),
}


def build_demo_data(sample_dir: str) -> dict:
    leads = []
    for path in sorted(glob.glob(os.path.join(sample_dir, "*.eml"))):
        with open(path, "rb") as fh:
            info = read_message(fh.read())
        lead = parse_email_text(info["body"], info)
        status, memo = PRESETS.get(os.path.basename(path), ("未対応", ""))
        lead.update(
            message_id=info["message_id"],
            subject=info["subject"],
            sender=info["sender"],
            received_at=info["received_at"].isoformat(timespec="minutes"),
            status=status,
            memo=memo,
        )
        leads.append(lead)
    leads.sort(key=lambda l: l["received_at"])
    for i, l in enumerate(leads, 1):
        l["id"] = i
    return {
        "demo": True,
        "leads": leads,
        "statuses": config.STATUSES,
        "deadline_soon_hours": config.DEADLINE_SOON_HOURS,
        "elapsed_alert_hours": config.ELAPSED_ALERT_HOURS,
        "sources": {k: v["label"] for k, v in config.SOURCES.items()},
    }


def export(sample_dir: str, out_path: str) -> int:
    data = build_demo_data(sample_dir)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    return len(data["leads"])
