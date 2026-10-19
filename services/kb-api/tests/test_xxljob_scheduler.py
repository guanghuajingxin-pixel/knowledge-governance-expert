"""调度作业集成测试：fake XXL-Job admin UI + sqlite，验证批处理作业注册与遗留作业清理。

定时编目已取消（自动同步走钉钉事件监听），XXL-Job 仅保留全局批处理作业（syncBatch tick）。
覆盖：cleanup_source_jobs 清理定时编目遗留作业（持久化 ID + 孤儿扫描、幂等）、
_apply_batch_job 幂等注册/启动、trigger_source_sync 进程内直跑、降级通道。
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
        elif path == "/jobinfo/pageList":
            handler = form.get("executorHandler", "")
            rows = [j for j in st["jobs"].values()
                    if not handler or j.get("executorHandler") == handler]
            self._json({"code": 200, "data": rows, "recordsTotal": len(rows)})
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


class CleanupSourceJobsTest(unittest.TestCase):
    """遗留 syncSource 作业清理：持久化 ID + 孤儿扫描 + 幂等。"""

    @classmethod
    def setUpClass(cls):
        _FakeAdminUI.state = {"groups": [], "jobs": {}, "calls": [],
                              "group_seq": 11, "job_seq": 101}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 18101), _FakeAdminUI)
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
            # 定时编目时代存量：启停两源均带 xxl_job_id（cron 列仅为历史兼容，不再使用）
            s1 = SyncSource(name="遗留源A", workspace_id="w", root_node_id="r",
                            dataset_name="t", enabled=True, xxl_job_id=777)
            s2 = SyncSource(name="遗留源B", workspace_id="w", root_node_id="r2",
                            dataset_name="t", enabled=False, xxl_job_id=888)
            db.add_all([s1, s2])
            db.commit()
            self.ids = (s1.id, s2.id)
        self.addCleanup(self.sql.dispose)
        self.client = XxlJobAdminClient("http://127.0.0.1:18101", "test-admin", "TestOnlyPass123!")
        # admin 侧预置：两个落库作业 + 一个孤儿 syncSource 作业 + 一个 syncBatch 作业（不可误删）
        _FakeAdminUI.state["jobs"] = {
            777: {"id": 777, "executorHandler": "syncSource", "triggerStatus": 1},
            888: {"id": 888, "executorHandler": "syncSource", "triggerStatus": 0},
            999: {"id": 999, "executorHandler": "syncSource", "triggerStatus": 1},  # 孤儿
            1000: {"id": 1000, "executorHandler": "syncBatch", "triggerStatus": 1},
        }
        self.patches = [
            patch.object(scheduler, "SyncSessionLocal", self.sessions),
            patch.object(scheduler, "get_admin_client", lambda: self.client),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def _calls(self):
        return _FakeAdminUI.state["calls"]

    def test_cleanup_removes_persisted_and_orphan_jobs(self):
        removed = scheduler.cleanup_source_jobs(self.client)
        self.assertEqual(removed, 3)
        self.assertIn(("remove", 777), self._calls())
        self.assertIn(("remove", 888), self._calls())
        self.assertIn(("remove", 999), self._calls())
        # syncBatch 作业不受影响
        self.assertNotIn(("remove", 1000), self._calls())
        with self.sessions() as db:
            for sid in self.ids:
                self.assertIsNone(db.get(SyncSource, sid).xxl_job_id)

    def test_cleanup_idempotent(self):
        scheduler.cleanup_source_jobs(self.client)
        calls_after_first = len([c for c in self._calls() if c[0] == "remove"])
        removed = scheduler.cleanup_source_jobs(self.client)
        self.assertEqual(removed, 0)
        calls_after_second = len([c for c in self._calls() if c[0] == "remove"])
        self.assertEqual(calls_after_first, calls_after_second)

    def test_cleanup_survives_admin_error(self):
        # 作业 777 删除失败 → 跳过继续（best effort，不抛异常）；
        # 孤儿扫描又会撞上仍在 admin 里的 777，再失败即中止本轮（下轮启动重试）
        def broken_remove(job_id):
            from app.services.sync.xxljob_admin import XxlJobAdminError
            if job_id == 777:
                raise XxlJobAdminError("boom")
            _FakeAdminUI.state["calls"].append(("remove", job_id))
            _FakeAdminUI.state["jobs"].pop(job_id, None)
        with patch.object(self.client, "remove_job", side_effect=broken_remove):
            removed = scheduler.cleanup_source_jobs(self.client)
        self.assertEqual(removed, 1)  # 仅 888 成功；999 孤儿因孤儿扫描撞上 777 失败而未扫到
        with self.sessions() as db:
            # 落库 ID 一律先清（无论 admin 删除成败），残留靠孤儿扫描兜底
            self.assertIsNone(db.get(SyncSource, self.ids[0]).xxl_job_id)
            self.assertIsNone(db.get(SyncSource, self.ids[1]).xxl_job_id)
        self.assertNotIn(("remove", 999), self._calls())


class BatchJobRegistryTest(unittest.TestCase):
    """全局批处理作业（syncBatch）幂等注册/启动。"""

    def setUp(self):
        _FakeAdminUI.state = {"groups": [{"id": 11, "appname": "kge-sync-executor", "title": "t"}],
                              "jobs": {}, "calls": [], "group_seq": 12, "job_seq": 201}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeAdminUI)
        port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.client = XxlJobAdminClient(f"http://127.0.0.1:{port}", "test-admin", "TestOnlyPass123!")
        self.client.ping()
        self.patches = [
            patch.object(scheduler, "get_admin_client", lambda: self.client),
            patch.object(scheduler, "get_settings", lambda: SimpleNamespace(
                xxl_job_executor_appname="kge-sync-executor", xxl_job_enabled=True,
                sync_batch_cron="*/30 * * * *")),
            patch.object(scheduler, "_batch_job_id", None),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def _calls(self):
        return _FakeAdminUI.state["calls"]

    def test_apply_batch_job_registers_and_starts(self):
        job_id = scheduler._apply_batch_job(self.client, 11)
        self.assertIsNotNone(job_id)
        job = _FakeAdminUI.state["jobs"][job_id]
        self.assertEqual(job["executorHandler"], "syncBatch")
        # 5 段 crontab 自动转 Quartz 6 段（秒位 0）
        self.assertEqual(job["scheduleConf"], "0 */30 * * * ?")
        self.assertEqual(job["scheduleType"], "CRON")
        self.assertEqual(job["triggerStatus"], 1)
        self.assertIn(("start", job_id), self._calls())

    def test_apply_batch_job_idempotent(self):
        first = scheduler._apply_batch_job(self.client, 11)
        adds = [c for c in self._calls() if c[0] == "add"]
        self.assertEqual(len(adds), 1)
        _FakeAdminUI.state["calls"].clear()
        second = scheduler._apply_batch_job(self.client, 11)
        self.assertEqual(first, second)
        self.assertEqual([c[0] for c in self._calls() if c[0] == "add"], [])
        self.assertIn(("update", first), self._calls())

    def test_apply_batch_job_recovers_missing(self):
        first = scheduler._apply_batch_job(self.client, 11)
        # admin 侧作业被手工删掉 → 按 handler 重新建
        _FakeAdminUI.state["jobs"].pop(first, None)
        _FakeAdminUI.state["calls"].clear()
        second = scheduler._apply_batch_job(self.client, 11)
        self.assertNotEqual(first, second)
        self.assertIn(("add", second), self._calls())

    def test_batch_tick_handler_routes_to_batch(self):
        from app.services.sync import batch
        with patch.object(batch, "run_sync_batch_tick", return_value=(200, "ok")) as tick:
            code, msg = scheduler._handle_sync_batch("", SimpleNamespace(log=lambda *a, **k: None))
        self.assertEqual((code, msg), (200, "ok"))
        tick.assert_called_once()


class TriggerChannelTest(unittest.TestCase):
    """触发通道：手动同步进程内直跑；降级批处理进程内 tick。"""

    def setUp(self):
        self.sql = create_engine("sqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
        SyncSource.__table__.create(self.sql)
        self.sessions = sessionmaker(bind=self.sql, expire_on_commit=False)
        with self.sessions() as db:
            src = SyncSource(name="源", workspace_id="w", root_node_id="r",
                             dataset_name="t", enabled=True)
            db.add(src)
            db.commit()
            self.source_id = src.id
        self.addCleanup(self.sql.dispose)

    def test_trigger_source_sync_runs_catalog_directly(self):
        from app.services.sync import catalog
        submitted = []
        with patch.object(scheduler, "_direct_executor",
                          SimpleNamespace(submit=lambda fn, *a, **k: submitted.append((fn, a, k)))), \
             patch.object(catalog, "run_catalog", return_value={"status": "success"}) as mock_catalog:
            result = scheduler.trigger_source_sync(self.source_id, "alice")
        self.assertEqual(result["via"], "direct")
        self.assertEqual(len(submitted), 1)
        fn, args, _kw = submitted[0]
        self.assertEqual(args, (self.source_id, "manual", "alice"))
        mock_catalog.assert_not_called()  # 仅提交，由线程执行

    def test_trigger_first_sync_same_channel(self):
        submitted = []
        with patch.object(scheduler, "_direct_executor",
                          SimpleNamespace(submit=lambda fn, *a, **k: submitted.append((fn, a, k)))):
            result = scheduler.trigger_first_sync(self.source_id, "bob")
        self.assertEqual(result["via"], "direct")
        self.assertEqual(submitted[0][1], (self.source_id, "manual", "bob"))

    def test_trigger_batch_once_disabled_falls_back_to_thread(self):
        from app.services.sync import batch
        submitted = []
        with patch.object(scheduler, "get_settings", lambda: SimpleNamespace(xxl_job_enabled=False)), \
             patch.object(scheduler, "_direct_executor",
                          SimpleNamespace(submit=lambda fn, *a, **k: submitted.append(fn))), \
             patch.object(batch, "run_sync_batch_tick") as tick:
            scheduler.trigger_batch_once()
        self.assertEqual(submitted, [tick])

    def test_trigger_batch_once_enabled_triggers_admin_job(self):
        with patch.object(scheduler, "get_settings", lambda: SimpleNamespace(xxl_job_enabled=True)), \
             patch.object(scheduler, "ensure_batch_job_running", return_value=42), \
             patch.object(scheduler, "_batch_job_id", 42), \
             patch.object(scheduler, "get_admin_client") as admin_cls:
            scheduler.trigger_batch_once()
            admin_cls.return_value.trigger_job.assert_called_once_with(42)


if __name__ == "__main__":
    unittest.main()
