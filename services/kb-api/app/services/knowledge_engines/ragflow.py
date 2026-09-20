"""HTTP contract verified against ragflow 7f09c774; vendor code is never imported.

Only retry a legacy PUT on a definitive 405 response to PATCH; never retry
ambiguous mutations (timeouts, 5xx), which could duplicate work remotely.
"""
from urllib.parse import quote
import httpx

from . import EngineError


def segment(value: str) -> str:
    return quote(value, safe="")


class RagflowEngine:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/api/v1"):
            self.base_url += "/api/v1"
        self.api_key = api_key
        if not base_url or not api_key:
            raise EngineError("请先在系统配置中配置 RAGFlow 服务地址和 API Key")

    async def request(self, method, path, **kwargs):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.request(method, self.base_url + path,
                    headers={"Authorization": f"Bearer {self.api_key}"}, **kwargs)
                if response.status_code == 405 and method == "PATCH":
                    response = await client.request("PUT", self.base_url + path,
                        headers={"Authorization": f"Bearer {self.api_key}"}, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EngineError(f"RAGFlow 请求失败（{type(exc).__name__}），请检查服务和接口版本") from exc
        if not isinstance(payload, dict):
            raise EngineError("RAGFlow 返回格式不符合接口契约")
        if payload.get("code", 0) != 0:
            raise EngineError(str(payload.get("message") or "RAGFlow 操作失败"))
        return payload.get("data")

    async def embedding_models(self):
        data = await self.request("GET", "/models", params={"type": "embedding"})
        rows = data if isinstance(data, list) else (data or {}).get("models", [])
        return [{"id": m.get("model_id") or m.get("model_name") or m.get("name"),
                 "name": "@".join(filter(None, [m.get("name") or m.get("model_name"),
                    m.get("instance_name") or m.get("model_instance"), m.get("provider_name") or m.get("model_provider")]))}
                for m in rows if m.get("enable", True)]

    def dataset_path(self, dataset):
        return f"/datasets/{segment(dataset)}"

    def document_path(self, dataset, document):
        return self.dataset_path(dataset) + f"/documents/{segment(document)}"

    async def create(self, name, description, config):
        return await self.request("POST", "/datasets", json={
            "name": name, "description": description, "permission": "me", **config})

    async def delete_dataset(self, dataset):
        return await self.request("DELETE", "/datasets", json={"ids": [dataset]})

    async def configure(self, dataset, config):
        return await self.request("PUT", self.dataset_path(dataset), json=config)

    async def upload(self, dataset, name, content):
        data = await self.request("POST", self.dataset_path(dataset) + "/documents",
                                  files={"file": (name, content, "application/octet-stream")})
        if not isinstance(data, list) or not data or not data[0].get("id"):
            raise EngineError("RAGFlow 上传未返回文档 ID；请检查引擎后重试")
        return data[0]

    async def document(self, dataset, document):
        data = await self.request("GET", self.dataset_path(dataset) + "/documents", params={"id": document, "page": 1, "page_size": 1})
        docs = (data or {}).get("docs", [])
        if not docs or docs[0].get("id") != document:
            raise EngineError("引擎中的文档不存在，请检查知识库绑定")
        return docs[0]

    async def configure_document(self, dataset, document, config):
        return await self.request("PATCH", self.document_path(dataset, document), json=config)

    async def parse(self, dataset, document, stop=False):
        return await self.request("DELETE" if stop else "POST", self.dataset_path(dataset) + "/chunks", json={"document_ids": [document]})

    async def chunks(self, dataset, document, page=1, size=20, keywords=""):
        return await self.request("GET", self.document_path(dataset, document) + "/chunks", params={"page": page, "page_size": size, **({"keywords": keywords} if keywords else {})})

    async def write_chunk(self, dataset, document, body, chunk=None):
        path = self.document_path(dataset, document) + "/chunks"
        if chunk:
            path += "/" + segment(chunk)
        result = await self.request("PATCH" if chunk else "POST", path, json=body)
        # RAGFlow add_chunk ignores available; set it explicitly on the returned ID.
        if not chunk and not body.get("available", True):
            created_id = (result or {}).get("chunk", {}).get("id")
            if not created_id:
                raise EngineError("分段已创建但未返回 ID，无法停用，请刷新后处理")
            await self.request("PATCH", path + "/" + segment(created_id), json={"available": False})
        return result

    async def delete_chunk(self, dataset, document, chunk):
        return await self.request("DELETE", self.document_path(dataset, document) + "/chunks", json={"chunk_ids": [chunk]})

    async def delete_document(self, dataset, document):
        return await self.request("DELETE", self.dataset_path(dataset) + "/documents", json={"ids": [document]})


def document_state(remote):
    run = str(remote.get("run", "0")).upper()
    progress = float(remote.get("progress") or 0)
    status = {"0": "UPLOADED", "1": "PARSING", "2": "CANCELLED", "3": "COMPLETED", "4": "FAILED",
              "UNSTART": "UPLOADED", "RUNNING": "PARSING", "CANCEL": "CANCELLED", "DONE": "COMPLETED", "FAIL": "FAILED"}.get(run, "UNKNOWN")
    if progress < 0:
        status = "FAILED"
    return status, max(0, min(1, progress))
