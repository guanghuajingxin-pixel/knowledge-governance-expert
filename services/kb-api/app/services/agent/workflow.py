"""杰克百晓生智能体 —— 基于 LangGraph，借鉴 DeerFlow 的 Planner/Researcher/Reporter 架构。

工作流节点：
  START → 问题分类器
    ├─ 模糊问题 → 问题澄清 → END
    ├─ 无关问题 → 拒答 → END
    ├─ 闲聊问候（智能调用模式）→ 寒暄直答 → 追问建议 → END
    └─ 清晰/复杂（强制模式下闲聊同样走检索）
          → 问题改写 → 任务规划（复杂/深度思考时）→ 知识检索
                ├─ 有召回 → 充分性判定
                │     ├─ sufficient → 生成答案（Reporter）
                │     └─ 不足且未超轮数 → 查询反思改写 → 回到检索（Researcher 反思循环）
                │     └─ 不足且超轮数 → 深度探索
                └─ 无召回且未超轮数 → 查询反思改写 → 回到检索
                └─ 无召回且超轮数 → 深度探索
          → 追问建议（可选）→ 保存上下文 → END
"""
from __future__ import annotations

import logging
import re
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from kb_common.clients import dify_client
from kb_common.config import get_settings

from . import prompts

logger = logging.getLogger(__name__)

# 问题分类标签
CLS_VAGUE = "模糊问题"
CLS_CLEAR = "清晰问题"
CLS_COMPLEX = "复杂探索"
CLS_IRRELEVANT = "无关问题"
CLS_CHITCHAT = "闲聊问候"

CLASS_LABELS = {CLS_VAGUE, CLS_CLEAR, CLS_COMPLEX, CLS_IRRELEVANT, CLS_CHITCHAT}


class AgentState(TypedDict, total=False):
    query: str
    rewritten_query: str
    classification: str
    retrieval_results: list[dict[str, Any]]
    sufficiency: dict[str, Any]
    answer: str
    citations: list[dict[str, Any]]
    follow_ups: list[str]
    plan: str
    retrieval_round: int
    last_query: str
    last_answer: str
    history: list[dict[str, str]]   # 多轮记忆 [{"role": "user"/"assistant", "content": ...}]
    dataset_ids: list[str]
    llm_config: dict[str, str]
    agent_config: dict[str, Any]
    top_k: int
    deep_think: bool


class SufficiencyOutput(BaseModel):
    sufficient: bool = Field(description="参考资料是否足以完整回答用户问题")
    missing: str = Field(default="", description="若不充分，缺失了什么信息；充分则填空字符串")


def _build_llm(llm_cfg: dict[str, str], agent_cfg: dict[str, Any] | None = None,
               temperature: float | None = None) -> ChatOpenAI:
    s = get_settings()
    ac = agent_cfg or {}
    kwargs: dict[str, Any] = dict(
        model=llm_cfg.get("model") or s.llm_model,
        base_url=llm_cfg.get("base_url") or s.llm_base_url,
        api_key=llm_cfg.get("api_key") or s.llm_api_key,
        temperature=float(ac.get("temperature", 0.7)) if temperature is None else temperature,
    )
    top_p = ac.get("top_p")
    max_tokens = ac.get("max_tokens")
    if top_p:
        kwargs["top_p"] = float(top_p)
    if max_tokens:
        kwargs["max_tokens"] = int(max_tokens)
    return ChatOpenAI(**kwargs)


def _history_text(state: AgentState, limit: int = 6) -> str:
    """把多轮记忆格式化为上下文文本；无记忆时回退到上一轮问答。"""
    history = state.get("history") or []
    if history:
        lines = []
        for turn in history[-limit:]:
            role = "用户" if turn.get("role") == "user" else "助手"
            lines.append(f"{role}：{turn.get('content', '')}")
        return "\n".join(lines)
    lq, la = state.get("last_query", ""), state.get("last_answer", "")
    if lq or la:
        return f"用户：{lq}\n助手：{la}"
    return "（无会话上文）"


# ---------- 节点实现 ----------

async def classify_node(state: AgentState) -> AgentState:
    """问题分类器：模糊/清晰/复杂探索/无关/闲聊问候。"""
    llm = _build_llm(state["llm_config"], state.get("agent_config"), temperature=0.1)
    msgs = [
        SystemMessage(content=prompts.CLASSIFIER_SYSTEM),
        HumanMessage(content=state["query"]),
    ]
    try:
        resp = await llm.ainvoke(msgs)
        label = (resp.content or "").strip()
        for c in CLASS_LABELS:
            if c in label:
                label = c
                break
        else:
            label = CLS_CLEAR
    except Exception as e:
        logger.warning("classify failed: %s", e)
        label = CLS_CLEAR
    state["classification"] = label
    return state


def route_after_classify(state: AgentState) -> str:
    c = state.get("classification", CLS_CLEAR)
    mode = (state.get("agent_config") or {}).get("retrieval_mode", "smart")
    if c == CLS_VAGUE:
        return "clarify"
    if c == CLS_IRRELEVANT:
        return "refuse"
    # 智能调用：闲聊问候直接回答不检索；强制调用：所有问题都走知识库
    if c == CLS_CHITCHAT and mode != "force":
        return "small_talk"
    return "rewrite"


async def clarify_node(state: AgentState) -> AgentState:
    """问题澄清：针对模糊问题给出候选问题。"""
    llm = _build_llm(state["llm_config"], state.get("agent_config"), temperature=0.3)
    ctx = _history_text(state)
    msgs = [
        SystemMessage(content=prompts.CLARIFY_SYSTEM),
        HumanMessage(content=f"用户问题：{state['query']}\n\n会话上文：\n{ctx}"),
    ]
    try:
        resp = await llm.ainvoke(msgs)
        state["answer"] = resp.content or ""
    except Exception as e:
        logger.warning("clarify failed: %s", e)
        state["answer"] = "您的问题我需要确认一下具体方向，能否补充更多细节？"
    state["citations"] = []
    return state


async def refuse_node(state: AgentState) -> AgentState:
    state["answer"] = prompts.IRRELEVANT_ANSWER
    state["citations"] = []
    return state


async def small_talk_node(state: AgentState) -> AgentState:
    """寒暄直答：问候/感谢/身份类问题直接回答，不检索知识库。"""
    llm = _build_llm(state["llm_config"], state.get("agent_config"), temperature=0.6)
    cfg = state.get("agent_config") or {}
    name = cfg.get("agent_name", "杰克百晓生")
    msgs = [
        SystemMessage(content=prompts.SMALL_TALK_SYSTEM.format(agent_name=name)),
        HumanMessage(content=state["query"]),
    ]
    try:
        resp = await llm.ainvoke(msgs)
        state["answer"] = resp.content or ""
    except Exception as e:
        logger.warning("small talk failed: %s", e)
        state["answer"] = "你好！我是杰克百晓生，有产品、流程制度方面的问题都可以问我。"
    state["citations"] = []
    return state


async def rewrite_node(state: AgentState) -> AgentState:
    """问题改写器：结合多轮上下文改写成独立完整的检索问题。"""
    llm = _build_llm(state["llm_config"], state.get("agent_config"), temperature=0.1)
    user_msg = prompts.REWRITE_USER_TMPL.format(
        query=state["query"],
        history=_history_text(state),
    )
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=prompts.REWRITE_SYSTEM),
            HumanMessage(content=user_msg),
        ])
        state["rewritten_query"] = (resp.content or state["query"]).strip()
    except Exception as e:
        logger.warning("rewrite failed: %s", e)
        state["rewritten_query"] = state["query"]
    return state


async def plan_node(state: AgentState) -> AgentState:
    """任务规划（DeerFlow Planner）：复杂问题或深度思考时，先拆解子任务计划。

    非复杂问题直接跳过（返回空更新，流式层不展示该步骤）。
    """
    cfg = state.get("agent_config") or {}
    enabled = cfg.get("planning_enabled", True)
    complex_q = state.get("classification") == CLS_COMPLEX
    deep = state.get("deep_think", False)
    if not (enabled and (complex_q or deep)):
        return {}
    llm = _build_llm(state["llm_config"], cfg, temperature=0.3)
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=prompts.PLANNER_SYSTEM),
            HumanMessage(content=f"用户问题：{state.get('rewritten_query') or state['query']}"),
        ])
        state["plan"] = (resp.content or "").strip()
    except Exception as e:
        logger.warning("plan failed: %s", e)
        state["plan"] = ""
    return state


async def retrieve_node(state: AgentState) -> AgentState:
    """知识检索（DeerFlow Researcher）：调用 Dify 知识库，支持多轮累积召回。"""
    state["retrieval_round"] = state.get("retrieval_round", 0) + 1
    dataset_ids = state.get("dataset_ids") or []
    query = state.get("rewritten_query") or state["query"]
    top_k = state.get("top_k", 5)
    try:
        results = await dify_client.retrieve(dataset_ids, query, top_k=top_k)
    except Exception as e:
        logger.warning("dify retrieve failed: %s", e)
        results = []
    # 多轮检索：累积并按段落内容去重
    merged = state.get("retrieval_results") or []
    seen_content = {(r.get("content") or "")[:80] for r in merged}
    for r in results:
        sig = (r.get("content") or "")[:80]
        if sig and sig in seen_content:
            continue
        if sig:
            seen_content.add(sig)
        merged.append(r)
    state["retrieval_results"] = merged
    # 引用来源按文档去重：同一文档只保留一条，避免同一文档多段落刷屏
    seen_doc: set[str] = set()
    cites: list[dict[str, Any]] = []
    for r in merged:
        key = r.get("document_id") or r.get("document_title") or ""
        if key and key in seen_doc:
            continue
        if key:
            seen_doc.add(key)
        cites.append(r)
    state["citations"] = cites
    return state


async def refine_query_node(state: AgentState) -> AgentState:
    """查询反思改写（Researcher 反思循环）：资料不足时换个角度改写查询，准备重检。"""
    llm = _build_llm(state["llm_config"], state.get("agent_config"), temperature=0.4)
    missing = (state.get("sufficiency") or {}).get("missing", "")
    prev = state.get("rewritten_query") or state["query"]
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=prompts.REFINE_SYSTEM),
            HumanMessage(content=(
                f"原始问题：{state['query']}\n"
                f"上一轮检索问题：{prev}\n"
                f"资料缺口：{missing or '（检索无召回）'}\n\n"
                "请输出换角度后的新检索问题，只输出问题本身。"
            )),
        ])
        refined = (resp.content or "").strip()
        if refined:
            state["rewritten_query"] = refined
    except Exception as e:
        logger.warning("refine query failed: %s", e)
    state["sufficiency"] = {}  # 重置判定，进入下一轮
    return state


def _max_rounds(state: AgentState) -> int:
    return max(1, int((state.get("agent_config") or {}).get("max_retrieval_rounds", 2) or 2))


def route_after_retrieve(state: AgentState) -> str:
    results = state.get("retrieval_results") or []
    rounds = state.get("retrieval_round", 0)
    if results:
        return "judge_sufficiency"
    if rounds < _max_rounds(state):
        return "refine_query"
    return "deep_explore"


async def judge_sufficiency_node(state: AgentState) -> AgentState:
    """充分性判定：结构化输出 sufficient / missing。"""
    llm = _build_llm(state["llm_config"], state.get("agent_config"), temperature=0.1)
    structured = llm.with_structured_output(SufficiencyOutput)
    ctx = _format_context(state.get("retrieval_results") or [])
    msgs = [
        SystemMessage(content=prompts.SUFFICIENCY_SYSTEM),
        HumanMessage(content=f"用户问题：{state.get('rewritten_query') or state['query']}\n\n参考资料：\n{ctx}"),
    ]
    try:
        out: SufficiencyOutput = await structured.ainvoke(msgs)
        state["sufficiency"] = {"sufficient": out.sufficient, "missing": out.missing}
    except Exception as e:
        logger.warning("sufficiency judge failed: %s", e)
        state["sufficiency"] = {"sufficient": True, "missing": ""}
    return state


def route_after_sufficiency(state: AgentState) -> str:
    suf = state.get("sufficiency") or {}
    rounds = state.get("retrieval_round", 0)
    if suf.get("sufficient"):
        return "generate_answer"
    if rounds < _max_rounds(state):
        return "refine_query"
    return "deep_explore"


async def generate_answer_node(state: AgentState) -> AgentState:
    """生成答案（DeerFlow Reporter）：基于参考资料 + 多轮上下文回答。"""
    cfg = state.get("agent_config") or {}
    deep = state.get("deep_think", False)
    temp = 0.8 if deep else None
    llm = _build_llm(state["llm_config"], cfg, temperature=temp)
    ctx = _format_context(state.get("retrieval_results") or [])
    system_prompt = prompts.ANSWER_SYSTEM
    if deep:
        system_prompt += (
            "\n\n【深度思考模式】请进行更深入、多步的分析：先拆解问题要点，"
            "再逐一结合参考资料给出依据，必要时做合理的归纳与延伸，"
            "最后给出结构清晰、论证充分的详尽回答；仍须严格基于参考资料并标注引用。"
        )
    history = _history_text(state)
    msgs = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=(
            f"参考资料：\n{ctx}\n\n"
            f"会话上文：\n{history}\n\n"
            f"用户问题：{state.get('rewritten_query') or state['query']}"
        )),
    ]
    try:
        resp = await llm.ainvoke(msgs)
        state["answer"] = resp.content or ""
    except Exception as e:
        logger.warning("generate answer failed: %s", e)
        state["answer"] = "知识库中暂无完整依据，无法回答该问题。"
    return state


async def deep_explore_node(state: AgentState) -> AgentState:
    """深度探索：多轮检索仍不足时的综合分析。"""
    llm = _build_llm(state["llm_config"], state.get("agent_config"), temperature=0.8)
    results = state.get("retrieval_results") or []
    ctx = _format_context(results) if results else "（知识库无相关召回）"
    missing = (state.get("sufficiency") or {}).get("missing", "")
    msgs = [
        SystemMessage(content=prompts.DEEP_EXPLORE_SYSTEM),
        HumanMessage(content=(
            f"用户问题：{state.get('rewritten_query') or state['query']}\n\n"
            f"参考资料：\n{ctx}\n\n"
            f"知识缺口：{missing}"
        )),
    ]
    try:
        resp = await llm.ainvoke(msgs)
        state["answer"] = resp.content or ""
    except Exception as e:
        logger.warning("deep explore failed: %s", e)
        state["answer"] = "知识库中暂无完整依据，无法回答该问题。建议补充相关知识后再试。"
    return state


async def follow_up_node(state: AgentState) -> AgentState:
    """下一步问题建议：回答完成后生成 3 个用户可能继续追问的问题。"""
    cfg = state.get("agent_config") or {}
    if not cfg.get("follow_up_enabled", True):
        return {}
    llm = _build_llm(state["llm_config"], cfg, temperature=0.7)
    answer = state.get("answer", "")
    if not answer:
        return {}
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=prompts.FOLLOW_UP_SYSTEM),
            HumanMessage(content=(
                f"用户问题：{state.get('rewritten_query') or state['query']}\n"
                f"本次回答：\n{answer[:1500]}"
            )),
        ])
        questions = re.findall(r"(?:^|\n)\s*(?:\d+[.、)]\s*)?(.{6,60}[？?])", resp.content or "")
        state["follow_ups"] = [q.strip() for q in questions[:3]]
    except Exception as e:
        logger.warning("follow up failed: %s", e)
        state["follow_ups"] = []
    return state


def route_after_answer(state: AgentState) -> str:
    cfg = state.get("agent_config") or {}
    return "follow_up" if cfg.get("follow_up_enabled", True) else "assign_vars"


async def assign_vars_node(state: AgentState) -> AgentState:
    """变量赋值：更新会话上下文（last_query / last_answer）。"""
    state["last_query"] = state.get("rewritten_query") or state["query"]
    state["last_answer"] = state.get("answer", "")
    return state


# ---------- 工具函数 ----------

def _format_context(results: list[dict[str, Any]]) -> str:
    if not results:
        return "（无相关资料）"
    parts = []
    for i, r in enumerate(results, 1):
        title = r.get("document_title") or "未知文档"
        parts.append(f"[{i}] ({title})\n{r.get('content', '')}")
    return "\n\n".join(parts)


# ---------- 构建图 ----------

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("classify", classify_node)
    g.add_node("clarify", clarify_node)
    g.add_node("refuse", refuse_node)
    g.add_node("small_talk", small_talk_node)
    g.add_node("rewrite", rewrite_node)
    g.add_node("plan", plan_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("refine_query", refine_query_node)
    g.add_node("judge_sufficiency", judge_sufficiency_node)
    g.add_node("generate_answer", generate_answer_node)
    g.add_node("deep_explore", deep_explore_node)
    g.add_node("follow_up", follow_up_node)
    g.add_node("assign_vars", assign_vars_node)

    g.set_entry_point("classify")
    g.add_conditional_edges(
        "classify",
        route_after_classify,
        {"clarify": "clarify", "refuse": "refuse",
         "small_talk": "small_talk", "rewrite": "rewrite"},
    )
    g.add_edge("clarify", END)
    g.add_edge("refuse", END)
    # 寒暄直答后同样可给追问建议（引导到业务问题）
    g.add_conditional_edges(
        "small_talk",
        route_after_answer,
        {"follow_up": "follow_up", "assign_vars": "assign_vars"},
    )
    g.add_edge("rewrite", "plan")
    g.add_edge("plan", "retrieve")
    g.add_conditional_edges(
        "retrieve",
        route_after_retrieve,
        {"refine_query": "refine_query", "judge_sufficiency": "judge_sufficiency",
         "deep_explore": "deep_explore"},
    )
    g.add_edge("refine_query", "retrieve")  # 反思循环：改写后重新检索
    g.add_conditional_edges(
        "judge_sufficiency",
        route_after_sufficiency,
        {"generate_answer": "generate_answer", "refine_query": "refine_query",
         "deep_explore": "deep_explore"},
    )
    g.add_conditional_edges(
        "generate_answer",
        route_after_answer,
        {"follow_up": "follow_up", "assign_vars": "assign_vars"},
    )
    g.add_conditional_edges(
        "deep_explore",
        route_after_answer,
        {"follow_up": "follow_up", "assign_vars": "assign_vars"},
    )
    g.add_edge("follow_up", "assign_vars")
    g.add_edge("assign_vars", END)
    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
