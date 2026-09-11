"""Dify 1.x 知识库 API 客户端（Dataset API）"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

import httpx


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

    def find_or_create_dataset(self, name: str, permission: str = "all_team_members") -> dict:
        for page in range(1, 6):
            data = self.list_datasets(page=page, limit=50, keyword=name)
            items = data.get("data", [])
            for item in items:
                if item.get("name") == name:
                    return item
            if not data.get("has_more", False):
                break
        created = self.create_dataset(name, description="由钉钉知识库同步服务自动创建", permission=permission)
        return created

    # ---------- 文档 ----------
    def upload_file(self, dataset_id: str, file_path: Path, file_name: str | None = None,
                    doc_language: str = "Chinese") -> dict:
        name = file_name or file_path.name
        mime, _ = mimetypes.guess_type(str(file_path))
        payload = {
            "indexing_technique": "high_quality",
            "process_rule": {"mode": "automatic"},
            "doc_form": "text_model",
            "doc_language": doc_language,
        }
        with file_path.open("rb") as fh:
            content = fh.read()
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
        payload = {
            "indexing_technique": "high_quality",
            "process_rule": {"mode": "automatic"},
            "doc_form": "text_model",
            "doc_language": doc_language,
        }
        with file_path.open("rb") as fh:
            content = fh.read()
        resp = self._client.post(
            f"{self.base_url}/datasets/{dataset_id}/documents/{document_id}/update-by-file",
            headers=self._headers,
            files={"file": (name, content, mime or "application/octet-stream")},
            data={"data": json.dumps(payload, ensure_ascii=False)},
        )
        return self._parse(resp, "update file")

    def delete_document(self, dataset_id: str, document_id: str) -> dict:
        return self._delete(f"/datasets/{dataset_id}/documents/{document_id}")

    def indexing_status(self, dataset_id: str, batch: str) -> dict:
        return self._get(f"/datasets/{dataset_id}/documents/{batch}/indexing-status")

    def wait_indexing(self, dataset_id: str, batch: str, timeout: int = 600) -> str:
        import time
        start = time.time()
        while time.time() - start < timeout:
            data = self.indexing_status(dataset_id, batch)
            items = data.get("data", [])
            statuses = {item.get("indexing_status", "") for item in items}
            if not statuses:
                return "unknown"
            if statuses == {"completed"}:
                return "completed"
            if "error" in statuses:
                return "error"
            time.sleep(3)
        return "timeout"
