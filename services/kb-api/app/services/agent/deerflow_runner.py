"""DeerFlow 2.0 sidecar 运行器。

把 QA Sidecar（services/deerflow，DeerFlow 2.0 super agent harness）的 SSE 事件
转译为问答页既有的流式协议（step / answer_delta / final / config_error）。

- Lead Agent 自主决定检索次数、检索词、是否澄清、是否派发子智能体；
- knowledge_search 工具的返回内容在此汇总为引用来源（按文档去重）；
- 回答文本随 agent 产出实时下发（answer_delta）；
- sidecar 不可达时抛 DeerflowUnavailable，由上层回退到内置工作流。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, AsyncGenerator

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

DEERFLOW_URL = os.getenv("DEERFLOW_SERVICE_URL", "http://127.0.0.1:2027").rstrip("/")

# 健康检查缓存（避免每次问答都探测）
_health_cache: dict[str, Any] = {"ok": False, "ts": 0.0}
_HEALTH_TTL = 5.0


class DeerflowUnavailable(Exception):
    """sidecar 未启动或未就绪，调用方应回退到内置工作流。"""


def _filter_cited_citations(answer: str, citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只保留答案中真正引用到的文档。

    判断依据：文档标题（去掉 [钉钉] 前缀、扩展名、杰克_前缀后的核心名）
    与答案的归一化匹配。答案常把长文件名简写为《短标题》（如
    《北斗2026年半年度战略报告外宣版》 ← 杰克_北斗…_V5.0.pptx），因此除
    完整包含外，还接受「标题首段（≥6 字）出现在答案中」的简写形式。
    这样不依赖 ref 编号方案，也不会把仅检索过但答案未提及的文档列出来。
    """
    if not answer or not citations:
        return citations
    ans_lower = answer.lower()

    def _norm(t: str) -> str:
        for ch in " \t\r\n_-.，。:：;；()（）【】[]《》「」·—'’“”\"!?！？":
            t = t.replace(ch, "")
        return t.lower()

    def _core_title(title: str) -> str:
        # 去掉 [钉钉] 前缀、扩展名、通用前缀，提取可用于匹配的核心名
        t = title
        if t.startswith("[钉钉]"):
            t = t[len("[钉钉]"):]
        # 去掉扩展名
        for ext in (".docx", ".doc", ".pdf", ".xlsx", ".xls", ".ppt", ".pptx", ".txt", ".md", ".adoc"):
            if t.lower().endswith(ext):
                t = t[: -len(ext)]
                break
        # 去掉开头的 "杰克_" 前缀（答案常引用时会省略）
        if t.startswith("杰克_"):
            t = t[len("杰克_"):]
        return t.strip()

    keep: list[dict[str, Any]] = []
    for c in citations:
        title = c.get("document_title") or ""
        core = _core_title(title)
        if len(core) < 4:
            if title.lower() in ans_lower:
                keep.append(c)
            continue
        # 1) 完整核心名（归一化后）出现在答案中
        if _norm(core) in _norm(answer):
            keep.append(c)
            continue
        # 2) 简写形式：标题首段（按 _ - （） 分隔的最长语义段，≥6 字）出现在答案中
        first_seg = next(
            (s for s in [_norm(x) for x in re.split(r"[_\-（）()]+", core)] if len(s) >= 6),
            "",
        )
        if first_seg and first_seg in _norm(answer):
            keep.append(c)
    return keep


# 跨流累积的线程级引用：choice_pause → continue/stop 续跑是新的 SSE 流，
# 已读文档的引用需要按 thread 保留，否则续跑后 final citations 为空、
# 前端无法把答案中的《文档名》转成可点击的源文档链接。
_THREAD_CITES: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_THREAD_CITES_TTL = 6 * 3600  # 秒；会话通常几分钟内续跑，超时清理


def _load_thread_cites(thread_id: str) -> list[dict[str, Any]]:
    import copy

    entry = _THREAD_CITES.get(thread_id)
    if not entry:
        return []
    ts, cites = entry
    if time.time() - ts > _THREAD_CITES_TTL:
        _THREAD_CITES.pop(thread_id, None)
        return []
    return copy.deepcopy(cites)


def _store_thread_cites(thread_id: str, citations: list[dict[str, Any]]) -> None:
    # 过量清理：仅保留最近使用的线程
    if len(_THREAD_CITES) > 200:
        for k in sorted(_THREAD_CITES, key=lambda k: _THREAD_CITES[k][0])[:100]:
            _THREAD_CITES.pop(k, None)
    _THREAD_CITES[thread_id] = (time.time(), citations[-60:])


async def is_deerflow_alive() -> bool:
    now = time.time()
    if now - _health_cache["ts"] < _HEALTH_TTL:
        return _health_cache["ok"]
    ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{DEERFLOW_URL}/health")
            resp.raise_for_status()
            data = resp.json()
            ok = bool(data.get("config_ready"))
    except Exception:
        ok = False
    _health_cache["ok"] = ok
    _health_cache["ts"] = now
    return ok


async def cancel_deerflow_stream(thread_id: str) -> None:
    """通知 sidecar 中断指定 thread 的 agent 运行（用户点停止/断开 SSE 时调用）。

    fire-and-forget：sidecar 在下一个事件边界停止拉取图事件，未开始的模型
    调用由限时中间件短路，不再消耗 token。正常结束时调用为 no-op。
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)
        ) as client:
            resp = await client.post(
                f"{DEERFLOW_URL}/v1/chat/cancel", json={"thread_id": thread_id}
            )
            logger.info("sidecar cancel thread=%s -> %s", thread_id, resp.status_code)
    except Exception as e:  # noqa: BLE001
        logger.warning("sidecar cancel request failed: %s", e)


def _sse(obj: dict[str, Any]) -> dict[str, Any]:
    return obj


async def _generate_follow_ups(query: str, answer: str,
                               llm_config: dict[str, str] | None,
                               agent_config: dict[str, Any] | None) -> list[str]:
    """复用既有追问提示词，在 sidecar 回答完成后生成 3 个追问建议。"""
    cfg = agent_config or {}
    if not cfg.get("follow_up_enabled", True) or not answer:
        return []
    try:
        from .workflow import _build_llm
        from . import prompts

        llm = _build_llm(llm_config or {}, cfg, temperature=0.7)
        resp = await llm.ainvoke([
            SystemMessage(content=prompts.FOLLOW_UP_SYSTEM),
            HumanMessage(content=(
                f"用户问题：{query}\n"
                f"本次回答：\n{answer[:1500]}"
            )),
        ])
        questions = re.findall(r"(?:^|\n)\s*(?:\d+[.、)]\s*)?(.{6,60}[？?])", resp.content or "")
        return [q.strip() for q in questions[:3]]
    except Exception as e:  # noqa: BLE001
        logger.warning("deerflow follow-up generation failed: %s", e)
        return []


async def run_deerflow_stream(
    query: str,
    *,
    thread_id: str,
    dataset_ids: list[str] | None = None,
    top_k: int = 8,
    deep_think: bool = False,
    plan_mode: bool = False,
    subagent_enabled: bool = False,
    disabled_tools: list[str] | None = None,
    llm_config: dict[str, str] | None = None,
    agent_config: dict[str, Any] | None = None,
    action: str = "",
) -> AsyncGenerator[dict[str, Any], None]:
    """调用 DeerFlow sidecar 并转译事件。

     yield 协议与 run_agent_stream 兼容，额外增加：
      {"type": "answer_delta", "delta": str}  回答文本实时增量
      {"type": "choice", "question": str, "options": list[str]}  限时探索确认按钮
      {"type": "choice_pause", "question": str, "options": list[str], "usage": dict}
          智能体暂停等待用户选择（不下发 final；用户点选后以 action=continue/stop 续跑）
    """
    payload = {
        "thread_id": thread_id,
        "message": query,
        "thinking_enabled": bool(deep_think),
        "plan_mode": bool(plan_mode),
        "subagent_enabled": bool(subagent_enabled),
        "recursion_limit": 80,
        "dataset_ids": dataset_ids or [],
        "top_k": max(int(top_k or 8), 5),
        "disabled_tools": disabled_tools or [],
        "action": (action or "").strip().lower(),
    }

    answer_parts: list[str] = []
    citations: list[dict[str, Any]] = _load_thread_cites(thread_id)
    # 已见文档去重签名：钉钉条目带 [钉钉] 前缀，需还原为去重时的原始签名
    seen_docs: set[str] = {
        ("dt:" + c["document_title"][len("[钉钉] "):]) if (c.get("document_title") or "").startswith("[钉钉] ") else c.get("document_title", "")
        for c in citations
    }
    search_count = 0
    # 限时探索：智能体调用 ask_clarification 请求用户确认时，本轮以 choice_pause 结束
    choice_pending: dict[str, Any] | None = None
    usage: dict[str, Any] = {}

    yield _sse({
        "type": "step",
        "node": "df_start",
        "title": "🦌 DeerFlow 2.0 智能体",
        "detail": "正在理解问题并规划检索…",
        "data": {},
    })

    def _absorb_retrieval(content: str) -> int:
        """解析 knowledge_search 工具返回，汇总引用，返回本次召回数。"""
        nonlocal citations
        try:
            data = json.loads(content)
        except Exception:
            return 0
        hits = data.get("results") or []
        for h in hits:
            title = h.get("document_title") or "未知文档"
            sig = title
            if sig in seen_docs:
                continue
            seen_docs.add(sig)
            cite: dict[str, Any] = {
                "document_title": title,
                "page_number": h.get("page_number"),
                "score": h.get("score"),
                "content": h.get("content") or "",
            }
            # 同步自钉钉知识库的 Dify 文档：携带钉钉原始链接，引用来源点击跳钉钉预览
            if h.get("url"):
                cite["url"] = h.get("url")
                cite["node_id"] = h.get("node_id") or ""
                cite["source"] = h.get("source") or "dingtalk"
            citations.append(cite)
        return len(hits)

    def _absorb_dingtalk(content: str) -> int:
        """解析 dingtalk_search 工具返回，汇总引用，返回命中数。"""
        nonlocal citations
        try:
            data = json.loads(content)
        except Exception:
            return 0
        hits = data.get("results") or []
        for h in hits:
            title = h.get("title") or "未知文档"
            sig = f"dt:{title}"
            if sig in seen_docs:
                continue
            seen_docs.add(sig)
            citations.append({
                "document_title": f"[钉钉] {title}",
                "page_number": None,
                "score": None,
                "content": h.get("url") or "",
                "url": h.get("url") or "",
                "node_id": h.get("node_id") or "",
                "extension": h.get("extension") or "",
                "source": "dingtalk",
            })
        return len(hits)

    def _absorb_read_doc(content: str) -> None:
        """解析 dingtalk_read_doc 工具返回，把被读取的源文档纳入引用（携带 url 供前端跳转预览）。"""
        nonlocal citations
        try:
            data = json.loads(content)
        except Exception:
            return
        title = data.get("title") or ""
        if not title:
            return
        sig = f"dt:{title}"
        if sig in seen_docs:
            return
        seen_docs.add(sig)
        citations.append({
            "document_title": f"[钉钉] {title}",
            "page_number": None,
            "score": None,
            "content": data.get("url") or "",
            "url": data.get("url") or "",
            "node_id": data.get("node_id") or "",
            "extension": "",
            "source": "dingtalk",
        })

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=10.0)) as client:
            async with client.stream("POST", f"{DEERFLOW_URL}/v1/chat/stream", json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise DeerflowUnavailable(f"sidecar HTTP {resp.status_code}: {body[:200]!r}")
                event_buf = ""
                async for chunk in resp.aiter_text():
                    event_buf += chunk
                    frames = event_buf.split("\n\n")
                    event_buf = frames.pop()
                    for frame in frames:
                        line = frame.strip()
                        if not line.startswith("data:"):
                            continue
                        try:
                            evt = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        etype = evt.get("type")
                        if etype == "tool_start":
                            name = evt.get("name") or ""
                            args = evt.get("args") or {}
                            if name == "knowledge_search":
                                search_count += 1
                                q = str(args.get("query") or "")[:60]
                                detail = f"第 {search_count} 次检索：{q}" if search_count > 1 else f"检索知识库：{q}"
                                yield _sse({"type": "step", "node": "retrieve",
                                            "title": "📚 知识检索", "detail": detail,
                                            "data": {"query": args.get("query", "")}})
                            elif name == "dingtalk_search":
                                q = str(args.get("query") or "")[:60]
                                yield _sse({"type": "step", "node": "dingtalk_search",
                                            "title": "📌 钉钉知识库检索", "detail": f"检索钉钉文档：{q}",
                                            "data": {"query": args.get("query", "")}})
                            elif name == "dingtalk_read_doc":
                                title = str(args.get("title") or args.get("node_id") or "钉钉文档")[:50]
                                yield _sse({"type": "step", "node": "dingtalk_read",
                                            "title": "📖 读取钉钉文档", "detail": f"正在读取：{title}",
                                            "data": {"title": args.get("title", "")}})
                            elif name == "task":
                                desc = str(args.get("description") or args.get("prompt") or "子任务")[:80]
                                yield _sse({"type": "step", "node": "subagent",
                                            "title": "🧩 子任务派发", "detail": desc, "data": {}})
                            elif name == "ask_clarification":
                                q = str(args.get("question") or args.get("clarification") or "需要确认是否继续")
                                opts = [str(o) for o in (args.get("options") or []) if str(o).strip()]
                                choice_pending = {"question": q, "options": opts}
                                yield _sse({"type": "step", "node": "clarify",
                                            "title": "🙋 等待确认",
                                            "detail": q[:80], "data": {}})
                                # 选择按钮卡片：前端渲染选项，用户点选后以 action=continue/stop 续跑
                                yield _sse({"type": "choice", "question": q, "options": opts})
                        elif etype == "tool_end":
                            name = evt.get("name") or ""
                            if name == "knowledge_search":
                                n = _absorb_retrieval(evt.get("content") or "")
                                yield _sse({"type": "step", "node": "retrieved",
                                            "title": "✅ 检索完成",
                                            "detail": f"本次召回 {n} 段，累计检索 {len(citations)} 篇文档",
                                            "data": {"hit_count": n}})
                            elif name == "dingtalk_search":
                                n = _absorb_dingtalk(evt.get("content") or "")
                                yield _sse({"type": "step", "node": "dingtalk_done",
                                            "title": "✅ 钉钉检索完成",
                                            "detail": f"找到 {n} 个相关文档",
                                            "data": {"hit_count": n}})
                            elif name == "dingtalk_read_doc":
                                _absorb_read_doc(evt.get("content") or "")
                                yield _sse({"type": "step", "node": "dingtalk_read_done",
                                            "title": "✅ 文档读取完成",
                                            "detail": "已获取正文内容", "data": {}})
                            elif name == "task":
                                yield _sse({"type": "step", "node": "subagent_done",
                                            "title": "📥 子任务返回", "detail": "子智能体调研结果已汇总",
                                            "data": {}})
                        elif etype == "ai_text":
                            text = evt.get("content") or ""
                            if text.strip():
                                answer_parts.append(text)
                                yield _sse({"type": "answer_delta", "delta": text})
                        elif etype == "cancelled":
                            # 用户手动中断（停止按钮/断连）：立即结束，不再生成追问/最终结果
                            logger.info("deerflow stream cancelled by user: %s", thread_id)
                            return
                        elif etype == "error":
                            yield _sse({"type": "config_error", "code": "agent_failed",
                                        "message": f"🤖 DeerFlow 智能体执行失败：{evt.get('message', '未知错误')}"})
                            return
                        elif etype == "end":
                            u = evt.get("usage") or {}
                            if isinstance(u, dict):
                                usage = {
                                    "input_tokens": int(u.get("input_tokens") or 0),
                                    "output_tokens": int(u.get("output_tokens") or 0),
                                    "total_tokens": int(u.get("total_tokens") or 0),
                                }
                            break
    except DeerflowUnavailable:
        raise
    except httpx.HTTPError as e:
        logger.warning("deerflow sidecar request failed: %s", e)
        raise DeerflowUnavailable(str(e)) from e

    answer = "".join(answer_parts).strip()

    # 限时探索暂停：智能体通过 ask_clarification 询问用户是否继续。
    # 本轮不下发 final（无答案），前端渲染选择按钮；用户点选后发起新请求（action=continue/stop）续跑。
    if choice_pending is not None and not answer:
        # 暂停前落盘本流已累积的引用，供续跑流 seed（否则续跑后 final citations 为空）
        _store_thread_cites(thread_id, citations)
        yield _sse({
            "type": "choice_pause",
            "question": choice_pending["question"],
            "options": choice_pending["options"],
            "usage": usage,
        })
        return

    follow_ups = await _generate_follow_ups(query, answer, llm_config, agent_config)

    # 仅保留答案中真正引用到的文档：按文档标题/显著子串是否出现在答案中过滤
    # 先落盘（未过滤的全量列表，供续跑周期累积），再过滤出答案真正引用的文档用于展示
    _store_thread_cites(thread_id, citations)
    citations = _filter_cited_citations(answer, citations)

    yield _sse({
        "type": "final",
        "result": {
            "answer": answer or "（未生成回答）",
            "citations": citations,
            "follow_ups": follow_ups,
            "classification": "deerflow2",
            "sufficiency": {},
            "rewritten_query": query,
            "last_query": query,
            "last_answer": answer,
            "usage": usage,
        },
    })
