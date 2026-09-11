"""知识加工路由：对已进入 Dify 的文档进行打标、摘要、关系构建，并提供上下文扩展接口。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session
from kb_common.clients import dify_client
from kb_common.models import ProcessedDocument, KnowledgeRelation, KnowledgeTag, Setting
from kb_common.config import get_settings
from app.deps import require_role
from app.services import processing

router = APIRouter(prefix="/api/v1/process", tags=["process"])


async def _runtime_dify_config(s: AsyncSession) -> tuple[str, str]:
    base_url_row = (await s.execute(select(Setting).where(Setting.key == "dify_base_url"))).scalar_one_or_none()
    api_key_row = (await s.execute(select(Setting).where(Setting.key == "dify_api_key"))).scalar_one_or_none()
    base_url = (base_url_row.value if base_url_row else None) or get_settings().dify_base_url
    api_key = (api_key_row.value if api_key_row else None) or get_settings().dify_api_key
    # 写入运行时配置，供 dify_client 读取
    settings = get_settings()
    settings.dify_base_url = base_url
    settings.dify_api_key = api_key
    return base_url, api_key


def _require_config(base_url: str, api_key: str) -> None:
    if not base_url:
        raise HTTPException(400, "尚未配置 Dify 服务地址，请先在『系统配置』中填写")
    if not api_key:
        raise HTTPException(400, "尚未配置 Dify API Key，请先在『系统配置』中填写")


# ---------- 文档列表（合并 Dify 文档 + 本地加工状态） ----------

@router.get("/datasets/{dataset_id}/documents")
async def list_processed_documents(
    dataset_id: str,
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    """列出数据集下所有文档及其加工状态（合并 Dify 文档列表与本地 processed_documents）。"""
    base_url, api_key = await _runtime_dify_config(s)
    _require_config(base_url, api_key)

    try:
        dify_docs = await dify_client.list_documents(dataset_id)
    except Exception as e:
        raise HTTPException(502, f"获取 Dify 文档列表失败：{e}")

    processed = (await s.execute(
        select(ProcessedDocument).where(ProcessedDocument.dataset_id == dataset_id)
    )).scalars().all()
    pmap = {p.document_id: p for p in processed}

    items = []
    for d in dify_docs:
        doc_id = d.get("id") or ""
        name = d.get("name") or ""
        p = pmap.get(doc_id)
        items.append({
            "document_id": doc_id,
            "name": name,
            "word_count": d.get("word_count") or 0,
            "status": d.get("indexing_status") or d.get("status") or "",
            "process_status": p.process_status if p else "pending",
            "tags": p.tags if p else [],
            "summary": p.summary if p else "",
            "doc_type": p.doc_type if p else "",
            "processed_at": p.updated_at.isoformat() if p and p.process_status == "completed" else None,
        })
    return {"items": items}


# ---------- 单个文档加工详情 ----------

@router.get("/documents/{document_id}")
async def get_processed_document(
    document_id: str,
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    p = (await s.execute(
        select(ProcessedDocument).where(ProcessedDocument.document_id == document_id)
    )).scalar_one_or_none()
    if not p:
        return {"exists": False}
    return {
        "exists": True,
        "document_id": p.document_id,
        "dataset_id": p.dataset_id,
        "name": p.name,
        "tags": p.tags,
        "summary": p.summary,
        "keywords": p.keywords,
        "doc_type": p.doc_type,
        "process_status": p.process_status,
        "error_message": p.error_message,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# ---------- AI 打标 + 摘要生成 ----------

@router.post("/datasets/{dataset_id}/documents/{document_id}/enhance")
async def enhance_document(
    dataset_id: str,
    document_id: str,
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    """对单个文档执行 AI 打标 + 摘要生成。"""
    base_url, api_key = await _runtime_dify_config(s)
    _require_config(base_url, api_key)
    result = await processing.enhance_document(s, dataset_id, document_id)
    if result.get("status") == "failed":
        raise HTTPException(500, result.get("error", "加工失败"))
    return result


# ---------- 批量加工 ----------

@router.post("/datasets/{dataset_id}/enhance-all")
async def enhance_all_documents(
    dataset_id: str,
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    """对数据集中所有文档执行 AI 打标 + 摘要生成（顺序处理）。"""
    base_url, api_key = await _runtime_dify_config(s)
    _require_config(base_url, api_key)
    try:
        dify_docs = await dify_client.list_documents(dataset_id)
    except Exception as e:
        raise HTTPException(502, f"获取 Dify 文档列表失败：{e}")

    results = []
    for d in dify_docs:
        doc_id = d.get("id")
        if not doc_id:
            continue
        try:
            r = await processing.enhance_document(s, dataset_id, doc_id)
            results.append(r)
        except Exception as e:
            results.append({"document_id": doc_id, "status": "failed", "error": str(e)})
    completed = sum(1 for r in results if r.get("status") == "completed")
    failed = sum(1 for r in results if r.get("status") == "failed")
    return {"total": len(results), "completed": completed, "failed": failed, "results": results}


# ---------- 构建知识关系 ----------

@router.post("/datasets/{dataset_id}/build-relations")
async def build_relations(
    dataset_id: str,
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    """对数据集中已加工的文档两两构建语义关系。"""
    return await processing.build_relations(s, dataset_id)


# ---------- 文档关系查询 ----------

@router.get("/documents/{document_id}/relations")
async def get_document_relations(
    document_id: str,
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    """获取指定文档的所有关联文档。"""
    rels = (await s.execute(
        select(KnowledgeRelation)
        .where(KnowledgeRelation.source_doc_id == document_id)
        .order_by(KnowledgeRelation.weight.desc())
    )).scalars().all()

    items = []
    for rel in rels:
        target = (await s.execute(
            select(ProcessedDocument).where(ProcessedDocument.document_id == rel.target_doc_id)
        )).scalar_one_or_none()
        items.append({
            "target_doc_id": rel.target_doc_id,
            "target_name": target.name if target else rel.target_doc_id,
            "relation_type": rel.relation_type,
            "weight": rel.weight,
            "description": rel.description,
        })
    return {"items": items}


# ---------- 知识图谱（整个数据集） ----------

@router.get("/datasets/{dataset_id}/graph")
async def get_knowledge_graph(
    dataset_id: str,
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    """返回数据集的知识图谱数据（节点=文档，边=关系），供前端可视化。"""
    docs = (await s.execute(
        select(ProcessedDocument).where(ProcessedDocument.dataset_id == dataset_id)
    )).scalars().all()
    doc_ids = [d.document_id for d in docs]

    nodes = [{
        "id": d.document_id,
        "name": d.name,
        "tags": d.tags,
        "doc_type": d.doc_type,
    } for d in docs]

    edges = []
    if doc_ids:
        rels = (await s.execute(
            select(KnowledgeRelation).where(KnowledgeRelation.source_doc_id.in_(doc_ids))
        )).scalars().all()
        seen = set()
        for rel in rels:
            pair = tuple(sorted([rel.source_doc_id, rel.target_doc_id]))
            if pair in seen:
                continue
            seen.add(pair)
            edges.append({
                "source": rel.source_doc_id,
                "target": rel.target_doc_id,
                "relation_type": rel.relation_type,
                "weight": rel.weight,
                "description": rel.description,
            })
    return {"nodes": nodes, "edges": edges}


# ---------- 上下文扩展（供智能问答调用） ----------

@router.get("/context/expand")
async def expand_context(
    document_ids: str = Query(..., description="逗号分隔的文档 ID 列表"),
    query: str = Query("", description="用户问题"),
    max_related: int = Query(3, ge=1, le=10),
    u=Depends(require_role("super_admin", "admin", "editor", "viewer")),
    s: AsyncSession = Depends(get_session),
):
    """根据命中的文档 ID 扩展问答上下文（摘要 + 关联文档 + 标签）。"""
    ids = [x.strip() for x in document_ids.split(",") if x.strip()]
    return await processing.expand_context(s, ids, query, max_related)


# ---------- 标签库 ----------

@router.get("/tags")
async def list_tags(
    u=Depends(require_role("super_admin", "admin", "editor", "viewer")),
    s: AsyncSession = Depends(get_session),
):
    tags = (await s.execute(
        select(KnowledgeTag).order_by(KnowledgeTag.count.desc())
    )).scalars().all()
    return {"items": [{"id": str(t.id), "name": t.name, "color": t.color, "count": t.count} for t in tags]}


# ---------- 加工统计 ----------

@router.get("/stats")
async def process_stats(
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    total = (await s.execute(select(func.count(ProcessedDocument.id)))).scalar() or 0
    completed = (await s.execute(
        select(func.count(ProcessedDocument.id)).where(ProcessedDocument.process_status == "completed")
    )).scalar() or 0
    failed = (await s.execute(
        select(func.count(ProcessedDocument.id)).where(ProcessedDocument.process_status == "failed")
    )).scalar() or 0
    rel_count = (await s.execute(select(func.count(KnowledgeRelation.id)))).scalar() or 0
    tag_count = (await s.execute(select(func.count(KnowledgeTag.id)))).scalar() or 0
    return {
        "total_documents": total,
        "completed": completed,
        "failed": failed,
        "relations": rel_count,
        "tags": tag_count,
    }
