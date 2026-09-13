import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from kb_common.database import get_session, SessionLocal
from kb_common.models import Document, UsageLog
from kb_common.rag import searcher, tracer
from app.deps import get_current_user, get_principal

router = APIRouter(prefix="/api/v1/search", tags=["search"])
# Keep only the current question thread when conversation memory is disabled.
# Choices are part of that same question, not a new independent question.
_TURN_THREADS: dict[tuple[str, str], tuple[float, str]] = {}



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
    # 首选：知识库（检索抽象层）ID，后端按 platform 解析为 dify/ragflow 两组 dataset
    library_ids: list[int] | None = Field(default=None, max_length=24)
    # 兼容旧字段：知识源注册表 ID（推送路径登记，非管理员校验沿用）
    knowledge_source_ids: list[int] | None = Field(default=None, max_length=24)
    # 兼容旧前端：直接传 Dify 数据集 ID（缺省时按注册表兜底）
    dify_dataset_ids: list[UUID] | None = Field(default=None, max_length=12)
    top_k: int | None = Field(default=None, ge=1, le=20)
    last_query: str = Field(default="", max_length=2000)
    last_answer: str = Field(default="", max_length=8000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=16)
    model: str = Field(default="", max_length=200)
    llm_profile_id: str = Field(default="", max_length=100)
    session_id: str = Field(default="", max_length=100)
    action: Literal["", "continue", "stop"] = ""


async def _resolve_retrieval_targets(body: "ChatIn", user, session) -> tuple[list[str], list[str]]:
    """把选中的知识库解析为 (dify_dataset_ids, ragflow_dataset_ids)。

    真相源=知识库抽象层（knowledge_libraries，enabled 的 dify / ragflow 镜像）：
    - 传 library_ids：按知识库逐条解析（platform 决定通道），校验存在且启用；
    - 兼容旧 knowledge_source_ids / dify_dataset_ids：走知识源注册表解析（过渡保护）；
    - 都不传：默认全部启用的知识库镜像。
    检索策略（rerank、检索方式等）由抽象层按 platform 内部决定，与本解析无关。
    非管理员只能检索启用的库（越权 403）。
    """
    from kb_common.models import KnowledgeLibrary, KnowledgeSource

    is_admin = user.role in {"admin", "super_admin"}
    dify_ids: list[str] = []
    ragflow_ids: list[str] = []

    if body.library_ids is not None:
        rows = (await session.execute(select(KnowledgeLibrary))).scalars().all()
        by_id = {r.id: r for r in rows}
        if not is_admin:
            bad = [i for i in body.library_ids
                   if i not in by_id or not by_id[i].enabled]
            if bad:
                raise HTTPException(403, "无权检索未向企业问答开放的知识库")
        for lid in body.library_ids:
            r = by_id.get(lid)
            if not r:
                # 选到已删除的库时忽略，避免整轮失败
                continue
            (dify_ids if r.platform == "dify" else ragflow_ids).append(r.dataset_id)
    elif body.knowledge_source_ids is not None or body.dify_dataset_ids is not None:
        rows = (await session.execute(select(KnowledgeSource).where(
            KnowledgeSource.enabled == True,  # noqa: E712
            KnowledgeSource.source_type.in_(["dify_dataset", "ragflow_dataset"]),
        ))).scalars().all()
        by_id = {r.id: r for r in rows}
        allowed_dify = {r.external_id for r in rows if r.source_type == "dify_dataset"}

        if body.knowledge_source_ids is not None:
            if not is_admin:
                missing = [i for i in body.knowledge_source_ids if i not in by_id]
                if missing:
                    raise HTTPException(403, "无权检索未向企业问答开放的知识库")
            for sid in body.knowledge_source_ids:
                r = by_id.get(sid)
                if not r:
                    # 管理员可选到未启用/不存在的库时忽略，避免整轮失败
                    continue
                if r.source_type == "dify_dataset":
                    dify_ids.append(r.external_id)
                else:
                    ragflow_ids.append(r.external_id)
        else:
            # 兼容旧前端：直接传 Dify 数据集 ID。非管理员仍受注册表约束（越权即 403）。
            dify_ids = [str(d) for d in body.dify_dataset_ids]
            if not is_admin and set(dify_ids) - allowed_dify:
                raise HTTPException(403, "无权检索未向企业问答开放的数据集")
    else:
        # 缺省：知识库抽象层里全部启用的库
        rows = (await session.execute(select(KnowledgeLibrary).where(
            KnowledgeLibrary.enabled == True,  # noqa: E712
        ))).scalars().all()
        for r in rows:
            (dify_ids if r.platform == "dify" else ragflow_ids).append(r.dataset_id)

    dify_ids = list(dict.fromkeys(dify_ids))
    ragflow_ids = list(dict.fromkeys(ragflow_ids))
    if len(dify_ids) + len(ragflow_ids) > 24:
        raise HTTPException(422, "单次检索的知识库过多，请缩小范围")
    return dify_ids, ragflow_ids


async def _prepare_qa(body: ChatIn, user, session) -> dict:
    """组装 DeerFlow sidecar 调用参数（旧内置问答链已废弃，无回退）。"""
    from kb_common.models import KnowledgeBase
    from app.services.agent.config import load_agent_config
    from app.services.llm_resolver import resolve_llm_config

    if not body.query.strip():
        raise HTTPException(422, "问题不能为空")

    cfg = await load_agent_config(session)
    llm = await resolve_llm_config(session, body.llm_profile_id, body.model)
    # 检索目标：从知识源注册表解析为 dify / ragflow 两组 dataset（取代旧的 dify_dataset_ids 设置项）
    datasets, ragflow_datasets = await _resolve_retrieval_targets(body, user, session)
    local_ids = [str(k) for k in body.kb_ids]
    if local_ids:
        query = select(KnowledgeBase).where(KnowledgeBase.id.in_(body.kb_ids))
        if user.role not in {"admin", "super_admin"}:
            query = query.where(KnowledgeBase.owner_id == user.id)
        rows = (await session.execute(query)).scalars().all()
        if {str(r.id) for r in rows} != set(local_ids):
            raise HTTPException(403, "无权检索指定知识库")
    # 多轮记忆由 sidecar checkpointer 按 thread 承载：会话 ID 即 thread_id；
    # 关闭长期记忆或无会话时每次新 thread，不沿用上一轮上下文
    if body.session_id:
        from app.routes.chat_session_route import _get_owned
        owned = await _get_owned(body.session_id, user, session)
        if cfg.get("long_memory_enabled", True):
            thread_id = str(owned.id)
        else:
            key = (str(user.id), str(owned.id))
            now = time.monotonic()
            for old_key, (created, _) in list(_TURN_THREADS.items()):
                if now - created > 86400:
                    _TURN_THREADS.pop(old_key, None)
            if body.action:
                if key not in _TURN_THREADS:
                    raise HTTPException(409, "本次选择已过期，请重新提问")
                thread_id = _TURN_THREADS[key][1]
            else:
                thread_id = f"nomem-{owned.id}-{uuid4()}"
                _TURN_THREADS[key] = (now, thread_id)
                while len(_TURN_THREADS) > 1000:
                    _TURN_THREADS.pop(next(iter(_TURN_THREADS)))
    else:
        thread_id = f"anon-{user.id}-{uuid4()}"
    tools = cfg.get("tools_enabled") or {}
    if not tools.get("knowledge_search", True):
        datasets, ragflow_datasets, local_ids = [], [], []
    top_k = body.top_k if body.top_k is not None else int(cfg.get("top_k", 8))
    return {
        "query": body.query,
        "thread_id": thread_id,
        "dataset_ids": datasets,
        "ragflow_dataset_ids": ragflow_datasets,
        "kb_ids": local_ids,
        "top_k": top_k,
        "plan_mode": bool(cfg.get("planning_enabled", True)),
        "subagent_enabled": bool(cfg.get("subagent_enabled", False)),
        "disabled_tools": [k for k, v in tools.items() if not v],
        "llm_config": llm,
        "agent_config": cfg,
        "action": body.action,
    }


# Cancellation is scoped by authenticated user and session. Disconnect also cancels the generator.
_ACTIVE_QA: dict[tuple[str, str], asyncio.Task] = {}


async def _qa_events(params: dict):
    from app.services.agent.deerflow_runner import (DeerflowUnavailable,
                                                     cancel_deerflow_stream,
                                                     run_deerflow_stream)
    if not params["llm_config"].get("api_key"):
        yield {"type": "config_error", "code": "llm_not_configured", "message": "请先在系统配置中配置问答模型。"}
        return
    try:
        async with asyncio.timeout(660):
            async for event in run_deerflow_stream(**params):
                yield event
    except asyncio.TimeoutError:
        await cancel_deerflow_stream(params["thread_id"])
        yield {"type": "final", "result": {
            "answer": "检索或回答超时，尚未形成可靠答案，请稍后重试或缩小问题范围。",
            "citations": [], "follow_ups": [], "engine": "deerflow",
            "answer_status": "insufficient",
            "sufficiency": {"sufficient": False, "missing": "问答超时"},
            "quality": {"verification": "prompt", "dws": "not_needed", "warnings": ["问答超时"]},
            "rewritten_query": params["query"], "last_query": params["query"],
            "last_answer": "", "usage": {}}}
    except DeerflowUnavailable as exc:
        # fail-fast：sidecar 未就绪直接报错，不回退旧链
        yield {"type": "config_error", "code": "agent_not_ready",
               "message": f"DeerFlow 问答服务未就绪：{exc}。请确认 sidecar 已启动。"}
    except Exception:
        import logging
        logging.getLogger(__name__).exception("DeerFlow QA failed")
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
        if event["type"] == "choice_pause":
            return {"answer": event.get("evidence_summary", ""), "answer_status": "awaiting_choice",
                    "choice": event, "citations": event.get("citations", []), "engine": "deerflow"}
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
        terminal_received = False
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if event is None:
                    break
                if event["type"] in {"final", "choice_pause"}:
                    terminal_received = True
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
            from app.services.agent.deerflow_runner import cancel_deerflow_stream
            if not terminal_received:
                await cancel_deerflow_stream(qa["thread_id"])
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
