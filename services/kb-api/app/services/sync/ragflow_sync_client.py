"""RAGFlow 知识库同步客户端（同步版，供 SyncEngine 使用）。

方法面对齐 DifyClient 的「非流水线」路径，使 SyncEngine 可用同一套调用：
    resolve_dataset / upload_file / update_file / delete_document / wait_indexing / close

RAGFlow 与 Dify 的关键差异：
- 上传文档后不会自动解析，必须显式 POST /datasets/{id}/chunks 触发；
- 无「按文件原位更新」接口：更新=删旧+传新+重新解析（解析失败旧文档已删，属已知取舍）；
- 解析状态在 document.run 字段（UNSTART/RUNNING/DONE/FAIL）+ progress。

错误统一抛 DifyError（复用引擎既有的异常分类与 404 容忍逻辑，避免改动 engine 的 except 分支）。
base_url 需含 /api/v1；凭据由 sync_settings.make_backend 从 DB 系统配置解析后注入。
"""
from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .dify_sync_client import DifyError

# RAGFlow 文档解析状态
_RUN_DONE = "DONE"
_RUN_FAIL = "FAIL"


class RagflowSyncClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 3600.0):
        # timeout 为「单个 HTTP 请求」上限（大文件上传/单次查询），默认 1h；
        # 「解析等待」总上限另由 settings.sync_indexing_timeout_seconds（默认 7 天）控制。
        self.base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self._client = httpx.Client(timeout=timeout)

    @staticmethod
    def _indexing_timeout() -> int:
        from kb_common.config import get_settings
        return int(get_settings().sync_indexing_timeout_seconds)

    def close(self) -> None:
        self._client.close()

    # ---------- 基础设施 ----------
    def _headers(self, json_ct: bool = True) -> dict[str, str]:
        if not self.base_url:
            raise DifyError("尚未配置 RAGFlow 服务地址，请在『RAGFlow 链接配置』中填写并保存")
        if not self._api_key:
            raise DifyError("尚未配置 RAGFlow API Key，请在『RAGFlow 链接配置』中填写并保存")
        h = {"Authorization": f"Bearer {self._api_key}"}
        if json_ct:
            h["Content-Type"] = "application/json"
        return h

    def _unwrap(self, resp: httpx.Response, action: str) -> Any:
        if resp.status_code == 404:
            raise DifyError(f"{action}：资源不存在（404）", status=404)
        if resp.status_code == 401:
            raise DifyError(f"{action}：API Key 无效或已过期（401）", status=401)
        if resp.status_code >= 400:
            raise DifyError(f"{action}：HTTP {resp.status_code} {resp.text[:200]}", status=resp.status_code)
        try:
            body = resp.json()
        except ValueError:
            raise DifyError(f"{action}：响应非 JSON（{resp.text[:200]}）", status=resp.status_code)
        if isinstance(body, dict) and body.get("code") not in (0, "0", None):
            raise DifyError(f"{action}：{body.get('message') or body}", code=body.get("code"))
        return body.get("data") if isinstance(body, dict) else body

    # ---------- 数据集 ----------
    def _list_datasets(self, params: dict) -> list[dict]:
        resp = self._client.get(f"{self.base_url}/datasets", params=params, headers=self._headers())
        data = self._unwrap(resp, "列出 RAGFlow 数据集")
        return data if isinstance(data, list) else []

    def resolve_dataset(self, dataset_id: str | None, name: str = "") -> dict:
        """ID 是同步目标身份；仅兼容尚未存 ID 的旧任务按名称解析。"""
        if dataset_id:
            items = self._list_datasets({"id": dataset_id, "page": 1, "page_size": 1})
            if items and items[0].get("id") == dataset_id:
                return items[0]
            raise DifyError(f"RAGFlow 知识库不存在: {dataset_id}")
        # 按名称解析
        matches = [d for d in self._list_datasets({"name": name.strip(), "page": 1, "page_size": 50})
                   if d.get("name") == name.strip()]
        if len(matches) > 1:
            raise DifyError("存在同名 RAGFlow 知识库，请编辑同步任务并按 ID 重新选择目标库")
        if not matches:
            raise DifyError(f"RAGFlow 知识库不存在: {name}")
        return matches[0]

    # ---------- 文档 ----------
    def _upload(self, dataset_id: str, file_path: Path, file_name: str | None) -> str:
        name = file_name or file_path.name
        content = file_path.read_bytes()
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        resp = self._client.post(
            f"{self.base_url}/datasets/{dataset_id}/documents",
            files={"file": (name, content, mime)},
            headers=self._headers(json_ct=False),
        )
        data = self._unwrap(resp, "上传 RAGFlow 文档")
        items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        if not items or not items[0].get("id"):
            raise DifyError("上传 RAGFlow 文档未返回文档 ID")
        doc_id = str(items[0]["id"])
        # RAGFlow 上传后不自动解析：显式触发 chunk 解析
        resp = self._client.post(
            f"{self.base_url}/datasets/{dataset_id}/chunks",
            json={"document_ids": [doc_id]}, headers=self._headers(),
        )
        self._unwrap(resp, "触发 RAGFlow 解析")
        return doc_id

    def upload_file(self, dataset_id: str, file_path: Path, file_name: str | None = None,
                    doc_language: str = "Chinese") -> dict:
        doc_id = self._upload(dataset_id, file_path, file_name)
        # batch 复用 doc_id：wait_indexing 据此轮询该文档解析进度
        return {"document": {"id": doc_id, "name": file_name or file_path.name,
                             "indexing_status": "indexing"}, "batch": doc_id}

    def update_file(self, dataset_id: str, document_id: str, file_path: Path,
                    file_name: str | None = None, doc_language: str = "Chinese") -> dict:
        """RAGFlow 无原位更新：先传新文档并解析，成功后删旧文档（失败保留旧文档）。"""
        new_id = self._upload(dataset_id, file_path, file_name)
        try:
            self.wait_indexing(dataset_id, new_id, timeout=self._indexing_timeout())
        except Exception:
            # 新文档解析失败：清理新文档，保留旧文档，抛出供引擎记录失败
            try:
                self.delete_document(dataset_id, new_id)
            except Exception:  # noqa: BLE001
                pass
            raise
        if document_id and document_id != new_id:
            try:
                self.delete_document(dataset_id, document_id)
            except DifyError as exc:
                if exc.status != 404:
                    raise
        return {"document": {"id": new_id, "name": file_name or file_path.name,
                             "indexing_status": "completed"}, "batch": new_id}

    def delete_document(self, dataset_id: str, document_id: str) -> dict:
        if not document_id:
            return {}
        resp = self._client.request(
            "DELETE", f"{self.base_url}/datasets/{dataset_id}/documents",
            json={"ids": [document_id]}, headers=self._headers(),
        )
        self._unwrap(resp, "删除 RAGFlow 文档")
        return {"ok": True}

    # ---------- 解析状态轮询 ----------
    def _get_document(self, dataset_id: str, document_id: str) -> dict | None:
        resp = self._client.get(
            f"{self.base_url}/datasets/{dataset_id}/documents",
            params={"page": 1, "page_size": 100, "keywords": ""}, headers=self._headers(),
        )
        data = self._unwrap(resp, "查询 RAGFlow 文档")
        docs = data.get("docs") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for d in docs or []:
            if str(d.get("id")) == str(document_id):
                return d
        return None

    def wait_indexing(self, dataset_id: str, batch: str, timeout: int | None = None,
                      on_progress: Callable[[str], None] | None = None) -> str:
        """轮询文档解析进度直到 DONE；FAIL 抛错；超时抛错。batch=RAGFlow document_id。

        timeout 缺省时取 settings.sync_indexing_timeout_seconds（默认 7 天），
        不在此处设分钟级上限，避免长解析（DeepDoc/OCR 大文件）被截断。
        """
        timeout = self._indexing_timeout() if timeout is None else int(timeout)
        start = time.monotonic()
        previous = ""
        while time.monotonic() - start < timeout:
            doc = self._get_document(dataset_id, batch)
            if doc is None:
                raise DifyError("RAGFlow 文档不存在，可能已被删除")
            run = (doc.get("run") or "").upper()
            progress = doc.get("progress")
            if run == _RUN_DONE:
                return "completed"
            if run == _RUN_FAIL:
                raise DifyError(f"RAGFlow 解析失败: {doc.get('progress_msg') or '未知原因'}")
            msg = f"{run or 'PARSING'} · 进度 {int((progress or 0) * 100)}%"
            if on_progress and msg != previous:
                on_progress(msg)
                previous = msg
            time.sleep(max(0, min(3, timeout - (time.monotonic() - start))))
        raise DifyError(f"等待 RAGFlow 解析超时（{timeout} 秒）")
