"""Dify 1.x 知识库 API 客户端（Dataset API，同步版，迁移自 DingDingKonwledgePipeline）。

base_url/api_key 从平台配置读取（dify_base_url / dify_api_key）。
注意 dify_base_url 需含 /v1 后缀（见 config.py 默认值）。
"""
from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from kb_common.config import get_settings
from kb_common.clients.document_upload import prepare_document


class DifyError(Exception):
    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class DifyClient:
    def __init__(self, base_url: str, dataset_api_key: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {dataset_api_key}"}
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _parse(resp: httpx.Response, action: str) -> Any:
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            message = body.get("message") or body.get("code") or resp.text[:300]
            raise DifyError(f"{action}: {message}", status=resp.status_code,
                            code=str(body.get("code", "")))
        if not resp.content:
            return {}
        return resp.json()

    def _get(self, path: str, params: dict | None = None) -> Any:
        resp = self._client.get(f"{self.base_url}{path}", params=params, headers=self._headers)
        return self._parse(resp, f"GET {path}")

    def _post(self, path: str, json_body: dict | None = None) -> Any:
        resp = self._client.post(f"{self.base_url}{path}", json=json_body, headers=self._headers)
        return self._parse(resp, f"POST {path}")

    def _patch(self, path: str, json_body: dict | None = None) -> Any:
        resp = self._client.patch(f"{self.base_url}{path}", json=json_body, headers=self._headers)
        return self._parse(resp, f"PATCH {path}")

    def _delete(self, path: str) -> Any:
        resp = self._client.delete(f"{self.base_url}{path}", headers=self._headers)
        return self._parse(resp, f"DELETE {path}")

    # ---------- 数据集 ----------
    def list_datasets(self, page: int = 1, limit: int = 30, keyword: str = "") -> dict:
        return self._get("/datasets", params={"page": page, "limit": limit, "keyword": keyword})

    def get_dataset(self, dataset_id: str) -> dict:
        return self._get(f"/datasets/{dataset_id}")

    def create_dataset(self, name: str, description: str = "",
                       permission: str = "all_team_members",
                       indexing_technique: str = "high_quality") -> dict:
        return self._post("/datasets", json_body={
            "name": name,
            "description": description,
            "permission": permission,
            "indexing_technique": indexing_technique,
        })

    def update_dataset(self, dataset_id: str, fields: dict) -> dict:
        return self._patch(f"/datasets/{dataset_id}", json_body=fields)

    def delete_dataset(self, dataset_id: str) -> dict:
        return self._delete(f"/datasets/{dataset_id}")

    def find_dataset_by_name(self, name: str) -> dict | None:
        """查找 Dify 中已有的数据集；同步源不会隐式创建数据集。"""
        for page in range(1, 6):
            data = self.list_datasets(page=page, limit=50, keyword=name)
            items = data.get("data", [])
            for item in items:
                if item.get("name") == name:
                    return item
            if not data.get("has_more", False):
                break
        return None

    # ---------- 文档 ----------
    def _file_payload(self, dataset_id: str, doc_language: str) -> dict:
        dataset = self.get_dataset(dataset_id)
        payload = {
            "indexing_technique": dataset.get("indexing_technique") or "high_quality",
            "doc_form": dataset.get("doc_form") or dataset.get("chunk_structure") or "text_model",
            "doc_language": doc_language,
        }
        # 已有知识库复用其分段规则，尤其不能将父子分段覆盖为普通自动分段。
        if not dataset.get("document_count") and payload["doc_form"] == "text_model":
            payload["process_rule"] = {"mode": "automatic"}
        return payload

    def upload_file(self, dataset_id: str, file_path: Path, file_name: str | None = None,
                    doc_language: str = "Chinese") -> dict:
        name = file_name or file_path.name
        mime, _ = mimetypes.guess_type(str(file_path))
        payload = self._file_payload(dataset_id, doc_language)
        with file_path.open("rb") as fh:
            content = fh.read()
        try:
            name, content = prepare_document(name, content, max_source_bytes=100 * 1024 * 1024)
        except ValueError as exc:
            raise DifyError(str(exc)) from exc
        mime, _ = mimetypes.guess_type(name)
        resp = self._client.post(
            f"{self.base_url}/datasets/{dataset_id}/document/create-by-file",
            headers=self._headers,
            files={"file": (name, content, mime or "application/octet-stream")},
            data={"data": json.dumps(payload, ensure_ascii=False)},
        )
        return self._parse(resp, "upload file")

    def update_file(self, dataset_id: str, document_id: str, file_path: Path,
                    file_name: str | None = None, doc_language: str = "Chinese") -> dict:
        name = file_name or file_path.name
        mime, _ = mimetypes.guess_type(str(file_path))
        payload = self._file_payload(dataset_id, doc_language)
        with file_path.open("rb") as fh:
            content = fh.read()
        try:
            name, content = prepare_document(name, content, max_source_bytes=100 * 1024 * 1024)
        except ValueError as exc:
            raise DifyError(str(exc)) from exc
        mime, _ = mimetypes.guess_type(name)
        resp = self._client.post(
            f"{self.base_url}/datasets/{dataset_id}/documents/{document_id}/update-by-file",
            headers=self._headers,
            files={"file": (name, content, mime or "application/octet-stream")},
            data={"data": json.dumps(payload, ensure_ascii=False)},
        )
        return self._parse(resp, "update file")

    def delete_document(self, dataset_id: str, document_id: str) -> dict:
        return self._delete(f"/datasets/{dataset_id}/documents/{document_id}")

    def document_count(self, dataset_id: str) -> int:
        """返回 Dify 数据集实际文档总数，而不是本地同步映射数。"""
        data = self._get(f"/datasets/{dataset_id}/documents", params={"page": 1, "limit": 1})
        return int(data.get("total", len(data.get("data", []))))

    def indexing_status(self, dataset_id: str, batch: str, timeout: float = 60) -> dict:
        response = self._client.get(
            f"{self.base_url}/datasets/{dataset_id}/documents/{batch}/indexing-status",
            headers=self._headers, timeout=timeout,
        )
        return self._parse(response, "查询 Dify 索引")

    def wait_indexing(self, dataset_id: str, batch: str, timeout: int = 600,
                      on_progress: Callable[[str], None] | None = None) -> str:
        start = time.monotonic()
        previous = ""
        while time.monotonic() - start < timeout:
            remaining = timeout - (time.monotonic() - start)
            data = self.indexing_status(dataset_id, batch, timeout=max(0.1, min(60, remaining)))
            items = data.get("data", [])
            statuses = {item.get("indexing_status", "") for item in items}
            if not statuses:
                raise DifyError("Dify 未返回索引状态")
            if statuses == {"completed"}:
                return "completed"
            if "error" in statuses:
                detail = next((item.get("error") for item in items if item.get("error")), "未知原因")
                raise DifyError(f"Dify 索引失败: {detail}")
            if statuses & {"paused", "stopped"} or any(item.get("paused_at") or item.get("stopped_at") for item in items):
                raise DifyError("Dify 索引已暂停或停止，请在 Dify 中恢复后重试")
            done = sum(item.get("completed_segments") or 0 for item in items)
            total = sum(item.get("total_segments") or 0 for item in items)
            progress = f"{', '.join(sorted(statuses))} · 分段 {done}/{total}"
            if on_progress and progress != previous:
                on_progress(progress)
                previous = progress
            time.sleep(max(0, min(3, timeout - (time.monotonic() - start))))
        raise DifyError(f"等待 Dify 索引超时（{timeout} 秒）")


def build_client_from_settings() -> DifyClient:
    """从平台配置构造一个 Dify 客户端。"""
    s = get_settings()
    return DifyClient(s.dify_base_url, s.dify_api_key)
