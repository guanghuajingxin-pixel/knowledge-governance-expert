"""钉钉开放平台 API 客户端（同步版，迁移自 DingDingKonwledgePipeline）。

配置从 kb_common.config.get_settings() 读取，由平台「系统配置」页统一管理。
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from kb_common.config import get_settings

API_BASE = "https://api.dingtalk.com"


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

    # ---------- 基础设施 ----------
    def _ensure_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expire_at - 300:
            return self._token
        resp = self._client.post(f"{API_BASE}/v1.0/oauth2/accessToken",
                                 json={"appKey": self.app_key, "appSecret": self.app_secret})
        data = self._parse(resp, "获取 accessToken 失败")
        token = data.get("accessToken")
        expire_in = int(data.get("expireIn", 7200))
        if not token:
            raise DingTalkError(f"获取 accessToken 失败: {data}", status=resp.status_code)
        self._token = token
        self._token_expire_at = now + expire_in
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

    def close(self) -> None:
        self._client.close()

    # ---------- 已跑通接口 ----------
    def test_connection(self) -> dict[str, Any]:
        self._ensure_token()
        workspaces = self.list_workspaces()
        return {"ok": True, "workspace_count": len(workspaces), "workspaces": workspaces}

    def list_workspaces(self) -> list[dict[str, Any]]:
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
                  max_results: int = 50) -> list[dict[str, Any]]:
        """递归遍历目录，为每个文件节点补充 relative_dir。目录节点不返回。

        收集所有非目录节点（在线文档 adoc/在线表格 axls/AI 表格 able/脑图 mind/
        普通上传文件等），由同步引擎按 extension 分流下载或导出。
        """
        result: list[dict[str, Any]] = []

        def walk(parent_node_id: str, rel_dir: str, depth: int) -> None:
            if depth > max_depth:
                return
            nodes = self.list_nodes(parent_node_id, max_results=max_results)
            for node in nodes:
                category = node.get("category", "")
                name = node.get("name", node.get("nodeId", ""))
                has_children = bool(node.get("hasChildren", False))
                is_folder = node.get("type") == "FOLDER" or category == "FOLDER"
                if not is_folder:
                    item = dict(node)
                    item["relative_dir"] = rel_dir
                    item["parent_node_id"] = parent_node_id
                    result.append(item)
                elif has_children:
                    child_dir = f"{rel_dir}/{name}" if rel_dir else name
                    walk(node.get("nodeId", ""), child_dir, depth + 1)

        walk(root_node_id, "", 0)
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
        if resp.status_code >= 400:
            raise DingTalkError(f"OSS 下载失败 HTTP {resp.status_code}: {resp.text[:300]}", status=resp.status_code)
        filename = ""
        try:
            from urllib.parse import urlparse
            path = urlparse(urls[0]).path
            filename = path.rsplit("/", 1)[-1]
        except Exception:
            filename = ""
        return resp.content, filename


def build_client_from_settings() -> DingTalkClient:
    """从平台配置构造一个钉钉同步客户端。"""
    s = get_settings()
    return DingTalkClient(s.dingtalk_app_key, s.dingtalk_app_secret,
                         s.dingtalk_operator_union_id)
