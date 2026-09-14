"""XXL-Job Python 执行器（内嵌 kb-api 进程，单服务一体化部署）。

实现 XXL-Job 2.4 执行器协议：
- 主动注册：每 30s POST {admin}/api/registry 上报 appname + http://ip:port，退出时 /api/registryRemove；
- 被动接收：admin 回调本服务 /beat /idleBeat /run /kill /log（JSON，accessToken 头校验）；
- 串行执行：同一 jobId 单线程队列（SERIAL_EXECUTION 语义），/run 立即 ack，任务在线程内跑；
- 执行回调：任务结束后 POST {admin}/api/callback 上报 handleCode/handleMsg；
- 日志：按 {log_path}/{yyyy-MM-dd}/{logId}.log 落盘，admin 控制台经 /log 拉取展示。

限制：/kill 只清空该作业排队任务并标记停止，正在执行的同步由引擎自身硬超时兜底，
不做线程强杀（同步子进程不可安全强杀）。
"""
from __future__ import annotations

import json
import logging
import queue
import socket
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

OK = {"code": 200, "msg": None, "content": None}


def _fail(msg: str, code: int = 500) -> dict:
    return {"code": code, "msg": msg, "content": None}


def detect_ip(admin_url: str) -> str:
    """以「到 admin 的出口 IP」作为注册 IP：容器/宿主机场景都能被 admin 路由到。"""
    parsed = urlparse(admin_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((host, port))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class JobLogWriter:
    """单个任务日志文件写入器：{log_path}/{yyyy-MM-dd}/{logId}.log。"""

    def __init__(self, log_path: Path, log_id: int, log_datetime_ms: int):
        self.log_id = log_id
        stamp = datetime.fromtimestamp(log_datetime_ms / 1000) if log_datetime_ms else datetime.now()
        self.file = log_path / stamp.strftime("%Y-%m-%d") / f"{log_id}.log"
        self.file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, line: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.file.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} [kge-executor] {line}\n")

    def read_from(self, from_line_num: int) -> dict:
        if not self.file.exists():
            return {"fromLineNum": from_line_num, "toLineNum": from_line_num - 1,
                    "logContent": "", "isEnd": True}
        lines = self.file.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(from_line_num, 1)
        chunk = lines[start - 1:]
        return {"fromLineNum": start, "toLineNum": start + len(chunk) - 1,
                "logContent": "\n".join(chunk), "isEnd": True}


class _JobWorker:
    """单 jobId 的串行执行线程。"""

    def __init__(self, job_id: int, executor: "XxlJobExecutor"):
        self.job_id = job_id
        self.executor = executor
        self.tasks: queue.Queue = queue.Queue()
        self.running = False
        self.thread = threading.Thread(target=self._loop, name=f"xxljob-job-{job_id}", daemon=True)

    def submit(self, params: dict) -> None:
        self.tasks.put(params)
        if not self.running:
            self.running = True
            self.thread.start()

    def busy(self) -> bool:
        return self.running and (not self.tasks.empty() or self._executing)

    _executing = False

    def _loop(self) -> None:
        while True:
            try:
                params = self.tasks.get_nowait()
            except queue.Empty:
                self.running = False
                return
            self._executing = True
            try:
                self.executor._execute(params)
            except Exception:  # noqa: BLE001
                logger.exception("xxl-job 任务执行异常 jobId=%s", self.job_id)
            finally:
                self._executing = False
                self.tasks.task_done()


class XxlJobExecutor:
    def __init__(self, admin_url: str, access_token: str, appname: str,
                 ip: str, port: int, log_path: Path):
        self.admin_url = admin_url.rstrip("/")
        self.access_token = access_token or ""
        self.appname = appname
        self.ip = ip
        self.port = port
        self.log_path = log_path
        self.handlers: dict = {}
        self._workers: dict[int, _JobWorker] = {}
        self._workers_lock = threading.Lock()
        self._callbacks: queue.Queue = queue.Queue()
        self._stopped = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._threads: list[threading.Thread] = []
        self._log_writers: dict[int, JobLogWriter] = {}

    # ---------- 生命周期 ----------
    def start(self, handlers: dict) -> None:
        self.handlers = handlers
        self.log_path.mkdir(parents=True, exist_ok=True)
        executor = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # 静默 access log
                pass

            def _reply(self, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                if executor.access_token and \
                        self.headers.get("XXL-JOB-ACCESS-TOKEN") != executor.access_token:
                    self._reply(_fail("access token mismatch"))
                    return
                try:
                    payload = json.loads(raw or b"{}")
                except ValueError:
                    self._reply(_fail("invalid json"))
                    return
                path = self.path.rstrip("/")
                if path == "/beat":
                    self._reply(OK)
                elif path == "/idleBeat":
                    worker = executor._workers.get(int(payload.get("jobId", -1)))
                    self._reply(_fail("job thread is running") if worker and worker.busy() else OK)
                elif path == "/run":
                    self._reply(executor._on_run(payload))
                elif path == "/kill":
                    executor._on_kill(int(payload.get("jobId", -1)))
                    self._reply(OK)
                elif path == "/log":
                    self._reply(executor._on_log(payload))
                else:
                    self._reply(_fail(f"unknown path {path}"))

        # 监听 0.0.0.0：注册上报用探测 IP，监听与注册解绑，避免出口 IP 非本机接口时绑定失败。
        self._server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        server_thread = threading.Thread(target=self._server.serve_forever,
                                         name="xxljob-executor-server", daemon=True)
        server_thread.start()
        self._threads.append(server_thread)
        for target, name in ((self._registry_loop, "xxljob-registry"),
                             (self._callback_loop, "xxljob-callback")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)
        logger.info("XXL-Job 执行器已启动: http://%s:%s appname=%s", self.ip, self.port, self.appname)

    def stop(self) -> None:
        self._stopped.set()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        try:
            requests.post(f"{self.admin_url}/api/registryRemove",
                          json={"registryGroup": "EXECUTOR", "registryKey": self.appname,
                                "registryValue": self.registry_value},
                          headers=self._headers, timeout=5)
        except requests.RequestException:
            pass

    @property
    def registry_value(self) -> str:
        return f"http://{self.ip}:{self.port}"

    @property
    def _headers(self) -> dict:
        return {"XXL-JOB-ACCESS-TOKEN": self.access_token} if self.access_token else {}

    # ---------- 注册 / 回调 ----------
    def _registry_loop(self) -> None:
        # 启动立即上报一次，之后每 30s 心跳；admin 靠注册表发现执行器地址。
        while not self._stopped.is_set():
            try:
                requests.post(f"{self.admin_url}/api/registry",
                              json={"registryGroup": "EXECUTOR", "registryKey": self.appname,
                                    "registryValue": self.registry_value},
                              headers=self._headers, timeout=5)
            except requests.RequestException as exc:
                logger.warning("XXL-Job 注册上报失败: %s", exc)
            self._stopped.wait(30)

    def _callback_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                item = self._callbacks.get(timeout=1)
            except queue.Empty:
                continue
            for attempt in range(3):
                try:
                    resp = requests.post(f"{self.admin_url}/api/callback", json=[item],
                                         headers=self._headers, timeout=5)
                    if resp.status_code == 200 and resp.json().get("code") == 200:
                        break
                except (requests.RequestException, ValueError):
                    time.sleep(2 * (attempt + 1))
            self._callbacks.task_done()

    # ---------- 任务接收与执行 ----------
    def _on_run(self, payload: dict) -> dict:
        if (payload.get("glueType") or "BEAN") != "BEAN":
            return _fail("仅支持 BEAN 模式作业")
        handler_name = payload.get("executorHandler") or ""
        if handler_name not in self.handlers:
            return _fail(f"未注册的 executorHandler: {handler_name}")
        job_id = int(payload.get("jobId", 0))
        with self._workers_lock:
            worker = self._workers.get(job_id)
            if worker is None or not worker.running:
                worker = _JobWorker(job_id, self)
                self._workers[job_id] = worker
        worker.submit(payload)
        return OK

    def _on_kill(self, job_id: int) -> None:
        with self._workers_lock:
            worker = self._workers.get(job_id)
        if worker is None:
            return
        # 清空排队任务；正在执行的任务由同步引擎硬超时兜底（不做强杀）。
        drained = 0
        while True:
            try:
                params = worker.tasks.get_nowait()
                drained += 1
                self._push_callback(params, 500, "任务被调度中心终止（排队中取消）")
            except queue.Empty:
                break
        if drained:
            logger.info("xxl-job jobId=%s 已取消 %s 个排队任务", job_id, drained)

    def _on_log(self, payload: dict) -> dict:
        log_id = int(payload.get("logId", 0))
        writer = self._log_writers.get(log_id)
        if writer is None:
            stamp_ms = int(payload.get("logDateTim") or 0)
            writer = JobLogWriter(self.log_path, log_id, stamp_ms)
        content = writer.read_from(int(payload.get("fromLineNum") or 1))
        return {"code": 200, "msg": None, "content": content}

    def _execute(self, params: dict) -> None:
        log_id = int(params.get("logId", 0))
        writer = JobLogWriter(self.log_path, log_id, int(params.get("logDateTim") or 0))
        self._log_writers[log_id] = writer
        handler_name = params.get("executorHandler") or ""
        handler = self.handlers.get(handler_name)
        writer.log(f"任务开始: handler={handler_name} param={params.get('executorParams')!r}")
        code, msg = 500, "handler 不存在"
        if handler is not None:
            try:
                code, msg = handler(params.get("executorParams") or "", writer)
            except Exception as exc:  # noqa: BLE001
                code, msg = 500, f"执行异常: {exc}"
        writer.log(f"任务结束: code={code} msg={msg}")
        self._push_callback(params, code, msg)

    def _push_callback(self, params: dict, code: int, msg: str) -> None:
        self._callbacks.put({"logId": int(params.get("logId", 0)),
                             "logDateTim": int(params.get("logDateTim") or 0),
                             "handleCode": code, "handleMsg": (msg or "")[:500]})
