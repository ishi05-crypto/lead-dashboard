"""Vercel Function（Python）。処理本体は mail_dashboard/server.py の Handler。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mail_dashboard.server import Handler  # noqa: E402


class handler(Handler):
    pass
