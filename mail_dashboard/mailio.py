"""メールの読み込み（.eml / IMAP / 生データ）と本文デコード。"""
import email
import hashlib
import html
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email import policy
from email.utils import getaddresses, parsedate_to_datetime

JST = timezone(timedelta(hours=9))

CHARSET_ALIASES = {
    "shift_jis": "cp932", "shift-jis": "cp932", "sjis": "cp932", "x-sjis": "cp932",
    "windows-31j": "cp932", "iso-2022-jp": "iso2022_jp_2004", "euc-jp": "euc_jp",
}


def _decode_payload(part) -> str:
    payload = part.get_payload(decode=True) or b""
    cs = (part.get_content_charset() or "").lower()
    candidates = [CHARSET_ALIASES.get(cs, cs)] if cs else []
    candidates += ["utf-8", "iso2022_jp_2004", "iso2022_jp_ext", "cp932", "euc_jp"]
    for c in candidates:
        try:
            return payload.decode(c)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", "replace")


def html_to_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", h)
    h = re.sub(r"(?i)</t[dh]>", "\t", h)
    h = re.sub(r"<[^>]+>", "", h)
    return html.unescape(h)


def extract_body(msg) -> str:
    plain, htm = [], []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            plain.append(_decode_payload(part))
        elif ctype == "text/html":
            htm.append(_decode_payload(part))
    if plain:
        return "\n".join(plain)
    return "\n".join(html_to_text(h) for h in htm)


def _domains(msg):
    out = []
    for h in ("From", "Sender", "Reply-To", "Return-Path"):
        for _, addr in getaddresses([str(v) for v in msg.get_all(h, [])]):
            if "@" in addr:
                d = addr.rsplit("@", 1)[1].strip(">").lower()
                if d not in out:
                    out.append(d)
    return out


def read_message(raw: bytes) -> dict:
    """生メール(bytes) → 取り込みに必要な情報。"""
    msg = email.message_from_bytes(raw, policy=policy.default)
    received = None
    try:
        if msg["Date"]:
            received = parsedate_to_datetime(str(msg["Date"]))
            if received.tzinfo:
                received = received.astimezone(JST).replace(tzinfo=None)
    except (TypeError, ValueError):
        received = None
    mid = str(msg["Message-ID"] or "").strip() or "sha1:" + hashlib.sha1(raw).hexdigest()
    domains = _domains(msg)
    return {
        "message_id": mid,
        "subject": str(msg["Subject"] or ""),
        "sender": str(msg["From"] or ""),
        "sender_domains": domains,
        "sender_domain": domains[0] if domains else "",
        "received_at": received or datetime.now(JST).replace(tzinfo=None),
        "body": extract_body(msg),
    }


def fetch_imap(host, user, password, folder="INBOX", days=7, port=993,
               mark_seen=False, known_ids=None):
    """IMAP から直近 days 日分を取得し、未取込のものだけ生データで返す。"""
    known_ids = known_ids or set()
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    with imaplib.IMAP4_SSL(host, port) as M:
        M.login(user, password)
        M.select(folder, readonly=not mark_seen)
        typ, data = M.search(None, "SINCE", since)
        ids = data[0].split() if typ == "OK" else []
        for num in ids:
            typ, hdr = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
            mid = ""
            if typ == "OK" and hdr and isinstance(hdr[0], tuple):
                m = re.search(rb"(?i)message-id:\s*(\S+)", hdr[0][1])
                mid = m.group(1).decode(errors="ignore") if m else ""
            if mid and mid in known_ids:
                continue
            typ, body = M.fetch(num, "(RFC822)" if mark_seen else "(BODY.PEEK[])")
            if typ == "OK" and body and isinstance(body[0], tuple):
                yield body[0][1]
