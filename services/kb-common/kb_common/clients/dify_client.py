"""Dify 知识库客户端。

通过 Dify Service API 实现知识库检索与数据集管理。
- 检索端点：POST {base_url}/datasets/{dataset_id}/retrieve
- 数据集列表：GET {base_url}/datasets
鉴权使用 Dataset API Key（单个数据集）或拥有多数据集权限的 App/Console Key。
"""
import json
import logging
from typing import Any

import httpx
from kb_common.config import get_settings

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return get_settings().dify_base_url.rstrip("/")


def _api_key() -> str:
    return get_settings().dify_api_key


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}


async def retrieve(
    dataset_ids: list[str],
    query: str,
    top_k: int | None = None,
    score_threshold: float | None = None,
) -> list[dict[str, Any]]:
    """跨多个 Dify 数据集检索，合并并按 score 降序返回。

    返回的每个 hit 统一为：
        {"score": float, "content": str, "document_title": str,
         "document_id": str, "dataset_id": str, "segment_id": str,
         "page_number": int | None}
    """
    s = get_settings()
    top_k = top_k or s.dify_retrieval_top_k
    score_threshold = score_threshold if score_threshold is not None else s.dify_score_threshold
    method = (s.dify_search_method or "semantic_search").strip()

    def _payload(search_method: str) -> dict[str, Any]:
        # Dify HitTestingPayload 要求 score_threshold_enabled 必填；
        # reranking 需在 Dify 控制台配置 Rerank 模型，未配置时必须关闭（否则 400）。
        model: dict[str, Any] = {
            "search_method": search_method,
            "top_k": top_k,
            "score_threshold": score_threshold,
            "score_threshold_enabled": False,
            "reranking_enable": bool(s.dify_reranking_enable),
        }
        if model["reranking_enable"]:
            model["reranking_mode"] = "reranking_model"
            model["reranking_model"] = {
                "reranking_provider_name": "langgenius/openai_api_compatible/openai_api_compatible",
                "reranking_model_name": "BAAI/bge-reranker-v2-m3",
            }
        return {"query": query, "retrieval_model": model}

    merged: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for did in dataset_ids:
            if not did:
                continue
            url = f"{_base_url()}/datasets/{did}/retrieve"
            data = None
            for m in ([method, "full_text_search"] if method != "full_text_search" else [method]):
                try:
                    resp = await client.post(url, json=_payload(m), headers=_headers())
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except httpx.HTTPStatusError as e:
                    body = (e.response.text or "")[:200]
                    logger.warning("Dify retrieve [%s] failed for dataset %s: HTTP %s %s",
                                   m, did, e.response.status_code, body)
                except Exception as e:
                    logger.warning("Dify retrieve [%s] failed for dataset %s: %s", m, did, e)
            if not data:
                continue
            for record in data.get("records", []) or []:
                seg = record.get("segment") or {}
                doc = seg.get("document") or {}
                merged.append({
                    "score": record.get("score") or 0.0,
                    "content": seg.get("content") or "",
                    "document_title": doc.get("name") or "",
                    "document_id": seg.get("document_id") or "",
                    "dataset_id": did,
                    "segment_id": seg.get("id") or "",
                    "page_number": None,
                })

    merged.sort(key=lambda x: x["score"], reverse=True)
    return merged[:top_k]


async def list_datasets() -> list[dict[str, Any]]:
    """列出当前 API Key 可访问的 Dify 数据集，失败时抛出异常由调用方处理。"""
    url = f"{_base_url()}/datasets"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        return data.get("data") or []


async def create_dataset(name: str) -> dict[str, Any]:
    """在 Dify 中新建知识库（数据集），失败抛异常。"""
    url = f"{_base_url()}/datasets"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json={"name": name}, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def upload_document(dataset_id: str, filename: str, content: bytes) -> dict[str, Any]:
    """上传文档到指定 Dify 知识库：直接向 create-by-file 端点提交文件（自动分段索引）。

    create-by-file 端点接受 multipart/form-data，内含 file 与 data（JSON 字符串），
    使用 Dataset API Key 鉴权，无需先调用 /files/upload（该端点需 App API Key）。

    返回 document 创建结果（含 document.id / batch）。
    """
    url = f"{_base_url()}/datasets/{dataset_id}/document/create-by-file"
    data = {
        "indexing_technique": "high_quality",
        "process_rule": {"mode": "automatic"},
        "doc_form": "text_model",
        "doc_language": "Chinese",
    }
    files = {
        "file": (filename, content),
        "data": (None, json.dumps(data), "application/json"),
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(url, files=files,
                                     headers={"Authorization": f"Bearer {_api_key()}"})
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = e.response.text
            try:
                err_json = e.response.json()
                code = err_json.get("code", "")
                msg = err_json.get("message", "") or body
                if code == "invalid_param":
                    detail = "参数无效，可能原因：文件超过 Dify 大小限制、文件格式不支持、或知识库嵌入模型未配置"
                else:
                    detail = f"{code}: {msg}" if code else msg
            except Exception:
                detail = body
            raise RuntimeError(f"Dify 上传失败（HTTP {e.response.status_code}）：{detail}") from e
        return resp.json()


async def get_dataset(dataset_id: str) -> dict[str, Any] | None:
    """获取单个数据集信息。"""
    url = f"{_base_url()}/datasets/{dataset_id}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning("Dify get_dataset failed for %s: %s", dataset_id, e)
        return None
