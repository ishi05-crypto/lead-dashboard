"""HTTP API（/api/ingest, /api/leads）のテスト。DATABASE_URL があれば PostgreSQL で実行。"""
import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from unittest import mock

from mail_dashboard import db, server

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")


def sample(name):
    with open(os.path.join(SAMPLES, name), "rb") as fh:
        return fh.read()


def unique(raw: bytes) -> bytes:
    """Message-ID を毎回変えて、PostgreSQL 上でも重複扱いされないようにする。"""
    return raw.replace(b"@sample>", f".{uuid.uuid4().hex}@sample>".encode(), 1)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.Handler.db_path = os.path.join(cls.tmp.name, "t.db")
        cls.env = mock.patch.dict(os.environ, {"INGEST_TOKEN": "tok", "DASHBOARD_USER": "admin",
                                               "DASHBOARD_PASSWORD": "pw"})
        cls.env.start()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.env.stop()
        cls.tmp.cleanup()

    def req(self, method, path, body=None, ctype=None, auth=None):
        r = urllib.request.Request(self.base + path, data=body, method=method)
        if ctype:
            r.add_header("Content-Type", ctype)
        if auth:
            r.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
        try:
            with urllib.request.urlopen(r) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_ingest_requires_token(self):
        code, _ = self.req("POST", "/api/ingest", sample("a1_share_tech.eml"), "message/rfc822")
        self.assertEqual(code, 403)

    def test_ingest_raw_and_duplicate(self):
        raw = unique(sample("a1_share_tech.eml"))
        code, res = self.req("POST", "/api/ingest?token=tok", raw, "message/rfc822")
        self.assertEqual((code, res["result"], res["source"]), (200, "inserted", "A-1"))
        code, res = self.req("POST", "/api/ingest?token=tok", raw, "message/rfc822")
        self.assertEqual(res["result"], "duplicate")

    def test_ingest_cloudmailin_multipart_raw(self):
        raw = unique(sample("c1_rehome.eml"))
        b = "----bnd"
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"envelope[to]\"\r\n\r\nx@cloudmailin.net\r\n"
                f"--{b}\r\nContent-Disposition: form-data; name=\"message\"; filename=\"message.eml\"\r\n"
                f"Content-Type: message/rfc822\r\n\r\n").encode() + raw + f"\r\n--{b}--\r\n".encode()
        code, res = self.req("POST", "/api/ingest?token=tok", body, f"multipart/form-data; boundary={b}")
        self.assertEqual((code, res["source"]), (200, "C-1"), res)

    def test_ingest_postmark_json(self):
        raw = unique(sample("a2_ace_oniwa.eml")).decode()
        code, res = self.req("POST", "/api/ingest?token=tok",
                             json.dumps({"From": "x", "RawEmail": raw}).encode(), "application/json")
        self.assertEqual((code, res["source"]), (200, "A-2"), res)

    def test_ingest_json_without_raw(self):
        body = json.dumps({"headers": {"from": "notice@call.omnidatabank.jp", "subject": "入電",
                                       "message_id": f"<{uuid.uuid4().hex}@x>"},
                           "plain": "計測番号：0800\n発信者番号：090-1111-2222\nアカウント名：EPARK\n"
                                    "キャンペーン名：a\n入電ID：9\n"}).encode()
        code, res = self.req("POST", "/api/ingest?token=tok", body, "application/json")
        self.assertEqual((code, res["source"]), (200, "B-2"), res)

    def test_dashboard_auth_and_update(self):
        self.assertEqual(self.req("GET", "/api/leads")[0], 401)
        _, res = self.req("POST", "/api/ingest?token=tok", unique(sample("b1_wonder.eml")), "message/rfc822")
        code, data = self.req("GET", "/api/leads", auth="admin:pw")
        self.assertEqual(code, 200)
        self.assertIn(res["id"], [l["id"] for l in data["leads"]])
        code, _ = self.req("POST", "/api/leads", json.dumps({"id": res["id"], "status": "対応中",
                                                             "memo": "折り返し済"}).encode(),
                           "application/json", auth="admin:pw")
        self.assertEqual(code, 200)
        lead = next(l for l in self.req("GET", "/api/leads", auth="admin:pw")[1]["leads"] if l["id"] == res["id"])
        self.assertEqual((lead["status"], lead["memo"]), ("対応中", "折り返し済"))


if __name__ == "__main__":
    unittest.main()
