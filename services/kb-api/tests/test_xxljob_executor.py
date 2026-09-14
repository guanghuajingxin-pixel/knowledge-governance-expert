"""XXL-Job 接入单测：cron→Quartz 转换规则 + 执行器协议（fake admin 收 registry/callback）。"""
import json
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile

from app.services.sync.xxljob_admin import crontab_to_quartz
from app.services.sync.xxljob_executor import XxlJobExecutor


class CronConversionTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(crontab_to_quartz("0 2 * * *"), "0 0 2 * * ?")
        self.assertEqual(crontab_to_quartz("*/5 * * * *"), "0 */5 * * * ?")
        self.assertEqual(crontab_to_quartz("30 1 * * 1-5"), "0 30 1 ? * 2-6")
        self.assertEqual(crontab_to_quartz("0 3 1 * *"), "0 0 3 1 * ?")

    def test_dow_wrap(self):
        # crontab 0/7=周日 → Quartz 1；7 同样归一
        self.assertEqual(crontab_to_quartz("0 22 * * 0"), "0 0 22 ? * 1")
        self.assertEqual(crontab_to_quartz("15 8 * * 7"), "0 15 8 ? * 1")

    def test_names(self):
        self.assertEqual(crontab_to_quartz("0 9 * * mon-fri"), "0 0 9 ? * MON-FRI")
        self.assertEqual(crontab_to_quartz("0 8 * * sun"), "0 0 8 ? * SUN")

    def test_reject(self):
        for bad in ("* * * *", "0 2 1 * 3", "0 2 * * xyz"):
            with self.assertRaises(ValueError):
                crontab_to_quartz(bad)


class _FakeAdmin(BaseHTTPRequestHandler):
    received: dict = {"registry": 0, "registry_value": None, "callback": []}

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/registry":
            self.received["registry"] += 1
            self.received["registry_value"] = body.get("registryValue")
        elif self.path == "/api/callback":
            self.received["callback"].extend(body)
        payload = json.dumps({"code": 200, "msg": None}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


class ExecutorProtocolTest(unittest.TestCase):
    """fake admin + 真执行器：/run ack、handler 执行、/log 拉取、callback 上报、注册立即上报。"""

    def test_protocol(self):
        _FakeAdmin.received = {"registry": 0, "registry_value": None, "callback": []}
        fake = ThreadingHTTPServer(("127.0.0.1", 18099), _FakeAdmin)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            ex = XxlJobExecutor("http://127.0.0.1:18099", "", "test-exec",
                                "127.0.0.1", 9998, Path(tmp))

            def echo_handler(param, job_log):
                job_log.log(f"handler echo param={param}")
                return 200, f"echoed {param}"

            ex.start({"echo": echo_handler})
            try:
                time.sleep(1.5)
                now_ms = int(time.time() * 1000)
                ack = _post("http://127.0.0.1:9998/run", {
                    "jobId": 1, "executorHandler": "echo", "executorParams": "42",
                    "glueType": "BEAN", "logId": 1001, "logDateTim": now_ms})
                self.assertEqual(ack["code"], 200)
                bad = _post("http://127.0.0.1:9998/run", {
                    "jobId": 2, "executorHandler": "nope", "glueType": "BEAN",
                    "logId": 1002, "logDateTim": now_ms})
                self.assertEqual(bad["code"], 500)
                self.assertEqual(_post("http://127.0.0.1:9998/beat", {})["code"], 200)

                deadline = time.time() + 5
                content = ""
                while time.time() < deadline:
                    resp = _post("http://127.0.0.1:9998/log", {"logId": 1001, "fromLineNum": 1})
                    content = resp["content"]["logContent"]
                    if "任务结束" in content:
                        break
                    time.sleep(0.3)
                self.assertIn("handler echo param=42", content)
                self.assertIn("任务结束: code=200", content)

                deadline = time.time() + 5
                while time.time() < deadline and not _FakeAdmin.received["callback"]:
                    time.sleep(0.3)
                self.assertGreaterEqual(_FakeAdmin.received["registry"], 1)
                self.assertEqual(_FakeAdmin.received["registry_value"], "http://127.0.0.1:9998")
                self.assertTrue(any(c["logId"] == 1001 and c["handleCode"] == 200
                                    for c in _FakeAdmin.received["callback"]))
            finally:
                ex.stop()
                fake.shutdown()


if __name__ == "__main__":
    unittest.main()
