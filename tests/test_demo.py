import json
import os
import tempfile
import unittest

from mail_dashboard import demo

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")


class DemoExportTests(unittest.TestCase):
    def test_export_matches_committed_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "demo.json")
            n = demo.export(SAMPLES, out)
            data = json.load(open(out, encoding="utf-8"))
        self.assertEqual(n, len(data["leads"]))
        self.assertTrue(data["demo"])
        self.assertEqual({l["source_code"] for l in data["leads"]},
                         {"A-1", "A-2", "A-3", "B-1", "B-2", "B-3", "C-1"})
        self.assertTrue(all(l["received_at"] and l["status"] for l in data["leads"]))
        # 公開用ファイルがサンプル・パーサーと食い違っていないこと（変更したら export-demo を再実行）
        with open(os.path.join(SAMPLES, "..", "public", "demo-data.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), data)


if __name__ == "__main__":
    unittest.main()
