"""钉钉开放平台 API 客户端（同步版，迁移自 DingDingKonwledgePipeline）。

配置从 kb_common.config.get_settings() 读取，由平台「系统配置」页统一管理。
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

import httpx


API_BASE = "https://api.dingtalk.com"

# ---------- 目录树遍历缓存（内存 + 磁盘快照，10 分钟 TTL） ----------
# 预演/同步列表高频点按，钉钉全树遍历串行需数十秒至分钟级；
# 缓存以 root_node_id 为 key，强制刷新传 use_cache=False 绕过。
_WALK_CACHE_TTL = 600.0
_WALK_SNAPSHOT = Path("/tmp/kge_sync_walk_cache.json")
_walk_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_walk_cache_lock = threading.Lock()


def _walk_cache_load() -> None:
    """服务重启/热重载后从磁盘快照热身（过期条目不加载）。"""
    try:
        if _WALK_SNAPSHOT.exists():
            raw = json.loads(_WALK_SNAPSHOT.read_text("utf-8"))
            now = time.time()
            for key, entry in raw.items():
                if now - entry[0] < _WALK_CACHE_TTL:
                    _walk_cache[key] = (entry[0], entry[1])
    except Exception:  # noqa: BLE001 — 快照损坏不影响正常流程
        pass


_walk_cache_load()


def _walk_cache_get(key: str) -> list[dict[str, Any]] | None:
    with _walk_cache_lock:
        hit = _walk_cache.get(key)
    if hit and time.time() - hit[0] < _WALK_CACHE_TTL:
        return hit[1]
    return None


def _walk_cache_put(key: str, nodes: list[dict[str, Any]]) -> None:
    with _walk_cache_lock:
        _walk_cache[key] = (time.time(), nodes)
        payload = {k: [v[0], v[1]] for k, v in _walk_cache.items()}
    try:
        _WALK_SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    except Exception:  # noqa: BLE001 — 写盘失败仅失去重启热身
        pass


# ---------- 知识库列表缓存（进程内，60 秒 TTL） ----------
# 同步页每次挂载 + 运行中每 3 秒轮询都要读知识库列表，钉钉侧 500ms+；
# 列表极少变动，短 TTL 缓存即可把这条链路压到毫秒级。按 operator_id 分键。
_WS_CACHE_TTL = 60.0
_ws_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_ws_cache_lock = threading.Lock()


def _ws_cache_get_any(key: str) -> tuple[float, list[dict[str, Any]]] | None:
    """取缓存条目（含已过期），供「旧值先顶上 + 后台刷新」判断使用。"""
    with _ws_cache_lock:
        return _ws_cache.get(key)


def _ws_cache_put(key: str, items: list[dict[str, Any]]) -> None:
    with _ws_cache_lock:
        _ws_cache[key] = (time.time(), items)


# 后台刷新：单线程执行器 + 在飞标记（同一时刻只允许一个刷新任务）
_ws_refresh_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dt-ws-refresh")
_ws_refresh_lock = threading.Lock()
_ws_refresh_inflight = False


def _schedule_ws_refresh(app_key: str, app_secret: str, operator_id: str) -> None:
    """后台刷新知识库列表缓存。

    必须新建一个独立 client：调用方的实例在路由 finally 里就会被 close()。
    刷新失败只记日志、保留旧数据，下次访问再试。
    """
    global _ws_refresh_inflight
    with _ws_refresh_lock:
        if _ws_refresh_inflight:
            return
        _ws_refresh_inflight = True

    def _run() -> None:
        global _ws_refresh_inflight
        client = DingTalkClient(app_key, app_secret, operator_id)
        try:
            items = client._list_workspaces_remote()
            _ws_cache_put(operator_id or "", items)
        except Exception:  # noqa: BLE001 — 后台刷新失败不影响已缓存数据的展示
            pass
        finally:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
            with _ws_refresh_lock:
                _ws_refresh_inflight = False

    _ws_refresh_executor.submit(_run)


class DingTalkError(Exception):
    """钉钉接口调用失败"""

    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class DingTalkClient:
    def __init__(self, app_key: str, app_secret: str, operator_id: str, timeout: float = 30.0):
        self.app_key = app_key
        self.app_secret = app_secret
        self.operator_id = operator_id
        self._client = httpx.Client(timeout=timeout)
        self._token: str = ""
        self._token_expire_at: float = 0.0
        # 并发遍历（walk_tree）下多线程共享同一 client：
        # token 刷新加锁防重复获取；请求间隔节流防钉钉限流（403）。
        self._token_lock = threading.Lock()
        self._throttle_lock = threading.Lock()
        self._last_request_at = 0.0

    # ---------- 基础设施 ----------
    def _ensure_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expire_at - 300:
            return self._token
        with self._token_lock:
            # 双检：等锁期间可能已被其他线程刷新
            if self._token and time.time() < self._token_expire_at - 300:
                return self._token
            resp = self._client.post(f"{API_BASE}/v1.0/oauth2/accessToken",
                                     json={"appKey": self.app_key, "appSecret": self.app_secret})
            data = self._parse(resp, "获取 accessToken 失败")
            token = data.get("accessToken")
            expire_in = int(data.get("expireIn", 7200))
            if not token:
                raise DingTalkError(f"获取 accessToken 失败: {data}", status=resp.status_code)
            self._token = token
            self._token_expire_at = time.time() + expire_in
            return token

    @staticmethod
    def _parse(resp: httpx.Response, action: str) -> dict[str, Any]:
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            code = body.get("code", "")
            message = body.get("message", resp.text[:300])
            raise DingTalkError(f"{action}: [{code}] {message}", status=resp.status_code, code=str(code))
        if not resp.content:
            return {}
        return resp.json()

    def _request(self, method: str, path: str, params: dict | None = None,
                 json_body: dict | None = None) -> dict[str, Any]:
        token = self._ensure_token()
        headers = {"x-acs-dingtalk-access-token": token}
        resp = self._client.request(method, f"{API_BASE}{path}", params=params, json=json_body, headers=headers)
        return self._parse(resp, f"{method} {path}")

    def _throttle(self) -> None:
        """全局请求间隔 ≥0.4s（并发遍历下防钉钉限流，项目既有约定）。"""
        with self._throttle_lock:
            gap = self._last_request_at + 0.4 - time.monotonic()
            if gap > 0:
                time.sleep(gap)
            self._last_request_at = time.monotonic()

    def close(self) -> None:
        self._client.close()

    # ---------- 已跑通接口 ----------
    def test_connection(self) -> dict[str, Any]:
        self._ensure_token()
        # 测试连接必须真打一次钉钉，不能吃缓存
        workspaces = self.list_workspaces(use_cache=False)
        return {"ok": True, "workspace_count": len(workspaces), "workspaces": workspaces}

    def list_workspaces(self, use_cache: bool = True) -> list[dict[str, Any]]:
        """操作人可见的知识库列表（60s 缓存 + 过期后台刷新）。

        「钉钉知识同步」页每次挂载都会调、有任务运行时还每 3 秒轮询一次。
        缓存过期时**先返回旧数据、再后台刷新**：钉钉限流/抖动时单次调用可达 50s，
        不能让它挡在页面渲染前面。完全没有缓存时才同步等一次。
        需要强制取最新时传 use_cache=False。
        """
        key = self.operator_id or ""
        if use_cache:
            entry = _ws_cache_get_any(key)
            if entry is not None:
                if time.time() - entry[0] >= _WS_CACHE_TTL:
                    _schedule_ws_refresh(self.app_key, self.app_secret, self.operator_id)
                return entry[1]
        items = self._list_workspaces_remote()
        if use_cache:
            _ws_cache_put(key, items)
        return items

    def _list_workspaces_remote(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            params = {"operatorId": self.operator_id, "maxResults": 30}
            if next_token:
                params["nextToken"] = next_token
            data = self._request("GET", "/v2.0/wiki/workspaces", params=params)
            items.extend(data.get("workspaces", []))
            next_token = data.get("nextToken")
            if not next_token:
                break
        return items

    def list_nodes(self, parent_node_id: str, max_results: int = 50) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            params = {
                "parentNodeId": parent_node_id,
                "operatorId": self.operator_id,
                "maxResults": max_results,
            }
            if next_token:
                params["nextToken"] = next_token
            data = self._request("GET", "/v2.0/wiki/nodes", params=params)
            items.extend(data.get("nodes", []))
            next_token = data.get("nextToken")
            if not next_token:
                break
        return items

    def get_node(self, node_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v2.0/wiki/nodes/{node_id}",
                             params={"operatorId": self.operator_id})

    def walk_tree(self, root_node_id: str, max_depth: int = 10,
                  max_results: int = 50, use_cache: bool = True) -> list[dict[str, Any]]:
        """遍历目录树，为每个文件节点补充 relative_dir。目录节点不返回。

        - use_cache=True：优先读 10 分钟 TTL 缓存（内存 + /tmp 快照，重启可热身）；
          use_cache=False：强制重新遍历并刷新缓存（预演「刷新」按钮 / 真实同步走此路径）。
        - 兄弟目录并发遍历（并发 ≤3 + 全局 0.4s 节流，防钉钉 403 限流）：
          协调者模式——仅主线程阻塞等待 future，worker 只列目录互不等待，无死锁。
        - 深度超限在发现子目录时抛出，与旧递归实现语义一致；结果按相对路径排序。

        收集所有非目录节点（在线文档 adoc/在线表格 axls/AI 表格 able/脑图 mind/
        普通上传文件等），由同步引擎按 extension 分流下载或导出。
        """
        if use_cache:
            cached = _walk_cache_get(root_node_id)
            if cached is not None:
                return cached

        from .export_service import safe_name

        def list_dir(parent_node_id: str, rel_dir: str) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
            """列单个目录：返回 (文件节点, [(子目录 node_id, 子目录相对路径), ...])。"""
            self._throttle()
            nodes = self.list_nodes(parent_node_id, max_results=max_results)
            files: list[dict[str, Any]] = []
            dirs: list[tuple[str, str]] = []
            for node in nodes:
                category = node.get("category", "")
                name = node.get("name", node.get("nodeId", ""))
                has_children = bool(node.get("hasChildren", False))
                is_folder = (node.get("type") == "FOLDER" or category == "FOLDER"
                             or (has_children and category not in ("DOCUMENT", "ALIDOC")))
                if not is_folder:
                    item = dict(node)
                    item["relative_dir"] = rel_dir
                    item["parent_node_id"] = parent_node_id
                    files.append(item)
                if is_folder or has_children:
                    child_dir = f"{rel_dir}/{safe_name(name)}" if rel_dir else safe_name(name)
                    dirs.append((node.get("nodeId", ""), child_dir))
            return files, dirs

        result: list[dict[str, Any]] = []
        visited: set[str] = {root_node_id}
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures: dict[Future, int] = {ex.submit(list_dir, root_node_id, ""): 0}
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for fut in done:
                    depth = futures.pop(fut)
                    files, dirs = fut.result()  # worker 异常在此向上抛
                    result.extend(files)
                    for child_pid, child_dir in dirs:
                        if depth + 1 > max_depth:
                            raise DingTalkError(f"目录超过最大遍历深度 {max_depth}，请提高 sync_max_depth 后重试")
                        if child_pid in visited:
                            continue
                        visited.add(child_pid)
                        futures[ex.submit(list_dir, child_pid, child_dir)] = depth + 1
        result.sort(key=lambda n: (n.get("relative_dir", ""), n.get("name", "")))
        _walk_cache_put(root_node_id, result)
        return result

    def build_tree(self, parent_node_id: str, max_depth: int = 5,
                   max_results: int = 50) -> list[dict[str, Any]]:
        """构建目录树（含目录节点）。"""
        def rec(pid: str, depth: int) -> list[dict[str, Any]]:
            if depth > max_depth:
                return []
            nodes = self.list_nodes(pid, max_results=max_results)
            result: list[dict[str, Any]] = []
            for node in nodes:
                node_id = node.get("nodeId", "")
                category = node.get("category", "")
                has_children = bool(node.get("hasChildren", False))
                item = {
                    "nodeId": node_id,
                    "name": node.get("name", node_id),
                    "category": category,
                    "hasChildren": has_children,
                    "children": [],
                }
                if category not in ("DOCUMENT", "ALIDOC") and has_children:
                    item["children"] = rec(node_id, depth + 1)
                result.append(item)
            return result

        return rec(parent_node_id, 0)

    # ---------- DOCUMENT 下载 ----------
    def download_document(self, node_id: str) -> tuple[bytes, str]:
        """返回 (内容 bytes, 文件名)。"""
        d1 = self._request("GET", f"/v2.0/doc/dentries/{node_id}/queryDentryId",
                           params={"operatorId": self.operator_id})
        space_id = d1.get("spaceId")
        dentry_id = d1.get("dentryId")
        if not space_id or not dentry_id:
            raise DingTalkError(f"queryDentryId 返回缺少 spaceId/dentryId: {d1}")

        d2 = self._request("POST",
                           f"/v1.0/storage/spaces/{space_id}/dentries/{dentry_id}/downloadInfos/query",
                           params={"unionId": self.operator_id},
                           json_body={"option": {"preferIntranet": False}})
        header_info = d2.get("headerSignatureInfo", {})
        urls = header_info.get("resourceUrls", [])
        if not urls:
            raise DingTalkError(f"downloadInfos/query 未返回下载地址: {d2}")
        dl_headers = dict(header_info.get("headers", {}))
        resp = self._client.get(urls[0], headers=dl_headers, timeout=120.0)
        from kb_common.clients.source_integrity import downloaded_file
        try:
            return downloaded_file(resp, urls[0])
        except (httpx.HTTPError, ValueError) as exc:
            raise DingTalkError(f"原文件下载失败：{exc}") from exc
