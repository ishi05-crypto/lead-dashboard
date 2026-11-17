"""送客元の判別と、送客元ごとの本文パーサー。

各パーサーは本文（正規化済みテキスト）から統一スキーマの dict を返す。
ダッシュボードの主要8項目:
  customer_name 顧客氏名 / phone 電話番号 / area エリア / work_type 作業種別 /
  scale 規模・本数 / desired_at 希望日時 / source_label 送客元 / contact_deadline 連絡期限
"""
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from . import config
from .textutil import (
    extract_area, first_url, g, guess_scale, join, norm_phone,
    normalize, parse_dt, parse_dt_ex, parse_known, parse_marked, strip_hearing,
)

# ------------------------------------------------------------------ 判別
BODY_SIGNATURES = [
    ("C-1", re.compile(r"package_estimate_shops|リショップナビ")),
    ("B-CDB", re.compile(r"計測番号[\s\S]*入電ID|入電ID[\s\S]*計測番号")),
    ("B-1", re.compile(r"発信者電話番号[\s\S]*宛先電話番号")),
    ("A-3", re.compile(r"CV日時")),
    ("A-2", re.compile(r"\bOR\d{3,}|お庭センター")),
    ("A-1", re.compile(r"取次日時|お客様への連絡期限|伐採110番")),
]


def _domain_match(domain: str, target: str) -> bool:
    return domain == target or domain.endswith("." + target)


def detect_source(sender_domains, text: str) -> str:
    """送信元ドメイン → 本文の特徴 → 本文中のドメイン の順で送客元を判定する。"""
    code = None
    for d in sender_domains:
        for c, cfg in config.SOURCES.items():
            if any(_domain_match(d, t) for t in cfg["domains"]):
                code = "B-CDB" if c in ("B-2", "B-3") else c
                break
        if code:
            break
    if not code:
        for c, rx in BODY_SIGNATURES:
            if rx.search(text):
                code = c
                break
    if not code:  # 転送メール等: 本文中に送客元ドメインが出てくるか
        for c, cfg in config.SOURCES.items():
            if any(t in text for t in cfg["domains"]):
                code = "B-CDB" if c in ("B-2", "B-3") else c
                break
    return code or "UNKNOWN"


def resolve_cdb_account(fields: dict) -> str:
    """コールデータバンク形式の B-2 / B-3 を アカウント名＋キャンペーン名 で判別。"""
    key = (g(fields, "アカウント名") + " " + g(fields, "キャンペーン名")).lower()
    for c in ("B-2", "B-3"):
        if any(k.lower() in key for k in config.SOURCES[c].get("account_keywords", [])):
            return c
    return "B-X"


# ------------------------------------------------------------------ 各パーサー
def parse_a1(text, meta):
    f = parse_marked(text)
    site, hearing = strip_hearing(g(f, "問合せ元サイト名"))
    addr = g(f, "住所")
    flags = [f"ヒアリング指示: {h.strip('【】')}" for h in hearing]
    if not g(f, "電話番号1", "電話番号"):
        flags.append("電話番号なし")
    return dict(
        fields=f,
        case_no=g(f, "案件番号"),
        detail_url=g(f, "詳細URL") or first_url(text),
        inquired_at=g(f, "取次日時"),
        contact_deadline=g(f, "お客様への連絡期限"),
        source_detail=site,
        customer_name=g(f, "お名前"),
        phone=norm_phone(g(f, "電話番号1", "電話番号")),
        phone2=norm_phone(g(f, "電話番号2")),
        email=g(f, "メールアドレス"),
        address=addr,
        area=extract_area(addr),
        work_type=join(g(f, "ジャンル"), g(f, "相談内容")),
        scale=join(g(f, "内容"), ("処分:" + g(f, "処分")) if g(f, "処分") else ""),
        desired_at=g(f, "希望日時"),
        note=join(
            ("他の希望作業: " + g(f, "他の希望作業")) if g(f, "他の希望作業") else "",
            ("建物種別: " + g(f, "建物種別")) if g(f, "建物種別") else "",
            ("関係性: " + g(f, "関係性")) if g(f, "関係性") else "",
            ("状況: " + g(f, "状況")) if g(f, "状況") else "",
            sep="\n",
        ),
        flags=flags,
    )


def parse_a2(text, meta):
    f = parse_marked(text)
    # 冒頭の但し書き（※エリア外のため、受注ベースの案件になります 等）
    notices = [l.strip() for l in text.split("\n") if l.strip().startswith(("※", "*"))]
    contract = "受注ベース" if "受注ベース" in text else "通常"
    flags = list(dict.fromkeys(notices))
    if "エリア外" in text and not any("エリア外" in n for n in flags):
        flags.append("エリア外")
    tree = g(f, "木の本数")
    return dict(
        fields=f,
        case_no=g(f, "案件番号"),
        detail_url=g(f, "サイトURL") or first_url(text),
        inquired_at=g(f, "受付日時", "送信時刻"),
        contact_deadline="",
        source_detail=g(f, "サイト名"),
        customer_name=g(f, "お客様名"),
        customer_kana=g(f, "お客様名(ふりがな)"),
        phone=norm_phone(g(f, "電話番号")),
        email=g(f, "メールアドレス"),
        address=g(f, "住所(地域)", "住所"),
        area=extract_area(g(f, "住所(地域)", "住所")),
        work_type=join(g(f, "種別"), g(f, "ご検討箇所")),
        scale=("木の本数: " + tree) if tree else guess_scale(g(f, "備考")),
        desired_at=join(
            ("①" + g(f, "お見積りの希望日時(第1候補)")) if g(f, "お見積りの希望日時(第1候補)") else "",
            ("②" + g(f, "お見積りの希望日時(第2候補)")) if g(f, "お見積りの希望日時(第2候補)") else "",
        ),
        contract_type=contract,
        note=join(
            ("問合せ方法: " + g(f, "お問い合わせ方法")) if g(f, "お問い合わせ方法") else "",
            ("お客様について: " + g(f, "お客様について")) if g(f, "お客様について") else "",
            ("備考: " + g(f, "備考")) if g(f, "備考") else "",
            ("サイト詳細: " + g(f, "サイト詳細")) if g(f, "サイト詳細") else "",
            sep="\n",
        ),
        flags=flags,
    )


A3_KEYS = ["お問い合わせ項目", "会社名", "氏名", "メールアドレス", "電話番号", "郵便番号",
           "住所", "自由欄", "CV日時", "端末種別", "広告種別", "広告媒体", "キーワード",
           "広告クリックID", "gclid", "GCLID"]
A3_STOP = re.compile(r"成約率|成約単価|売上単価|ROAS")


def _ad_note(f):
    return join(*(f"{k}: {g(f, k, prefix=False)}" for k in
                  ("端末種別", "広告種別", "広告媒体", "キーワード") if g(f, k, prefix=False)))


def parse_a3(text, meta):
    f = parse_known(text, A3_KEYS, multiline=["自由欄", "住所"], stop_re=A3_STOP)
    free = g(f, "自由欄", prefix=False)
    addr = join(g(f, "郵便番号", prefix=False), g(f, "住所", prefix=False), sep=" ")
    return dict(
        fields=f,
        inquired_at=g(f, "CV日時", prefix=False),
        customer_name=join(g(f, "氏名", prefix=False), g(f, "会社名", prefix=False)),
        phone=norm_phone(g(f, "電話番号", prefix=False)),
        email=g(f, "メールアドレス", prefix=False),
        address=addr,
        area=extract_area(g(f, "住所", prefix=False)),
        work_type=g(f, "お問い合わせ項目", prefix=False),
        scale=guess_scale(free),
        desired_at="",
        source_detail=g(f, "広告媒体", prefix=False),
        note=join(("自由欄: " + free) if free else "", _ad_note(f),
                  ("gclid: " + g(f, "広告クリックID", "gclid", "GCLID", prefix=False))
                  if g(f, "広告クリックID", "gclid", "GCLID", prefix=False) else "", sep="\n"),
    )


B1_KEYS = ["サイトURL", "発信日時", "発信者電話番号", "宛先電話番号", "広告クリックID",
           "端末種別", "広告種別", "広告媒体", "キーワード"]


def _area_from_url(url):
    host = urlparse(url).hostname or ""
    sub = host.split(".")[0] if host else ""
    return config.SUBDOMAIN_AREA.get(sub, "")


def parse_b1(text, meta):
    f = parse_known(text, B1_KEYS)
    site = g(f, "サイトURL", prefix=False)
    area = _area_from_url(site) or _area_from_url("https://" + (meta.get("sender_domain") or ""))
    return dict(
        fields=f,
        inquired_at=g(f, "発信日時", prefix=False),
        customer_name="",
        phone=norm_phone(g(f, "発信者電話番号", prefix=False)),
        area=area + ("（サイト）" if area else ""),
        work_type="電話入電",
        scale="",
        source_detail=site,
        detail_url=site,
        note=join("宛先: " + g(f, "宛先電話番号", prefix=False), _ad_note(f), sep="\n"),
        flags=["折り返し要（氏名未取得）"],
    )


CDB_KEYS = ["計測番号", "発信者番号", "入電日時", "アカウント名", "キャンペーン名", "観測点名",
            "コンバージョントリガ名", "通話時間(秒)", "通話時間", "通話切断理由", "入電ID", "PV数"]


def parse_cdb(text, meta):
    f = parse_known(text, CDB_KEYS)
    secs = g(f, "通話時間(秒)", "通話時間", prefix=False)
    flags = ["折り返し要（氏名未取得）"]
    try:
        if int(re.sub(r"\D", "", secs) or -1) < config.SHORT_CALL_SECONDS:
            flags.append(f"短時間通話（{secs}秒）")
    except ValueError:
        pass
    return dict(
        fields=f,
        source_code=resolve_cdb_account(f),
        case_no=g(f, "入電ID", prefix=False),
        inquired_at=g(f, "入電日時", prefix=False),
        customer_name="",
        phone=norm_phone(g(f, "発信者番号", prefix=False)),
        area=g(f, "観測点名", prefix=False),
        work_type=join("電話入電", g(f, "キャンペーン名", prefix=False)),
        scale="",
        source_detail=join(g(f, "アカウント名", prefix=False), g(f, "キャンペーン名", prefix=False)),
        note=join(
            f"通話時間: {secs}秒" if secs else "",
            ("切断理由: " + g(f, "通話切断理由", prefix=False)) if g(f, "通話切断理由", prefix=False) else "",
            ("計測番号: " + g(f, "計測番号", prefix=False)) if g(f, "計測番号", prefix=False) else "",
            ("CVトリガ: " + g(f, "コンバージョントリガ名", prefix=False)) if g(f, "コンバージョントリガ名", prefix=False) else "",
            ("PV数: " + g(f, "PV数", prefix=False)) if g(f, "PV数", prefix=False) else "",
            sep="\n",
        ),
        flags=flags,
    )


C1_KEYS = ["案件詳細URL", "都道府県", "郵便番号", "想定工事規模"]


def parse_c1(text, meta):
    # 営業ノウハウ文が長いので、項目名の完全一致だけで拾う
    f = parse_known(text, C1_KEYS)
    url = first_url(g(f, "案件詳細URL", prefix=False)) or first_url(text, "package_estimate_shops")
    m = re.search(r"package_estimate_shops/(\d+)", url)
    brand = ""
    bm = re.search(r"^\s*(.+?)\s*ご担当者様", text, re.M)
    if bm:
        brand = bm.group(1).strip()
    pref = g(f, "都道府県", prefix=False)
    zipc = g(f, "郵便番号", prefix=False)
    return dict(
        fields=f,
        case_no=m.group(1) if m else "",
        detail_url=url,
        brand=brand,
        customer_name="",
        phone="",
        area=join(pref, ("〒" + zipc) if zipc else "", sep=" "),
        work_type=meta.get("subject", "")[:60],
        scale=g(f, "想定工事規模", prefix=False),
        source_detail=("宛先: " + brand) if brand else "",
        flags=["氏名・電話は管理画面で確認"],
    )


def parse_unknown(text, meta):
    return dict(fields={}, work_type=meta.get("subject", ""), note=text[:2000],
                flags=["送客元を判別できませんでした"])


PARSERS = {"A-1": parse_a1, "A-2": parse_a2, "A-3": parse_a3, "B-1": parse_b1,
           "B-CDB": parse_cdb, "C-1": parse_c1, "UNKNOWN": parse_unknown}


# ------------------------------------------------------------------ 入口
def parse_email_text(body: str, meta: dict) -> dict:
    """本文＋メタ情報（subject, sender_domains, received_at）→ 統一スキーマ。"""
    text = normalize(body)
    code = detect_source(meta.get("sender_domains", []), text)
    lead = PARSERS[code](text, meta)
    code = lead.pop("source_code", code)
    cfg = config.SOURCES[code]
    lead["source_code"] = code
    lead["source_label"] = cfg["label"]

    received = meta.get("received_at")
    inquired = parse_dt(lead.get("inquired_at", ""), base=received) or received

    # 連絡期限 = 希望日時の N 日前（第1候補など、最初に読み取れた日時を採用）
    mail_deadline = lead.get("contact_deadline", "")
    desired_dt, has_time = parse_dt_ex(lead.get("desired_at", ""), base=inquired or received)
    deadline_dt, basis = None, ""
    if desired_dt:
        deadline_dt = desired_dt - timedelta(days=config.CONTACT_LEAD_DAYS)
        if not has_time:
            deadline_dt = deadline_dt.replace(hour=23, minute=59)
        basis = f"希望日の{config.CONTACT_LEAD_DAYS}日前"
    elif mail_deadline:
        deadline_dt = parse_dt(mail_deadline, base=inquired or received)
        basis = "送客元指定" if deadline_dt else ""
    if deadline_dt:
        lead["contact_deadline"] = deadline_dt.strftime("%Y/%m/%d %H:%M")
    else:
        lead["contact_deadline"] = ""
    if mail_deadline and basis != "送客元指定":
        lead["note"] = join(f"送客元指定の連絡期限: {mail_deadline}", lead.get("note", ""), sep="\n")
    # メール内の日時は日本時間。ブラウザ側で正しく残り時間を出すため +09:00 を付ける
    lead["deadline_iso"] = deadline_dt.isoformat(timespec="minutes") + "+09:00" if deadline_dt else ""
    lead["deadline_basis"] = basis
    lead["inquired_iso"] = inquired.isoformat(timespec="minutes") if inquired else ""
    lead.setdefault("flags", [])
    lead.setdefault("contract_type", "")
    return lead
