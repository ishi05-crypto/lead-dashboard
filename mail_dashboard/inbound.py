"""受信メール Webhook のペイロードから生メール(RFC822)を取り出す。

どのメールアドレスからでも「転送」さえできれば取り込めるように、主要な
受信メール→Webhook 変換サービスの形式をまとめて受け付ける。

  - 生メールそのもの（message/rfc822, text/plain, Apps Script, curl 等）
  - CloudMailin  : multipart「Raw」形式（message フィールド） / JSON 形式
  - Postmark     : JSON（RawEmail。無ければ TextBody 等から組み立て）
  - SendGrid     : Inbound Parse の「raw」オプション（email フィールド）
"""
import json
import re
from email.message import EmailMessage
from urllib.parse import parse_qs

RAW_KEYS = ("message", "RawEmail", "raw", "email", "rawEmail")


def _parse_multipart(body: bytes, content_type: str) -> dict:
    """multipart/form-data をバイト列のまま分解する（生メールを1バイトも変えないため）。"""
    m = re.search(r'boundary="?([^";]+)"?', content_type, re.I)
    if not m:
        raise ValueError("multipart の boundary がありません")
    delim = b"--" + m.group(1).encode()
    out = {}
    for chunk in body.split(delim)[1:]:
        if chunk.startswith(b"--"):
            break
        head, sep, data = chunk.lstrip(b"\r\n").partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        name = re.search(rb'(?<![\w])name="([^"]*)"', head, re.I)
        if name:
            out[name.group(1).decode("utf-8", "replace")] = data
    return out


def _build_from_json(d: dict) -> bytes:
    """生メールが含まれない JSON（CloudMailin JSON / Postmark）からメールを組み立てる。"""
    h = {k.lower(): v for k, v in (d.get("headers") or {}).items()} if isinstance(d.get("headers"), dict) else {}
    m = EmailMessage()
    m["From"] = d.get("From") or h.get("from") or (d.get("envelope") or {}).get("from", "")
    m["Subject"] = d.get("Subject") or h.get("subject") or ""
    date = d.get("Date") or h.get("date")
    if date:
        m["Date"] = date
    mid = d.get("MessageID") or h.get("message_id") or h.get("message-id")
    if mid:
        m["Message-ID"] = mid if mid.startswith("<") else f"<{mid}>"
    text = d.get("TextBody") or d.get("plain") or ""
    html = d.get("HtmlBody") or d.get("html") or ""
    m.set_content(text or " ", charset="utf-8")
    if html and not text:
        m.add_alternative(html, subtype="html", charset="utf-8")
    return m.as_bytes()


def extract_raw(body: bytes, content_type: str = "") -> bytes:
    ct = (content_type or "").lower()
    if "application/json" in ct:
        data = json.loads(body or b"{}")
        for k in RAW_KEYS:
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.encode("utf-8", "surrogateescape")
        return _build_from_json(data)
    if "multipart/form-data" in ct:
        fields = _parse_multipart(body, content_type)
        for k in RAW_KEYS:
            if fields.get(k):
                return fields[k]
        raise ValueError("multipart に生メールのフィールド（message / email）がありません。"
                         "サービス側で Raw 形式を選んでください")
    if "application/x-www-form-urlencoded" in ct:
        fields = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}
        for k in RAW_KEYS:
            if fields.get(k):
                return fields[k].encode()
        raise ValueError("フォームに生メールのフィールドがありません")
    return body  # 生メールそのもの
