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

from kb_common.clients.document_upload import prepare_document
from kb_common.clients.dify_document import file_payload, pipeline_payload, pipeline_result


class DifyError(Exception):
    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class DifyClient:
    def __init__(self, base_url: str, dataset_api_key: str, timeout: float = 600.0):
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
        matches = []
        page = 1
        while True:
            data = self.list_datasets(page=page, limit=50, keyword=name)
            items = data.get("data", [])
            for item in items:
                if item.get("name") == name:
                    matches.append(item)
            if not data.get("has_more", False):
                break
            page += 1
        if len(matches) > 1:
            raise DifyError("存在同名 Dify 知识库，请编辑同步任务并按 ID 重新选择目标库")
        return matches[0] if matches else None

    def resolve_dataset(self, dataset_id: str | None, name: str = "") -> dict:
        """ID 是同步目标的身份；仅兼容尚未保存 ID 的旧任务按名称解析。"""
        if not dataset_id:
            match = self.find_dataset_by_name(name.strip())
            if not match:
                raise DifyError(f"Dify 知识库不存在: {name}")
            dataset_id = match.get("id")
        if not dataset_id:
            raise DifyError("Dify 未返回知识库 ID")
        dataset = self.get_dataset(dataset_id)
        if dataset.get("id") != dataset_id:
            raise DifyError("Dify 知识库详情返回的 ID 与目标不一致")
        return dataset

    # ---------- 文档 ----------
    def _file_payload(self, dataset_id: str, doc_language: str) -> dict:
        return file_payload(self.get_dataset(dataset_id), doc_language)

    def upload_file(self, dataset_id: str, file_path: Path, file_name: str | None = None,
                    doc_language: str = "Chinese") -> dict:
        name = file_name or file_path.name
        payload = self._file_payload(dataset_id, doc_language)
        with file_path.open("rb") as fh:
            content = fh.read()
        try:
            name, content = prepare_document(name, content)
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
        payload = self._file_payload(dataset_id, doc_language)
        with file_path.open("rb") as fh:
            content = fh.read()
        try:
            name, content = prepare_document(name, content)
        except ValueError as exc:
            raise DifyError(str(exc)) from exc
        mime, _ = mimetypes.guess_type(name)
        resp = self._client.post(
            f"{self.base_url}/datasets/{dataset_id}/documents/{document_id}/update-by-file",
            headers=self._headers,
            files={"file": (name, content, mime or "application/octet-stream")},
            data={"data": json.dumps(payload, ensure_ascii=False)},
        )
        try:
            return self._parse(resp, "update file")
        except DifyError as exc:
            if exc.status == 404:
                return self.upload_file(dataset_id, file_path, file_name, doc_language)
            if "Document is not available" not in str(exc):
                raise
            document = self._get(f"/datasets/{dataset_id}/documents/{document_id}")
            if document.get("indexing_status") not in ("error", "completed", "paused", "stopped"):
                raise DifyError("旧文档仍在索引，请等待处理完成后重试") from exc
            return self._replace_document(
                dataset_id, document_id,
                lambda: self.upload_file(dataset_id, file_path, file_name, doc_language),
            )

    def delete_document(self, dataset_id: str, document_id: str) -> dict:
        return self._delete(f"/datasets/{dataset_id}/documents/{document_id}")

    # ---------- 知识流水线（runtime_mode=rag_pipeline 的数据集） ----------
    def list_datasource_nodes(self, dataset_id: str) -> list[dict]:
        """列出已发布流水线的数据源节点（用于定位 local_file 起始节点）。"""
        data = self._get(f"/datasets/{dataset_id}/pipeline/datasource-plugins",
                         params={"is_published": "true"})
        return data if isinstance(data, list) else (data.get("data") or [])

    def local_file_node_id(self, dataset_id: str) -> str:
        """取第一个本地文件类型数据源节点的 node_id；找不到说明流水线不支持文件同步。"""
        for node in self.list_datasource_nodes(dataset_id):
            if node.get("datasource_type") == "local_file" and node.get("node_id"):
                return str(node["node_id"])
        raise DifyError("知识流水线未配置本地文件数据源节点，无法通过 API 同步文档", code="no_local_file_node")

    def upload_pipeline_file(self, file_path: Path, file_name: str | None = None) -> dict:
        """上传文件到流水线文件暂存区，返回 {id, name, ...}。"""
        name = file_name or file_path.name
        with file_path.open("rb") as fh:
            content = fh.read()
        try:
            name, content = prepare_document(name, content)
        except ValueError as exc:
            raise DifyError(str(exc)) from exc
        mime, _ = mimetypes.guess_type(name)
        resp = self._client.post(
            f"{self.base_url}/datasets/pipeline/file-upload",
            headers=self._headers,
            files={"file": (name, content, mime or "application/octet-stream")},
        )
        return self._parse(resp, "upload pipeline file")

    def run_pipeline(self, dataset_id: str, start_node_id: str, reference: str,
                     name: str, timeout: float = 600.0,
                     inputs: dict | None = None) -> dict:
        """以阻塞模式运行知识流水线处理单个文件。

        create-by-file 接口对 rag_pipeline 数据集只会派发普通索引任务，
        导致「No subchunk segmentation found in rules」或控制台预览报
        PublishedWorkflowRunPayload 校验错误；流水线数据集必须走本接口。

        ⚠️ inputs 必须携带流水线定义的必填变量（如 max_chunk_length / parent_mode /
        child_length），缺失会报 500 "xxx is required in input form"。不同流水线的
        变量完全不同，值由调用方从同步源配置（pipeline_inputs）传入；
        未传时使用已发布流水线自己的默认值。

        真实响应结构（Dify 1.16.1 实测）：{batch, dataset, documents: [{id, name, ...}]}。
        """
        payload = pipeline_payload(start_node_id, reference, name, inputs)
        resp = self._client.post(f"{self.base_url}/datasets/{dataset_id}/pipeline/run",
                                 json=payload, headers=self._headers, timeout=timeout)
        return self._parse(resp, "run pipeline")

    def upload_file_via_pipeline(self, dataset_id: str, file_path: Path,
                                 file_name: str | None = None,
                                 timeout: float = 600.0,
                                 inputs: dict | None = None) -> dict:
        """流水线数据集新增文档：上传文件 → 运行流水线 → 解析响应取 document_id/batch。

        ⚠️ 真实响应结构（2026-09-11 本地 Dify 1.16.1 实测）与官方文档/源码不一致：
        实际返回 `{batch, dataset, documents: [{id, name, indexing_status, ...}]}` 顶层结构，
        而不是 WorkflowAppBlockingResponse 的 `{task_id, workflow_run_id, data: {outputs}}`。
        本实现按真实响应解析，同时保留 data.outputs 兜底路径以兼容未来版本。

        返回结构与 create-by-file 对齐：{"document": {"id", "name", "indexing_status"},
        "batch": ...}，batch 供引擎复用 wait_indexing 轮询索引进度。
        """
        name = file_name or file_path.name
        node_id = self.local_file_node_id(dataset_id)
        uploaded = self.upload_pipeline_file(file_path, file_name=name)
        reference = uploaded.get("id")
        if not reference:
            raise DifyError("流水线文件上传未返回文件 ID")
        result = self.run_pipeline(dataset_id, node_id, str(reference), name,
                                   timeout=timeout, inputs=inputs)

        try:
            return pipeline_result(result, name)
        except ValueError as exc:
            raise DifyError(str(exc)) from exc

    def update_file_via_pipeline(self, dataset_id: str, document_id: str, file_path: Path,
                                 file_name: str | None = None,
                                 timeout: float = 600.0,
                                 inputs: dict | None = None) -> dict:
        """流水线不支持原位更新；新文档索引成功后才删除旧文档。"""
        return self._replace_document(
            dataset_id, document_id,
            lambda: self.upload_file_via_pipeline(dataset_id, file_path, file_name,
                                                  timeout=timeout, inputs=inputs),
            timeout=timeout,
        )

    def _replace_document(self, dataset_id: str, document_id: str,
                          upload: Callable[[], dict], timeout: float = 600) -> dict:
        result = upload()
        new_id = (result.get("document") or {}).get("id")
        if not new_id or new_id == document_id:
            raise DifyError("替换文档未返回新的文档 ID")
        try:
            if result.get("batch"):
                self.wait_indexing(dataset_id, result["batch"], timeout=timeout)
            elif result["document"].get("indexing_status") != "completed":
                raise DifyError("替换文档未返回索引批次，无法确认成功，保留旧文档")
            try:
                self.delete_document(dataset_id, document_id)
            except DifyError as exc:
                if exc.status != 404:
                    raise
        except Exception:
            # 已知新 ID 的失败尝试回滚；原映射及旧文档仍可用于重试。
            try:
                self.delete_document(dataset_id, new_id)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("清理失败替换文档 %s 失败", new_id)
            raise
        result["document"]["indexing_status"] = "completed"
        return result

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
