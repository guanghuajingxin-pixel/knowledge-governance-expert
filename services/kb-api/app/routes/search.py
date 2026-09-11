import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from kb_common.database import get_session, SessionLocal
from kb_common.models import Document, UsageLog
from kb_common.rag import searcher, tracer
from app.deps import get_current_user, get_principal

router = APIRouter(prefix="/api/v1/search", tags=["search"])


class SearchIn(BaseModel):
    query: str
    kb_ids: list[str]
    top_k: int = 10
    search_type: str = "hybrid"   # hybrid | semantic | keyword
    filters: dict | None = None


def _log_usage(user_id, scene: str, query: str,
               hit_count: int, doc_ids: list[str], doc_titles: list[str]):
    """后台记录调用日志（fire-and-forget，使用独立 session，异常不影响主流程）。"""
    async def _run():
        try:
            async with SessionLocal() as s:
                s.add(UsageLog(
                    user_id=user_id,
                    scene=scene,
                    query=query,
                    hit_count=hit_count,
                    hit_document_ids=doc_ids[:50],
                    hit_document_titles=doc_titles[:50],
                ))
                await s.commit()
        except Exception:
            pass
    asyncio.create_task(_run())


@router.post("")
async def search(body: SearchIn, u=Depends(get_principal), s: AsyncSession = Depends(get_session)):
    t0 = time.perf_counter()
    hits = await _dispatch(body, rerank=True)
    doc_ids = {h.get("document_id") for h in hits if h.get("document_id")}
    docs = (await s.execute(select(Document).where(Document.id.in_(doc_ids)))).scalars().all()
    dmap = {str(d.id): (d.original_filename, d.storage_path, d.file_type) for d in docs}
    results = [tracer.trace(h, dmap) for h in hits]
    took_ms = int((time.perf_counter() - t0) * 1000)
    # 埋点
    uid = getattr(u, "id", None)
    titles = [d.original_filename for d in docs]
    _log_usage(uid, "search", body.query, len(results), [str(d.id) for d in docs], titles)
    return {"results": results, "total": len(results), "took_ms": took_ms}


@router.post("/test")
async def search_test(body: SearchIn, u=Depends(get_current_user)):
    """检索测试：返回召回内容、K 值、Score，便于调参。"""
    hits = await _dispatch(body, rerank=False)
    return {"k": body.top_k, "results": [{"text": h.get("text"), "score": h.get("score"),
            "document_title": h.get("document_title"), "chunk_index": h.get("chunk_index")} for h in hits]}


async def _dispatch(body: SearchIn, rerank: bool) -> list[dict]:
    """按 search_type 分发到 semantic/keyword/hybrid；faq 与未知值回退 hybrid。"""
    st = (body.search_type or "hybrid").lower()
    if st == "semantic":
        return await searcher.semantic(body.kb_ids, body.query, body.top_k, body.filters, rerank=rerank)
    if st == "keyword":
        return await searcher.keyword(body.kb_ids, body.query, body.top_k, body.filters)
    return await searcher.hybrid(body.kb_ids, body.query, body.top_k, body.filters, rerank=rerank)


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    kb_ids: list[UUID] = Field(default_factory=list, max_length=12)
    dify_dataset_ids: list[UUID] | None = Field(default=None, max_length=12)
    top_k: int | None = Field(default=None, ge=1, le=20)
    last_query: str = Field(default="", max_length=2000)
    last_answer: str = Field(default="", max_length=8000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=16)
    model: str = Field(default="", max_length=200)
    llm_profile_id: str = Field(default="", max_length=100)
    deep_think: bool = False
    session_id: str = Field(default="", max_length=100)
    action: Literal["", "continue", "stop"] = ""


async def _prepare_qa(body: ChatIn, user, session):
    from kb_common.config import get_settings
    from kb_common.models import Setting, KnowledgeBase, ChatMessage
    from app.services.agent.config import load_agent_config
    from app.services.llm_resolver import resolve_llm_config
    from app.services.agent.enterprise import EnterpriseQA
    from app.services.agent.enterprise_retrieval import EnterpriseRetriever

    if not body.query.strip():
        raise HTTPException(422, "问题不能为空")
    async def effective(key):
        row = (await session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        return (row.value if row else None) or getattr(get_settings(), key, "")

    cfg = await load_agent_config(session)
    llm = await resolve_llm_config(session, body.llm_profile_id, body.model)
    defaults = [d.strip() for d in (await effective("dify_dataset_ids")).split(",") if d.strip()]
    datasets = defaults if body.dify_dataset_ids is None else [str(d) for d in body.dify_dataset_ids]
    datasets = list(dict.fromkeys(datasets))
    if len(datasets) > 12:
        raise HTTPException(422, "单次最多检索12个数据集，请缩小范围")
    if user.role not in {"admin", "super_admin"} and set(datasets) - set(defaults):
        raise HTTPException(403, "无权检索未向企业问答开放的数据集")
    local_ids = [str(k) for k in body.kb_ids]
    if local_ids:
        query = select(KnowledgeBase).where(KnowledgeBase.id.in_(body.kb_ids))
        if user.role not in {"admin", "super_admin"}:
            query = query.where(KnowledgeBase.owner_id == user.id)
        rows = (await session.execute(query)).scalars().all()
        if {str(r.id) for r in rows} != set(local_ids):
            raise HTTPException(403, "无权检索指定知识库")
    history = [turn.model_dump() for turn in body.history]
    if body.session_id:
        from app.routes.chat_session_route import _get_owned
        owned = await _get_owned(body.session_id, user, session)
        rows = (await session.execute(select(ChatMessage).where(ChatMessage.session_id == owned.id)
                                     .order_by(ChatMessage.created_at.desc()).limit(8))).scalars().all()
        history = [{"role": r.role, "content": r.content[:8000]} for r in reversed(rows)]
    elif not history and body.last_query:
        history = [{"role": "user", "content": body.last_query}]
    if not cfg.get("long_memory_enabled", True):
        history = []
    if not (cfg.get("tools_enabled") or {}).get("knowledge_search", True):
        datasets, local_ids = [], []
    dify = {"base_url": await effective("dify_base_url"), "api_key": await effective("dify_api_key")}
    top_k = body.top_k if body.top_k is not None else int(cfg.get("top_k", 8))
    retriever = EnterpriseRetriever(dify, datasets, local_ids, max(top_k, 12) if body.deep_think else top_k)
    return EnterpriseQA(query=body.query, history=history, llm_config=llm, agent_config=cfg,
                        retriever=retriever, user_id=str(user.id), role=user.role)


# Cancellation is scoped by authenticated user and session. Disconnect also cancels the generator.
_ACTIVE_QA: dict[tuple[str, str], asyncio.Task] = {}


async def _qa_events(qa):
    if not qa.llm_config.get("api_key"):
        yield {"type": "config_error", "code": "llm_not_configured", "message": "请先在系统配置中配置问答模型。"}
        return
    try:
        async with asyncio.timeout(300):
            async for event in qa.stream():
                yield event
    except asyncio.TimeoutError:
        yield {"type": "final", "result": qa.result("检索或核验超时，尚未形成可靠答案，请稍后重试或缩小问题范围。", status="insufficient")}
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Enterprise QA failed")
        yield {"type": "config_error", "code": "agent_failed", "message": "问答服务暂不可用，请稍后重试。"}


@router.post("/chat")
async def chat(body: ChatIn, u=Depends(get_principal), s: AsyncSession = Depends(get_session)):
    qa = await _prepare_qa(body, u, s)
    async for event in _qa_events(qa):
        if event["type"] == "final":
            result = event["result"]
            cites = result.get("citations") or []
            _log_usage(u.id, "chat", body.query, len(cites),
                       [c.get("document_id", "") for c in cites], [c.get("document_title", "") for c in cites])
            return result
        if event["type"] == "config_error":
            return {"answer": event["message"], "citations": [], "config_error": event["code"]}


@router.post("/chat/stream")
async def chat_stream(body: ChatIn, u=Depends(get_principal), s: AsyncSession = Depends(get_session)):
    qa = await _prepare_qa(body, u, s)
    key = (str(u.id), body.session_id)
    async def generate():
        task = asyncio.current_task()
        if body.session_id:
            previous = _ACTIVE_QA.get(key)
            if previous and previous is not task:
                previous.cancel()
            _ACTIVE_QA[key] = task
        queue = asyncio.Queue()
        async def produce():
            try:
                async for event in _qa_events(qa):
                    await queue.put(event)
            finally:
                await queue.put(None)
        worker = asyncio.create_task(produce())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if event is None:
                    break
                if event["type"] == "final":
                    cites = event["result"].get("citations") or []
                    _log_usage(u.id, "chat", body.query, len(cites),
                               [c.get("document_id", "") for c in cites], [c.get("document_title", "") for c in cites])
                yield _sse(event)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            if _ACTIVE_QA.get(key) is task:
                _ACTIVE_QA.pop(key, None)
    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ChatCancelIn(BaseModel):
    session_id: str = Field(default="", max_length=100)


@router.post("/chat/cancel")
async def chat_cancel(body: ChatCancelIn, u=Depends(get_principal)):
    task = _ACTIVE_QA.get((str(u.id), body.session_id))
    if task:
        task.cancel()
    return {"cancelled": bool(task)}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
