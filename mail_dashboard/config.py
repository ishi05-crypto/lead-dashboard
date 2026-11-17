"""送客元ごとの設定。運用に合わせてここを編集する。

連絡期限のルール: 希望日時の CONTACT_LEAD_DAYS 日前。
  - 希望日時に時刻があれば同時刻、日付だけなら その日の 23:59 を期限とする。
  - 希望日時が読み取れない案件は、本文に送客元指定の期限があればそれを使い、無ければ「期限なし」。
"""

SOURCES = {
    "A-1": {
        "label": "シェアテクノロジー（伐採110番）",
        "domains": ["partner.rits-orange.jp"],
    },
    "A-2": {
        "label": "Ace（お庭センター）",
        "domains": ["oniwa.link329.com"],
    },
    "A-3": {
        "label": "はやぶさLP（茨城）",
        "domains": ["ibaraki.hayabusa-oniwa.com"],
    },
    "B-1": {
        "label": "wonder事務局（入電）",
        "domains": ["kanagawa.hayabusa-oniwa.com"],
    },
    # B-2 / B-3 は同じドメイン・同じフォーマット。アカウント名＋キャンペーン名で判別する。
    "B-2": {
        "label": "EPARKレスキュー（入電）",
        "domains": ["call.omnidatabank.jp"],
        "account_keywords": ["EPARK", "イーパーク"],
    },
    "B-3": {
        "label": "あおい総合研究所（入電）",
        "domains": ["call.omnidatabank.jp"],
        "account_keywords": ["あおい", "アオイ", "aoi"],
    },
    "B-X": {
        "label": "コールデータバンク（アカウント未登録）",
        "domains": [],
    },
    "C-1": {
        "label": "リショップナビ",
        "domains": ["rehome-navi.com"],
    },
    "UNKNOWN": {
        "label": "未判別",
        "domains": [],
    },
}

# はやぶさ系サブドメイン → エリア（B-1 などエリア情報が本文に無い場合の補完）
SUBDOMAIN_AREA = {
    "ibaraki": "茨城県", "kanagawa": "神奈川県", "tokyo": "東京都", "chiba": "千葉県",
    "saitama": "埼玉県", "tochigi": "栃木県", "gunma": "群馬県", "osaka": "大阪府",
    "hyogo": "兵庫県", "kyoto": "京都府", "aichi": "愛知県", "shizuoka": "静岡県",
}

# 通話時間（秒）がこれ未満の入電には「短時間通話」フラグを付ける
SHORT_CALL_SECONDS = 15

# ステータス候補（ダッシュボードで切替）
STATUSES = ["未対応", "対応中", "アポ確定", "完了", "対象外"]

# 連絡期限 = 希望日時の N 日前
CONTACT_LEAD_DAYS = 7
# ダッシュボードで「期限間近」とみなす残り時間（時間）
DEADLINE_SOON_HOURS = 24
# 未対応のまま受信からこの時間を超えたら経過時間を強調表示（時間）
ELAPSED_ALERT_HOURS = 24
