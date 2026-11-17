"""本文テキストの正規化・項目抽出・日時/住所/電話番号の整形ヘルパー。"""
import re
import unicodedata
from datetime import datetime, timedelta

SEP_RE = re.compile(r"^\s*[-=━─_*・〓◆◇]{4,}\s*$")
URL_RE = re.compile(r"https?://[^\s<>\"'）)]+")


def normalize(text: str) -> str:
    """全角英数・記号を半角に揃え（NFKC）、改行を \n に統一する。

    これで「：」と「:」、「（）」と「()」などの揺れを吸収できる。
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("　", " ")
    return text


def _norm_key(k: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", k))


def _put(fields, key, value):
    key = _norm_key(key)
    if key in fields:  # 同名キーは最初を優先、2つ目以降は連番で保持
        i = 2
        while f"{key}#{i}" in fields:
            i += 1
        key = f"{key}#{i}"
    fields[key] = value.strip()
    return key


# ---------------------------------------------------------------- 記号付き形式
MARK_RE = re.compile(r"^\s*■\s*([^:\n]{1,40}?)\s*(?::\s*(.*))?$")
BRACKET_RE = re.compile(r"^\s*【([^】]{1,40})】\s*:?\s*(.*)$")


def parse_marked(text: str) -> dict:
    """`■項目:値` と `【項目】値` を拾う（A-1 / A-2 用）。

    次の項目が出るまでの行は直前の項目の続き（複数行の値）として連結する。
    区切り線が来たら項目を閉じる。
    """
    fields, cur = {}, None
    for line in text.split("\n"):
        m = MARK_RE.match(line) or BRACKET_RE.match(line)
        if m:
            cur = _put(fields, m.group(1), m.group(2) or "")
            continue
        if SEP_RE.match(line):
            cur = None
            continue
        if cur is not None and line.strip():
            fields[cur] = (fields[cur] + "\n" + line.strip()).strip()
    return fields


# ---------------------------------------------------------------- 既知項目のみ
def parse_known(text: str, keys, multiline=(), stop_re=None) -> dict:
    """項目名の完全一致でだけ拾う（A-3 / B / C-1 用）。

    `項目: 値` / `■項目:値` / 項目名だけの行＋次行に値、のどれにも対応。
    本文中の営業文・成約率表などは項目名に一致しないので無視される。
    """
    keys = sorted({_norm_key(k) for k in keys}, key=len, reverse=True)
    multiline = {_norm_key(k) for k in multiline}
    pat = re.compile(
        r"^\s*[■・●◆]?\s*(" + "|".join(map(re.escape, keys)) + r")\s*(?:[:：]\s*(.*))?$"
    )
    fields, cur, pending = {}, None, None
    for line in text.split("\n"):
        if stop_re and stop_re.search(line):
            cur = pending = None
            continue
        m = pat.match(line)
        if m:
            key, val = m.group(1), m.group(2)
            if key in fields:  # 2回目以降は無視（表の見出し等の誤検出防止）
                cur = pending = None
                continue
            fields[key] = (val or "").strip()
            pending = key if not fields[key] else None
            cur = key if key in multiline else None
            continue
        if SEP_RE.match(line):
            cur = pending = None
            continue
        s = line.strip()
        if not s:
            continue
        if pending:
            fields[pending] = s
            cur = pending if pending in multiline else None
            pending = None
        elif cur:
            fields[cur] = (fields[cur] + "\n" + s).strip()
    return fields


def g(fields: dict, *candidates, prefix=True) -> str:
    """候補名で値を取り出す。完全一致 → 前方一致（prefix=True のとき）。"""
    for c in candidates:
        v = fields.get(_norm_key(c))
        if v:
            return v
    if prefix:
        for c in candidates:
            c = _norm_key(c)
            for k, v in fields.items():
                if k.startswith(c) and v and "#" not in k:
                    return v
    return ""


def join(*parts, sep=" / "):
    return sep.join(p.strip() for p in parts if p and p.strip())


def first_url(text, contains=""):
    for u in URL_RE.findall(text or ""):
        if contains in u:
            return u
    return ""


# ---------------------------------------------------------------- 日時
_DT_FULL = re.compile(
    r"(\d{4})\s*[/\-年.]\s*(\d{1,2})\s*[/\-月.]\s*(\d{1,2})\s*日?"
    r"(?:\s*[(（][^)）]{1,3}[)）])?\s*(?:(\d{1,2})\s*[:時]\s*(\d{1,2})?)?"
)
_DT_MD = re.compile(
    r"(\d{1,2})\s*[/月]\s*(\d{1,2})\s*日?(?:\s*[(（][^)）]{1,3}[)）])?\s*(?:(\d{1,2})\s*[:時]\s*(\d{1,2})?)?"
)


def parse_dt_ex(text: str, base: datetime | None = None):
    """日本語メールに出てくる日時表記を (datetime, 時刻指定の有無) に変換する。"""
    if not text:
        return None, False
    t = normalize(text)
    m = _DT_FULL.search(t)
    try:
        if m:
            y, mo, d, h, mi = m.groups()
            return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0)), h is not None
        m = _DT_MD.search(t)
        if m and base:
            mo, d, h, mi = m.groups()
            dt = datetime(base.year, int(mo), int(d), int(h or 0), int(mi or 0))
            if dt < base - timedelta(days=60):  # 12月受信で「1/10」等 → 翌年
                dt = dt.replace(year=dt.year + 1)
            return dt, h is not None
    except ValueError:
        pass
    return None, False


def parse_dt(text: str, base: datetime | None = None) -> datetime | None:
    return parse_dt_ex(text, base)[0]


def add_hours(dt: datetime | None, hours):
    if dt is None or hours is None:
        return None
    return dt + timedelta(hours=hours)


# ---------------------------------------------------------------- 住所・電話
_PREF = r"(北海道|東京都|京都府|大阪府|[^\s\d]{2,3}県)"
_CITY = r"([^\s\d]+?郡[^\s\d]+?[町村]|[^\s\d]+?市[^\s\d]+?区|[^\s\d]+?[市区町村])"


def extract_area(address: str) -> str:
    """住所から「都道府県＋市区町村」を取り出す。〒・カナ併記は除去。"""
    if not address:
        return ""
    a = normalize(address)
    a = re.sub(r"〒?\s*\d{3}-?\d{4}", " ", a)
    a = re.sub(r"[(（][^)）]*[)）]", " ", a)  # (カナ) を除去
    a = re.sub(r"[ァ-ヴー・]{4,}", " ", a)  # 括弧なしのカナ併記行
    a = " ".join(x for x in a.split() if x)
    m = re.search(_PREF + r"?\s*" + _CITY, a)
    if m and (m.group(1) or m.group(2)):
        return join(m.group(1) or "", m.group(2) or "", sep="")
    m = re.search(_PREF, a)
    if m:
        return m.group(1)
    return a[:20]


def norm_phone(p: str) -> str:
    if not p:
        return ""
    p = normalize(p)
    p = re.sub(r"[‐‑–—―ー−]", "-", p)
    m = re.search(r"\+?\d[\d\-\s]{8,}\d", p)
    return re.sub(r"\s", "", m.group(0)) if m else p.strip()


def guess_scale(text: str) -> str:
    """自由記述から本数・高さ・面積らしき表現を拾う（項目が無い送客元の補完）。"""
    if not text:
        return ""
    t = normalize(text)
    hits = re.findall(
        r"\d+(?:\.\d+)?\s*(?:本|株|m|メートル|㎡|平米|坪)(?:程度|くらい|位|ほど)?", t
    )
    return "・".join(dict.fromkeys(h.replace(" ", "") for h in hits))[:60]


HEARING_RE = re.compile(r"【[^】]*ヒア[^】]*】")


def strip_hearing(text: str):
    """「【電番号ヒアする！】」などヒアリング指示を除去し、(本文, 指示リスト) を返す。"""
    found = HEARING_RE.findall(text or "")
    return HEARING_RE.sub("", text or "").strip(), found
