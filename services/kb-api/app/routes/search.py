import asyncio
import json
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
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


class ChatIn(BaseModel):
    query: str
    kb_ids: list[str] = []                 # 本地 ES 知识库 ID（兼容旧逻辑）
    dify_dataset_ids: list[str] | None = None  # Dify 数据集 ID；为空时走默认配置
    top_k: int = 5
    last_query: str = ""                   # 上一轮改写后的问题（会话上下文）
    last_answer: str = ""                  # 上一轮回答（会话上下文）
    history: list[dict] = []               # 多轮记忆 [{"role": "user"/"assistant", "content": ...}]
    model: str = ""                        # 前端选定的模型（覆盖系统配置默认）
    llm_profile_id: str = ""               # 模型所属供应商配置 ID（多供应商模型管理）
    deep_think: bool = False               # 深度思考开关：增大召回 + 更详尽推理
    session_id: str = ""                   # 前端会话 ID：映射 DeerFlow thread（重新对话时刷新）
    # 限时探索续跑动作：""=新问题；"continue"=用户选择继续探索；"stop"=先基于已检索内容回答
    action: str = ""


@router.post("/chat")
async def chat(body: ChatIn, u=Depends(get_principal), s: AsyncSession = Depends(get_session)):
    # 优先使用 Dify Agent（指定了数据集或配置了默认数据集）
    from kb_common.config import get_settings
    from kb_common.models import Setting
    from sqlalchemy import select

    async def _effective(key: str) -> str:
        row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        return (row.value if row else None) or getattr(get_settings(), key)

    dify_api_key = await _effective("dify_api_key")
    if body.dify_dataset_ids is not None or dify_api_key:
        from app.services.agent import run_agent
        from app.services.llm_resolver import resolve_llm_config
        llm_config = await resolve_llm_config(s, body.llm_profile_id, body.model)
        dify_config = {
            "base_url": await _effective("dify_base_url"),
            "api_key": dify_api_key,
        }
        from app.services.agent.config import load_agent_config
        agent_cfg = await load_agent_config(s)
        result = await run_agent(
            body.query,
            dataset_ids=body.dify_dataset_ids,
            last_query=body.last_query,
            last_answer=body.last_answer,
            history=body.history,
            top_k=body.top_k,
            deep_think=body.deep_think,
            llm_config=llm_config,
            dify_config=dify_config,
            agent_config=agent_cfg,
        )
        # 埋点
        cites = result.get("citations") or []
        titles = [c.get("document_title") or c.get("title") or "" for c in cites if isinstance(c, dict)]
        _log_usage(getattr(u, "id", None), "chat", body.query, len(cites), [], titles)
        return result

    # 回退：本地 ES 知识库问答
    from app.services.chat import answer
    result = await answer(body.query, body.kb_ids, body.top_k, s)
    cites = result.get("citations") or []
    titles = [c.get("document_title") or c.get("title") or "" for c in cites if isinstance(c, dict)]
    _log_usage(s, getattr(u, "id", None), "chat", body.query, len(cites), [], titles)
    return result


@router.post("/chat/stream")
async def chat_stream(body: ChatIn, u=Depends(get_principal), s: AsyncSession = Depends(get_session)):
    """智能问答流式端点（SSE）：逐节点推送 Agent 步骤进度，最终推送完整结果。

    事件格式（每行 `data: {json}\\n\\n`）：
      {"type":"step","node":"classify","title":"🔍 问题分类","detail":"正在分析问题类型…","data":{...}}
      {"type":"final","result":{"answer":...,"citations":[...],...}}
      {"type":"config_error","code":"llm_not_configured","message":"..."}
    """
    from kb_common.config import get_settings
    from kb_common.models import Setting
    from sqlalchemy import select

    async def _effective(key: str) -> str:
        row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        return (row.value if row else None) or getattr(get_settings(), key)

    dify_api_key = await _effective("dify_api_key")
    has_dify = body.dify_dataset_ids is not None or dify_api_key

    if not has_dify:
        # 无 Dify 时不走流式 Agent，直接返回配置引导
        async def _no_dify():
            yield _sse({"type": "config_error", "code": "dify_not_configured",
                        "message": "尚未配置 Dify 知识库，请前往「系统配置」配置。"})
        return StreamingResponse(_no_dify(), media_type="text/event-stream")

    from app.services.agent import run_agent_stream
    from app.services.llm_resolver import resolve_llm_config
    llm_config = await resolve_llm_config(s, body.llm_profile_id, body.model)
    dify_config = {
        "base_url": await _effective("dify_base_url"),
        "api_key": dify_api_key,
    }

    from app.services.agent.config import load_agent_config
    agent_cfg = await load_agent_config(s)

    # DeerFlow 2.0 thread：同一会话（session_id）共享长期记忆与上下文
    import uuid as _uuid
    uid = getattr(u, "id", None) or "anon"
    sid = body.session_id.strip() or _uuid.uuid4().hex
    thread_id = f"kge-u{uid}-{sid}"

    async def _gen():
        try:
            # 1) 优先 DeerFlow 2.0 sidecar（工具调用循环 + 子智能体 + 长期记忆）
            try:
                from app.services.agent.deerflow_runner import DeerflowUnavailable, is_deerflow_alive, run_deerflow_stream

                if await is_deerflow_alive():
                    # 工具开关：tools_enabled 中为 False 的工具不下发给智能体
                    tools_enabled = agent_cfg.get("tools_enabled") or {}
                    disabled_tools = [k for k, on in tools_enabled.items() if not on]
                    async for evt in run_deerflow_stream(
                        body.query,
                        thread_id=thread_id,
                        dataset_ids=body.dify_dataset_ids,
                        top_k=max(int(body.top_k or 5), int(agent_cfg.get("top_k") or 8)),
                        deep_think=body.deep_think,
                        plan_mode=bool(agent_cfg.get("planning_enabled", True)),
                        subagent_enabled=bool(agent_cfg.get("subagent_enabled", False)),
                        disabled_tools=disabled_tools,
                        llm_config=llm_config,
                        agent_config=agent_cfg,
                        action=body.action,
                    ):
                        yield _sse(evt)
                        if evt.get("type") == "final":
                            cites = (evt.get("result") or {}).get("citations") or []
                            titles = [c.get("document_title") or c.get("title") or ""
                                      for c in cites if isinstance(c, dict)]
                            _log_usage(uid, "chat", body.query, len(cites), [], titles)
                    return
            except DeerflowUnavailable:
                pass  # sidecar 未就绪，回退内置工作流
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("deerflow stream error, fallback: %s", e)

            # 2) 回退：内置 LangGraph 工作流
            try:
                async for evt in run_agent_stream(
                    body.query,
                    dataset_ids=body.dify_dataset_ids,
                    last_query=body.last_query,
                    last_answer=body.last_answer,
                    history=body.history,
                    top_k=body.top_k,
                    deep_think=body.deep_think,
                    llm_config=llm_config,
                    dify_config=dify_config,
                    agent_config=agent_cfg,
                ):
                    yield _sse(evt)
                    # 最终结果埋点
                    if evt.get("type") == "final":
                        cites = (evt.get("result") or {}).get("citations") or []
                        titles = [c.get("document_title") or c.get("title") or ""
                                  for c in cites if isinstance(c, dict)]
                        _log_usage(uid, "chat", body.query,
                                    len(cites), [], titles)
            except Exception as e:
                yield _sse({"type": "config_error", "code": "agent_failed",
                            "message": f"🤖 智能问答执行失败（{e.__class__.__name__}）。"})
        finally:
            # 用户点停止/关闭页面/切换会话导致客户端断连时，通知 sidecar 中断
            # agent 执行（未开始的模型调用不再发起，停止空转耗 token）；
            # 正常结束时该调用为 no-op（thread 状态已清理）。
            try:
                from app.services.agent.deerflow_runner import cancel_deerflow_stream
                await cancel_deerflow_stream(thread_id)
            except Exception:
                pass

    return StreamingResponse(_gen(), media_type="text/event-stream")


class ChatCancelIn(BaseModel):
    session_id: str = ""


@router.post("/chat/cancel")
async def chat_cancel(body: ChatCancelIn, u=Depends(get_principal)):
    """中断进行中的流式回答（用户点停止按钮）：通知 sidecar 停止 agent 执行。

    thread_id 规则与 chat_stream 一致（kge-u{uid}-{session_id}）。
    前端在 abort SSE 连接之外额外调用本端点，确保取消信号确定性到达
    （不依赖断连检测时机）；正常结束时为 no-op。
    """
    import uuid as _uuid
    uid = getattr(u, "id", None) or "anon"
    sid = (body.session_id or "").strip() or _uuid.uuid4().hex
    thread_id = f"kge-u{uid}-{sid}"
    from app.services.agent.deerflow_runner import cancel_deerflow_stream
    await cancel_deerflow_stream(thread_id)
    return {"cancelled": True}


def _sse(obj: dict) -> str:
    """SSE 单条消息：`data: {json}\\n\\n`"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
