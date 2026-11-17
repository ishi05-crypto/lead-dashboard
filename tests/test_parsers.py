import glob
import os
import sqlite3
import unittest
from email.message import EmailMessage

from mail_dashboard import db
from mail_dashboard.mailio import read_message
from mail_dashboard.parsers import parse_email_text

HERE = os.path.dirname(__file__)
SAMPLES = os.path.join(HERE, "..", "samples")


def parse_sample(name):
    with open(os.path.join(SAMPLES, name), "rb") as fh:
        info = read_message(fh.read())
    return parse_email_text(info["body"], info)


class ParserTests(unittest.TestCase):
    def test_a1_share_tech(self):
        l = parse_sample("a1_share_tech.eml")
        self.assertEqual(l["source_code"], "A-1")
        self.assertEqual(l["customer_name"], "山田 太郎")
        self.assertEqual(l["phone"], "090-1234-5678")
        self.assertEqual(l["area"], "茨城県水戸市")
        self.assertEqual(l["source_detail"], "伐採110番")  # ヒアリング指示は除去
        self.assertTrue(any("ヒア" in f for f in l["flags"]))
        # 連絡期限 = 希望日(11/24, 時刻なし)の7日前 23:59。送客元指定の期限は備考に残す
        self.assertEqual(l["deadline_iso"], "2026-11-17T23:59+09:00")
        self.assertEqual(l["deadline_basis"], "希望日の7日前")
        self.assertIn("送客元指定の連絡期限", l["note"])
        self.assertIn("年内に対応希望", l["note"])  # 【状況】の複数行

    def test_a2_ace(self):
        l = parse_sample("a2_ace_oniwa.eml")
        self.assertEqual(l["source_code"], "A-2")
        self.assertEqual(l["case_no"], "OR5821")
        self.assertEqual(l["customer_kana"], "さとう はなこ")
        self.assertEqual(l["contract_type"], "受注ベース")
        self.assertIn("4〜6本", l["scale"])
        self.assertIn("11/21", l["desired_at"])
        self.assertIn("11/22", l["desired_at"])
        self.assertEqual(l["deadline_iso"], "2026-11-14T23:59+09:00")  # 第1候補 11/21 の7日前

    def test_deadline_with_time_and_no_desired(self):
        l = parse_sample("a2_ace_oniwa_2.eml")
        self.assertEqual(l["deadline_iso"], "2026-12-05T10:00+09:00")  # 時刻指定あり → 同時刻
        b1 = parse_sample("b1_wonder.eml")
        self.assertEqual(b1["deadline_iso"], "")  # 希望日時なし → 期限なし

    def test_year_rollover(self):
        from datetime import datetime
        from mail_dashboard.textutil import parse_dt
        self.assertEqual(parse_dt("1/10(日) 午前", base=datetime(2026, 12, 20)), datetime(2027, 1, 10))

    def test_a3_hayabusa_ignores_kpi_table(self):
        l = parse_sample("a3_hayabusa_lp.eml")
        self.assertEqual(l["source_code"], "A-3")
        self.assertEqual(l["customer_name"], "鈴木 一郎")
        self.assertEqual(l["area"], "茨城県つくば市")
        self.assertEqual(l["fields"]["キーワード"], "草刈り 業者 つくば")
        self.assertIn("来週中", l["note"])
        self.assertNotIn("成約率", str(l["fields"]))

    def test_b1_wonder(self):
        l = parse_sample("b1_wonder.eml")
        self.assertEqual(l["source_code"], "B-1")
        self.assertEqual(l["phone"], "045-111-2222")
        self.assertIn("神奈川県", l["area"])

    def test_cdb_split_by_account(self):
        self.assertEqual(parse_sample("b2_epark.eml")["source_code"], "B-2")
        b3 = parse_sample("b3_aoi.eml")
        self.assertEqual(b3["source_code"], "B-3")
        self.assertTrue(any("短時間" in f for f in b3["flags"]))

    def test_c1_rehome(self):
        l = parse_sample("c1_rehome.eml")
        self.assertEqual(l["source_code"], "C-1")
        self.assertEqual(l["case_no"], "123456")
        self.assertEqual(l["brand"], "はなまる造園")
        self.assertEqual(l["scale"], "50万円〜100万円")
        self.assertEqual(l["area"], "千葉県 〒270-1234")

    def test_iso2022jp_and_body_detection(self):
        # 転送などで送信元ドメインが変わっても本文の特徴で判別できる
        m = EmailMessage()
        m["From"] = "someone@forwarder.example"
        m["Subject"] = "Fwd: 入電"
        m["Message-ID"] = "<jis@test>"
        m.set_content("計測番号：0800\n発信者番号：03-1111-2222\n入電日時：2026/11/17 9:00\n"
                      "アカウント名：EPARK\nキャンペーン名：x\n入電ID：1\n", charset="iso-2022-jp")
        info = read_message(m.as_bytes())
        l = parse_email_text(info["body"], info)
        self.assertEqual(l["source_code"], "B-2")
        self.assertEqual(l["phone"], "03-1111-2222")

    def test_ingest_dedupes(self):
        con = db.connect(path=":memory:", url="")
        path = sorted(glob.glob(os.path.join(SAMPLES, "*.eml")))[0]
        with open(path, "rb") as fh:
            raw = fh.read()
        self.assertEqual(db.ingest_raw(con, raw)[1], "inserted")
        self.assertEqual(db.ingest_raw(con, raw)[1], "duplicate")
        self.assertEqual(db.reparse_all(con), 1)


if __name__ == "__main__":
    unittest.main()
