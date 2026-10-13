"""知识库：本地文档库/物料库统一注册表（原外部镜像登记接口已随外部库集成下线）。

与「知识源管理」（推送路径定义）相互独立：本路由提供知识库列表、基础信息更新
与检索测试；文档的导入/解析走文档库管理（managed_library）。
"""
from datetime import datetime
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session
from kb_common.models import KnowledgeLibrary
from app.deps import get_current_user, require_role

router = APIRouter(prefix="/api/v1/knowledge-libraries", tags=["knowledge-library"])


class KnowledgeLibraryOut(BaseModel):
    id: int
    name: str
    platform: str
    dataset_id: str
    description: str
    enabled: bool
    library_type: str
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeLibraryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    enabled: bool | None = None


@router.get("", response_model=list[KnowledgeLibraryOut])
async def list_knowledge_libraries(
    enabled_only: bool = Query(False, description="只返回已启用的知识库"),
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """知识库列表：问答页/统一检索等所有「选择知识库」处从此接口取数。"""
    q = select(KnowledgeLibrary).where(KnowledgeLibrary.library_type != "material")
    if enabled_only:
        q = q.where(KnowledgeLibrary.enabled == True)  # noqa: E712
    q = q.order_by(KnowledgeLibrary.platform, KnowledgeLibrary.id.desc())
    return (await s.execute(q)).scalars().all()


@router.put("/{library_id}", response_model=KnowledgeLibraryOut,
            dependencies=[Depends(require_role("super_admin", "admin"))])
async def update_knowledge_library(
    library_id: int,
    payload: KnowledgeLibraryUpdate,
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """更新知识库（改名/描述/启停）。"""
    lib = await s.get(KnowledgeLibrary, library_id)
    if lib is None:
        raise HTTPException(404, "知识库不存在")
    data = payload.model_dump(exclude_unset=True)
    if lib.library_type == "material":
        raise HTTPException(409, "物料库请通过物料库管理入口修改")
    if lib.library_type == "document" and set(data) - {"enabled"}:
        raise HTTPException(409, "项目文档库的名称和设置请通过文档库设置接口修改")
    if "name" in data:
        if not (data["name"] or "").strip():
            raise HTTPException(422, "知识库名称不能为空")
        data["name"] = data["name"].strip()
    for key, value in data.items():
        setattr(lib, key, value)
    await s.commit()
    await s.refresh(lib)
    return lib


class RetrievalTestIn(BaseModel):
    query: str = Field(max_length=2000)
    # 空 = 全部登记的知识库（含停用，便于排查）；也可指定子集
    library_ids: list[int] = Field(default_factory=list)
    # 检索参数均可缺省：缺省时按「知识库设置-检索设置」(engine_config.retrieval) 取库级默认
    top_k: int | None = Field(None, ge=1, le=50)
    # 检索模式：hybrid=混合检索、vector=向量检索（weight=1.0）、fulltext=全文检索（weight=0.0）
    mode: Literal["hybrid", "vector", "fulltext"] | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    rerank: bool | None = None
    rerank_model_id: UUID | None = None
    # 阈值作用于最终分数；向量权重作用于混合检索。
    similarity_threshold: float | None = Field(None, ge=0, le=1)
    vector_similarity_weight: float | None = Field(None, ge=0, le=1)


async def _search_document_library(s: AsyncSession, lib, query: str, top_k: int,
                                    mode: str = "hybrid", **options) -> list[dict]:
    from app.services.library_retrieval import search
    return await search(s, lib, query, top_k, mode, **options)


@router.post("/retrieval-test", dependencies=[Depends(require_role("super_admin", "admin"))])
async def retrieval_test(body: RetrievalTestIn,
                         u=Depends(get_current_user),
                         s: AsyncSession = Depends(get_session)):
    """检索测试：本地文档库执行 RAGFlow NLP 检索核（向量 + 词项混合）。

    用于排查「引擎自带检索能搜到、智能问答检索不到」的断层：逐库返回
    ok/失败原因与命中分段，检索参数原样回显方便与引擎侧测试对齐。
    """
    return await execute_retrieval(body, s)


async def execute_retrieval(body: RetrievalTestIn, s: AsyncSession, *, public: bool = False):
    """Shared retrieval implementation; public calls must name enabled libraries explicitly."""
    import time as _time

    if not body.query.strip():
        raise HTTPException(422, "检索词不能为空")

    q = select(KnowledgeLibrary).where(KnowledgeLibrary.library_type != "material")
    if public:
        if not body.library_ids:
            raise HTTPException(422, "必须指定知识库")
        q = q.where(KnowledgeLibrary.enabled.is_(True))
    if body.library_ids:
        q = q.where(KnowledgeLibrary.id.in_(body.library_ids))
    libs = (await s.execute(q.order_by(KnowledgeLibrary.platform, KnowledgeLibrary.id))).scalars().all()
    if public and {lib.id for lib in libs} != set(body.library_ids):
        raise HTTPException(403, "指定知识库不存在或未开放检索")
    if not libs:
        raise HTTPException(404, "未找到指定知识库")

    started = _time.monotonic()
    lib_report: list[dict] = []
    hits: list[dict] = []
    max_top_k = body.top_k or 8  # 各库生效 top_k 的最大值：多库合并后按此截取
    for lib in libs:
        entry = {"library_id": lib.id, "name": lib.name, "platform": lib.platform,
                 "dataset_id": lib.dataset_id, "enabled": lib.enabled,
                 "ok": False, "count": 0, "error": ""}
        try:
            # 真实向量与词项评分，过滤后排序、父段去重。
            # 未显式传参的检索参数按库级「检索设置」(engine_config.retrieval) 取默认。
            rcfg = (lib.engine_config or {}).get("retrieval") or {}
            eff_mode = body.mode or rcfg.get("mode") or "hybrid"
            eff_top_k = body.top_k or rcfg.get("top_k") or 8
            max_top_k = max(max_top_k, eff_top_k)
            eff_threshold = body.similarity_threshold if body.similarity_threshold is not None \
                else float(rcfg.get("score_threshold") or 0.0)
            eff_weight = body.vector_similarity_weight if body.vector_similarity_weight is not None \
                else float(rcfg.get("vector_weight") or 0.7)
            eff_rerank = body.rerank if body.rerank is not None else bool(rcfg.get("rerank"))
            eff_rerank_model = str(body.rerank_model_id) if body.rerank_model_id else \
                (str(rcfg["rerank_model_id"]) if rcfg.get("rerank_model_id") else None)
            entry |= {"mode": eff_mode, "top_k": eff_top_k, "score_threshold": eff_threshold,
                      "vector_weight": eff_weight, "rerank": eff_rerank}
            lib_hits = await _search_document_library(
                s, lib, body.query, eff_top_k, eff_mode,
                document_ids=[str(d) for d in body.document_ids],
                threshold=eff_threshold,
                vector_weight=eff_weight,
                rerank=eff_rerank,
                rerank_model_id=eff_rerank_model)
            for h in lib_hits:
                hits.append({**h, "library_id": lib.id, "library_name": lib.name})
            entry["ok"] = True
            entry["count"] = len(lib_hits)
        except Exception as e:  # noqa: BLE001 - 逐库隔离：单库失败不影响其他库测试
            entry["error"] = f"{e.__class__.__name__}: {e}"
        lib_report.append(entry)

    hits.sort(key=lambda x: x.get("score") or 0.0, reverse=True)
    hits = hits[:max_top_k]
    return {
        "query": body.query,
        "top_k": max_top_k,
        "elapsed_ms": int((_time.monotonic() - started) * 1000),
        "libraries": lib_report,
        "hits": hits,
        "total": len(hits),
    }
