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


async def _dataset_retrieval_model(client: httpx.AsyncClient, did: str, top_k: int) -> dict[str, Any] | None:
    """拉取知识库自身在 Dify 控制台保存的检索配置（含 Rerank 模型），仅放大 top_k 后复用。

    返回 None 表示拉取失败或知识库未保存配置，调用方回退到环境变量配置。
    """
    try:
        resp = await client.get(f"{_base_url()}/datasets/{did}", headers=_headers())
        resp.raise_for_status()
        raw = (resp.json() or {}).get("retrieval_model_dict")
        if not (isinstance(raw, dict) and raw.get("search_method")):
            return None
        cfg = {k: v for k, v in raw.items() if v not in (None, [], {})}
        rerank = raw.get("reranking_model") or {}
        # reranking_model 为空对象时必须剔除，否则 Dify 校验会以空模型名报 400
        if not (cfg.get("reranking_enable") and rerank.get("reranking_model_name")):
            cfg.pop("reranking_model", None)
        cfg["top_k"] = max(int(cfg.get("top_k") or 0), top_k)
        return cfg
    except Exception as e:
        logger.warning("Fetch dataset %s retrieval config failed: %s", did, e)
        return None


async def retrieve(
    dataset_ids: list[str],
    query: str,
    top_k: int | None = None,
    score_threshold: float | None = None,
) -> list[dict[str, Any]]:
    """跨多个 Dify 数据集检索，合并并按 score 降序返回。

    优先使用各知识库自身保存的检索配置（含其 Rerank 模型）——单一知识库时
    返回顺序即 Dify Rerank 后的顺序；拉取配置失败时回退到环境变量配置。

    返回的每个 hit 统一为：
        {"score": float, "content": str, "document_title": str,
         "document_id": str, "dataset_id": str, "segment_id": str,
         "page_number": int | None}
    """
    s = get_settings()
    top_k = top_k or s.dify_retrieval_top_k
    score_threshold = score_threshold if score_threshold is not None else s.dify_score_threshold
    method = (s.dify_search_method or "semantic_search").strip()

    def _payload(retrieval_model: dict[str, Any] | None = None,
                 search_method: str | None = None) -> dict[str, Any]:
        # Dify HitTestingPayload 要求 score_threshold_enabled 必填；
        # reranking 需在 Dify 控制台配置 Rerank 模型，未配置时必须关闭（否则 400）。
        model: dict[str, Any]
        if retrieval_model is not None:
            model = retrieval_model
        else:
            model = {
                "search_method": search_method or method,
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
            # 知识库自身配置优先（检索方式、Rerank 模型、分数阈值均以控制台配置为准）
            cfg = await _dataset_retrieval_model(client, did, top_k)
            attempts = [_payload(cfg)] if cfg else []
            # 不传 retrieval_model 时 Dify 同样使用知识库自身默认配置
            attempts.append({"query": query})
            # 知识库配置请求均失败时，最终回退到环境变量配置
            fallbacks = [method, "full_text_search"] if method != "full_text_search" else [method]
            attempts.extend(_payload(search_method=m) for m in fallbacks)
            data = None
            for payload in attempts:
                try:
                    resp = await client.post(url, json=payload, headers=_headers())
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except httpx.HTTPStatusError as e:
                    body = (e.response.text or "")[:200]
                    logger.warning("Dify retrieve failed for dataset %s: HTTP %s %s",
                                   did, e.response.status_code, body)
                except Exception as e:
                    logger.warning("Dify retrieve failed for dataset %s: %s", did, e)
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
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            dataset_response = await client.get(
                f"{_base_url()}/datasets/{dataset_id}", headers=_headers()
            )
            dataset_response.raise_for_status()
            dataset = dataset_response.json()
            data = {
                "indexing_technique": dataset.get("indexing_technique") or "high_quality",
                "doc_form": dataset.get("doc_form") or dataset.get("chunk_structure") or "text_model",
                "doc_language": "Chinese",
            }
            # Existing datasets inherit their saved processing rules, including
            # hierarchical segmentation. Only a new ordinary dataset needs defaults.
            if not dataset.get("document_count") and data["doc_form"] == "text_model":
                data["process_rule"] = {"mode": "automatic"}
            resp = await client.post(url, files={"file": (filename, content)},
                                     data={"data": json.dumps(data)},
                                     headers={"Authorization": f"Bearer {_api_key()}"})
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = e.response.text
            try:
                err_json = e.response.json()
                code = err_json.get("code", "")
                msg = err_json.get("message", "") or body
                detail = f"{code}: {msg}" if code else msg
            except Exception:
                detail = body
            hints = {
                401: "请检查系统配置中的 Dataset API Key。",
                403: "当前 API Key 无权写入此知识库。",
                413: "文件超过 Dify 或网关限制，请压缩或拆分文件。",
                415: "此 Dify 实例不支持该格式，请另存为 DOCX、PDF 或 TXT。",
                429: "Dify 请求频率或配额受限，请稍后检查配额再重试。",
            }
            raise RuntimeError(f"Dify 上传失败（HTTP {e.response.status_code}）：{detail[:800]}。{hints.get(e.response.status_code, '')}") from e
        except httpx.TimeoutException as e:
            raise RuntimeError("Dify 响应超时，请先到目标知识库确认文档是否已创建，再决定是否重试，避免重复上传。") from e
        return resp.json()


async def list_documents(dataset_id: str) -> list[dict[str, Any]]:
    """列出指定 Dify 数据集下的所有文档。"""
    url = f"{_base_url()}/datasets/{dataset_id}/documents"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        return data.get("data") or []


async def get_document_segments(dataset_id: str, document_id: str) -> list[dict[str, Any]]:
    """获取指定文档的所有分块（segment）内容。"""
    url = f"{_base_url()}/datasets/{dataset_id}/documents/{document_id}/segments"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        return data.get("data") or []


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


async def upload_document_by_text(
    dataset_id: str,
    name: str,
    text: str,
    indexing_technique: str | None = None,
) -> dict[str, Any]:
    """通过文本内容创建 Dify 文档（适用于大文件经 MinerU 解析后的 Markdown）。

    Dify create-by-file 对单文件有大小限制（通常 15MB），超大二进制文档
    可先经 MinerU 解析为 Markdown，再通过本接口写入知识库，Dify 自动分块索引。
    """
    if not text or not text.strip():
        raise RuntimeError("文本内容为空，无法创建文档")
    url = f"{_base_url()}/datasets/{dataset_id}/document/create-by-text"
    # Dify KnowledgeConfig 要求 indexing_technique 必填；doc_form 必须与数据集一致，
    # 否则 400（doc_form is different from the dataset doc_form）。
    # 均从数据集读取，与该知识库已有的索引方式（含 create-by-file 路径）保持一致。
    dataset = await get_dataset(dataset_id) or {}
    if not indexing_technique:
        indexing_technique = dataset.get("indexing_technique") or "high_quality"
    doc_form = dataset.get("doc_form") or dataset.get("chunk_structure") or "text_model"
    data: dict[str, Any] = {
        "name": name,
        "text": text,
        "doc_form": doc_form,
        "doc_language": "Chinese",
        "indexing_technique": indexing_technique,
    }
    # 与 create-by-file (_file_payload) 一致：空知识库 + 普通分段时使用自动分段规则。
    if not dataset.get("document_count") and doc_form == "text_model":
        data["process_rule"] = {"mode": "automatic"}
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(url, json=data, headers=_headers())
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = e.response.text
            try:
                err_json = e.response.json()
                code = err_json.get("code", "")
                msg = err_json.get("message", "") or body
                detail = f"{code}: {msg}" if code else msg
            except Exception:
                detail = body
            raise RuntimeError(f"Dify create-by-text 失败（HTTP {e.response.status_code}）：{detail[:800]}") from e
        except httpx.TimeoutException as e:
            raise RuntimeError("Dify create-by-text 响应超时") from e
        return resp.json()
