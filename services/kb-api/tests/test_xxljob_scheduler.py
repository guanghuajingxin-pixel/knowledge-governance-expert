"""调度作业同步集成测试：fake XXL-Job admin UI + sqlite，验证 scheduler 幂等同步逻辑。

覆盖：启用源建作业（cron 转 Quartz、handler/param 正确、启动）、停用源停作业、
二次同步走 update 不重复建、删除源清理作业、xxl_job_id 回存。
"""
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kb_common.models import SyncSource
from app.services.sync import scheduler
from app.services.sync import engine as sync_engine
from app.services.sync.xxljob_admin import XxlJobAdminClient


class _FakeAdminUI(BaseHTTPRequestHandler):
    """模拟 XXL-Job admin 的表单接口（ReturnT JSON）。"""
    state: dict = {}

    def log_message(self, fmt, *args):
        pass

    def _form(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return {k: v[0] for k, v in parse_qs(raw.decode()).items()}

    def _json(self, payload: dict, status: int = 200, cookie: bool = False) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json;charset=UTF-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", "XXL_JOB_LOGIN_ID=fake; Path=/")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        st = self.__class__.state
        form = self._form()
        path = self.path
        if path == "/login":
            self._json({"code": 200}, status=302, cookie=True)
        elif path == "/jobgroup/pageList":
            groups = [g for g in st["groups"] if g["appname"] == form.get("appname", "")]
            self._json({"code": 200, "data": groups, "recordsTotal": len(groups)})
        elif path == "/jobgroup/add":
            gid = st["group_seq"]
            st["group_seq"] += 1
            st["groups"].append({"id": gid, "appname": form["appname"], "title": form.get("title", "")})
            self._json({"code": 200})
        elif path == "/jobinfo/add":
            jid = st["job_seq"]
            st["job_seq"] += 1
            st["jobs"][jid] = {**form, "id": jid, "triggerStatus": 0}
            st["calls"].append(("add", jid))
            self._json({"code": 200, "content": jid})
        elif path == "/jobinfo/update":
            jid = int(form["id"])
            if jid not in st["jobs"]:
                self._json({"code": 500, "msg": "job not found"})
                return
            st["jobs"][jid].update(form)
            st["calls"].append(("update", jid))
            self._json({"code": 200})
        elif path == "/jobinfo/start":
            jid = int(form["id"])
            st["jobs"][jid]["triggerStatus"] = 1
            st["calls"].append(("start", jid))
            self._json({"code": 200})
        elif path == "/jobinfo/stop":
            jid = int(form["id"])
            if jid in st["jobs"]:
                st["jobs"][jid]["triggerStatus"] = 0
            st["calls"].append(("stop", jid))
            self._json({"code": 200})
        elif path == "/jobinfo/remove":
            jid = int(form["id"])
            st["jobs"].pop(jid, None)
            st["calls"].append(("remove", jid))
            self._json({"code": 200})
        elif path == "/jobinfo/trigger":
            jid = int(form["id"])
            st["calls"].append(("trigger", jid, form.get("executorParam", "")))
            self._json({"code": 200})
        else:
            self._json({"code": 500, "msg": f"unknown {path}"})


class SchedulerJobSyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _FakeAdminUI.state = {"groups": [], "jobs": {}, "calls": [],
                              "group_seq": 11, "job_seq": 101}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 18100), _FakeAdminUI)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _FakeAdminUI.state = {"groups": [], "jobs": {}, "calls": [],
                              "group_seq": 11, "job_seq": 101}
        self.sql = create_engine("sqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
        SyncSource.__table__.create(self.sql)
        self.sessions = sessionmaker(bind=self.sql, expire_on_commit=False)
        with self.sessions() as db:
            self.enabled = SyncSource(name="启用源", workspace_id="w", root_node_id="r",
                                      dify_dataset_name="t", enabled=True, cron="0 2 * * *")
            self.disabled = SyncSource(name="停用源", workspace_id="w", root_node_id="r2",
                                       dify_dataset_name="t", enabled=False, cron="*/5 * * * *",
                                       xxl_job_id=777)
            db.add_all([self.enabled, self.disabled])
            db.commit()
            self.enabled_id, self.disabled_id = self.enabled.id, self.disabled.id
        self.addCleanup(self.sql.dispose)

        self.client = XxlJobAdminClient("http://127.0.0.1:18100", "admin", "123456")
        self.patches = [
            patch.object(scheduler, "SyncSessionLocal", self.sessions),
            patch.object(scheduler, "get_admin_client", lambda: self.client),
            patch.object(scheduler, "get_settings", lambda: SimpleNamespace(
                xxl_job_executor_appname="kge-sync-executor", xxl_job_enabled=True)),
            patch.object(scheduler, "_group_id", None),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def _jobs(self):
        return _FakeAdminUI.state["jobs"]

    def _calls(self):
        return _FakeAdminUI.state["calls"]

    def test_sync_creates_and_stops(self):
        active = scheduler.sync_all_jobs()
        self.assertEqual(active, 1)
        jobs = list(self._jobs().values())
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["executorHandler"], "syncSource")
        self.assertEqual(job["executorParam"], str(self.enabled_id))
        self.assertEqual(job["scheduleConf"], "0 0 2 * * ?")
        self.assertEqual(job["scheduleType"], "CRON")
        self.assertEqual(job["glueType"], "BEAN")
        self.assertEqual(job["triggerStatus"], 1)
        self.assertIn(("stop", 777), self._calls())  # 停用源旧作业被停
        with self.sessions() as db:
            row = db.get(SyncSource, self.enabled_id)
            self.assertEqual(row.xxl_job_id, job["id"])

    def test_second_sync_updates_not_duplicates(self):
        scheduler.sync_all_jobs()
        first_id = list(self._jobs())[0]
        adds = [c for c in self._calls() if c[0] == "add"]
        self.assertEqual(len(adds), 1)
        _FakeAdminUI.state["calls"].clear()
        scheduler.sync_all_jobs()
        self.assertEqual(len(self._jobs()), 1)
        self.assertIn(("update", first_id), self._calls())
        self.assertNotIn("add", [c[0] for c in self._calls()])

    def test_remove_source_job(self):
        scheduler.sync_all_jobs()
        job_id = list(self._jobs())[0]
        scheduler.remove_source_job(job_id)
        self.assertIn(("remove", job_id), self._calls())
        self.assertEqual(self._jobs(), {})

    def test_invalid_cron_stops_old_job(self):
        with self.sessions() as db:
            row = db.get(SyncSource, self.enabled_id)
            row.cron = "0 2 1 * 3"  # 日周同时指定，Quartz 不支持
            row.xxl_job_id = 555
            db.commit()
        scheduler.sync_all_jobs()
        self.assertIn(("stop", 555), self._calls())
        self.assertEqual(self._jobs(), {})


    # ----- 触发链路（「确认并开始同步」→ XXL-Job） -----
    def _trigger_calls(self):
        return [c for c in self._calls() if c[0] == "trigger"]

    def test_trigger_goes_to_xxljob_with_operator(self):
        scheduler.sync_all_jobs()
        job_id = list(self._jobs())[0]
        _FakeAdminUI.state["calls"].clear()
        result = scheduler.trigger_source_sync(self.enabled_id, "alice")
        self.assertEqual(result["via"], "xxl-job")
        triggers = self._trigger_calls()
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0][1], job_id)
        param = json.loads(triggers[0][2])
        self.assertEqual(param["source_id"], self.enabled_id)
        self.assertEqual(param["operator"], "alice")
        self.assertEqual(param["trigger"], "manual")

    def test_trigger_creates_missing_job_first(self):
        result = scheduler.trigger_source_sync(self.enabled_id, "bob")
        self.assertEqual(result["via"], "xxl-job")
        self.assertEqual(len(self._trigger_calls()), 1)
        with self.sessions() as db:
            self.assertIsNotNone(db.get(SyncSource, self.enabled_id).xxl_job_id)

    def test_trigger_disabled_falls_back_to_direct(self):
        with patch.object(scheduler, "SyncSessionLocal", self.sessions), \
             patch.object(scheduler, "get_settings", lambda: SimpleNamespace(
                 xxl_job_executor_appname="kge-sync-executor", xxl_job_enabled=False)), \
             patch.object(sync_engine, "run_sync") as mock_run:
            result = scheduler.trigger_source_sync(self.enabled_id, "carol")
        self.assertEqual(result["via"], "direct")
        mock_run.assert_called_once_with(self.enabled_id, "manual", "carol")

    def test_handler_parses_json_param(self):
        with patch.object(scheduler, "run_sync", return_value={"status": "success", "message": "ok"}) as mock_run:
            code, _msg = scheduler._handle_sync_source(
                json.dumps({"source_id": self.enabled_id, "operator": "alice", "trigger": "manual"}),
                SimpleNamespace(log=lambda *a, **k: None))
        self.assertEqual(code, 200)
        mock_run.assert_called_once_with(self.enabled_id, "manual", "alice")

    def test_handler_plain_id_param(self):
        with patch.object(scheduler, "run_sync", return_value={"status": "success", "message": "ok"}) as mock_run:
            code, _msg = scheduler._handle_sync_source(
                str(self.enabled_id), SimpleNamespace(log=lambda *a, **k: None))
        self.assertEqual(code, 200)
        mock_run.assert_called_once_with(self.enabled_id, "schedule", "")


if __name__ == "__main__":
    unittest.main()
