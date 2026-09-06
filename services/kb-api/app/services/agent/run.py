"""Agent 运行入口。"""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from kb_common.config import get_settings

from .workflow import AgentState, get_graph

logger = logging.getLogger(__name__)

# 节点中文步骤名映射
STEP_LABELS = {
    "classify": ("🔍 问题分类", "正在分析问题类型…"),
    "clarify": ("💡 问题澄清", "正在生成澄清建议…"),
    "refuse": ("🚫 拒答", "判定为无关问题…"),
    "small_talk": ("💬 寒暄应答", "正在直接回应问候…"),
    "rewrite": ("✏️ 问题改写", "正在结合上下文改写问题…"),
    "plan": ("🗂 任务规划", "正在拆解检索与分析计划…"),
    "retrieve": ("📚 知识检索", "正在从 Dify 知识库召回…"),
    "refine_query": ("🔁 反思改写", "资料不足，换个角度重新检索…"),
    "judge_sufficiency": ("⚖️ 充分性判定", "正在判断参考资料是否充分…"),
    "generate_answer": ("✍️ 生成答案", "正在基于参考资料生成回答…"),
    "deep_explore": ("🔬 深度探索", "正在进行深度分析…"),
    "follow_up": ("💡 追问建议", "正在生成你可能想问的问题…"),
    "assign_vars": ("💾 保存上下文", "正在更新会话状态…"),
}


def _config_response(query: str, code: str, message: str) -> dict[str, Any]:
    """配置缺失或 Agent 执行异常时的兜底响应：HTTP 200 + 引导文案，避免前端收到 500。"""
    return {
        "answer": message,
        "citations": [],
        "classification": "",
        "sufficiency": {},
        "rewritten_query": query,
        "last_query": query,
        "last_answer": "",
        "config_error": code,
    }


async def run_agent(
    query: str,
    dataset_ids: list[str] | None = None,
    *,
    last_query: str = "",
    last_answer: str = "",
    history: list[dict[str, str]] | None = None,
    top_k: int = 5,
    deep_think: bool = False,
    llm_config: dict[str, str] | None = None,
    dify_config: dict[str, str] | None = None,
    agent_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行杰克百晓生智能体工作流。

    Args:
        query: 用户原始问题
        dataset_ids: 指定检索的 Dify 数据集 ID 列表；为空时使用配置的默认值
        last_query: 上一轮改写后的问题（会话上下文）
        last_answer: 上一轮回答（会话上下文）
        top_k: 知识库召回条数上限
        llm_config: LLM 配置覆盖 {base_url, api_key, model}
        dify_config: Dify 配置覆盖 {base_url, api_key}

    Returns:
        {"answer": str, "citations": list, "classification": str,
         "sufficiency": dict, "rewritten_query": str,
         "last_query": str, "last_answer": str}
    """
    s = get_settings()
    # 将运行时配置写入 settings 对象（get_settings 为 lru_cache，修改会持久化）
    if dify_config:
        if dify_config.get("base_url"):
            s.dify_base_url = dify_config["base_url"]
        if dify_config.get("api_key"):
            s.dify_api_key = dify_config["api_key"]

    if not dataset_ids:
        default_ids = [d.strip() for d in (s.dify_dataset_ids or "").split(",") if d.strip()]
        dataset_ids = default_ids

    cfg = llm_config or {}
    llm_api_key = (cfg.get("api_key") or s.llm_api_key or "").strip()

    # 预检：未配置 LLM API Key 时直接返回引导文案。
    # 否则 Agent 首个节点构造 ChatOpenAI 会抛 "Missing credentials"，前端只看到笼统的 500。
    if not llm_api_key:
        return _config_response(
            query,
            "llm_not_configured",
            "🤖 智能问答依赖大模型（LLM），但当前尚未配置 LLM API Key。\n\n"
            "请前往「系统配置 → 接入配置」填写 LLM 服务地址、API Key 与模型并保存，然后重新提问。",
        )

    # 召回条数：以智能体配置 top_k 为准；深度思考时自动提升至 ≥10
    base_top_k = int((agent_config or {}).get("top_k") or top_k or 5)
    effective_top_k = max(base_top_k, 10) if deep_think else base_top_k

    state: AgentState = {
        "query": query,
        "rewritten_query": query,
        "dataset_ids": dataset_ids,
        "last_query": last_query,
        "last_answer": last_answer,
        "history": history or [],
        "top_k": effective_top_k,
        "deep_think": deep_think,
        "agent_config": agent_config or {},
        "llm_config": {
            "base_url": cfg.get("base_url") or s.llm_base_url,
            "api_key": llm_api_key,
            "model": cfg.get("model") or s.llm_model,
        },
    }

    try:
        graph = get_graph()
        final = await graph.ainvoke(state)
    except Exception as e:
        logger.warning("agent run failed: %s", e)
        return _config_response(
            query,
            "agent_failed",
            f"🤖 智能问答执行失败（{e.__class__.__name__}）。\n\n"
            "请前往「系统配置 → 接入配置」检查 LLM 与 Dify 配置是否正确，稍后重试。",
        )

    return {
        "answer": final.get("answer", ""),
        "citations": final.get("citations", []),
        "follow_ups": final.get("follow_ups", []),
        "classification": final.get("classification", ""),
        "sufficiency": final.get("sufficiency", {}),
        "plan": final.get("plan", ""),
        "rewritten_query": final.get("rewritten_query", ""),
        "last_query": final.get("last_query", ""),
        "last_answer": final.get("last_answer", ""),
    }


async def run_agent_stream(
    query: str,
    dataset_ids: list[str] | None = None,
    *,
    last_query: str = "",
    last_answer: str = "",
    history: list[dict[str, str]] | None = None,
    top_k: int = 5,
    deep_think: bool = False,
    llm_config: dict[str, str] | None = None,
    dify_config: dict[str, str] | None = None,
    agent_config: dict[str, Any] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """流式执行智能体工作流，逐节点 yield 步骤进度事件。

    yield 的事件类型：
      {"type": "step", "node": str, "title": str, "detail": str, "data": dict}
      {"type": "final", "result": dict}
      {"type": "config_error", "code": str, "message": str}
    """
    s = get_settings()
    if dify_config:
        if dify_config.get("base_url"):
            s.dify_base_url = dify_config["base_url"]
        if dify_config.get("api_key"):
            s.dify_api_key = dify_config["api_key"]

    if not dataset_ids:
        default_ids = [d.strip() for d in (s.dify_dataset_ids or "").split(",") if d.strip()]
        dataset_ids = default_ids

    cfg = llm_config or {}
    llm_api_key = (cfg.get("api_key") or s.llm_api_key or "").strip()

    if not llm_api_key:
        yield {
            "type": "config_error",
            "code": "llm_not_configured",
            "message": (
                "🤖 智能问答依赖大模型（LLM），但当前尚未配置 LLM API Key。\n\n"
                "请前往「系统配置 → 接入配置」填写 LLM 服务地址、API Key 与模型并保存，然后重新提问。"
            ),
        }
        return

    # 召回条数：以智能体配置 top_k 为准；深度思考时自动提升至 ≥10
    base_top_k = int((agent_config or {}).get("top_k") or top_k or 5)
    effective_top_k = max(base_top_k, 10) if deep_think else base_top_k

    state: AgentState = {
        "query": query,
        "rewritten_query": query,
        "dataset_ids": dataset_ids,
        "last_query": last_query,
        "last_answer": last_answer,
        "history": history or [],
        "top_k": effective_top_k,
        "deep_think": deep_think,
        "agent_config": agent_config or {},
        "llm_config": {
            "base_url": cfg.get("base_url") or s.llm_base_url,
            "api_key": llm_api_key,
            "model": cfg.get("model") or s.llm_model,
        },
    }

    try:
        graph = get_graph()
        final_state: dict[str, Any] = dict(state)
        async for chunk in graph.astream(state, stream_mode="updates"):
            # chunk 形如 {"classify": {更新字段...}}
            for node_name, update in chunk.items():
                # plan 节点在非复杂问题下跳过（空更新），不展示该步骤
                if node_name == "plan" and not (update or {}).get("plan"):
                    if isinstance(update, dict):
                        final_state.update(update)
                    continue
                title, detail = STEP_LABELS.get(node_name, (node_name, "处理中…"))
                # 提取该节点的关键中间结果
                snippet = _extract_step_data(node_name, update)
                # 用中间结果丰富步骤详情
                if node_name == "plan" and snippet.get("plan"):
                    detail = "已拆解为 " + str(snippet["plan"].count("\n") + 1) + " 个子任务"
                elif node_name == "retrieve":
                    rounds = (update or {}).get("retrieval_round")
                    hit = snippet.get("hit_count", 0)
                    detail = f"第 {rounds} 轮检索 · 累计召回 {hit} 段" if rounds else f"召回 {hit} 段"
                elif node_name == "follow_up":
                    n = len(snippet.get("follow_ups") or [])
                    detail = f"已生成 {n} 个追问建议" if n else "未生成追问"
                yield {
                    "type": "step",
                    "node": node_name,
                    "title": title,
                    "detail": detail,
                    "data": snippet,
                }
                # 合并到最终状态
                if isinstance(update, dict):
                    final_state.update(update)
    except Exception as e:
        logger.warning("agent stream failed: %s", e)
        yield {
            "type": "config_error",
            "code": "agent_failed",
            "message": (
                f"🤖 智能问答执行失败（{e.__class__.__name__}）。\n\n"
                "请前往「系统配置 → 接入配置」检查 LLM 与 Dify 配置是否正确，稍后重试。"
            ),
        }
        return

    yield {
        "type": "final",
        "result": {
            "answer": final_state.get("answer", ""),
            "citations": final_state.get("citations", []),
            "follow_ups": final_state.get("follow_ups", []),
            "classification": final_state.get("classification", ""),
            "sufficiency": final_state.get("sufficiency", {}),
            "plan": final_state.get("plan", ""),
            "rewritten_query": final_state.get("rewritten_query", ""),
            "last_query": final_state.get("last_query", ""),
            "last_answer": final_state.get("last_answer", ""),
        },
    }


def _extract_step_data(node: str, update: dict[str, Any] | None) -> dict[str, Any]:
    """从节点输出中提取用于前端展示的中间结果。"""
    if not update:
        return {}
    if node == "classify":
        return {"classification": update.get("classification", "")}
    if node in ("rewrite", "refine_query"):
        return {"rewritten_query": update.get("rewritten_query", "")}
    if node == "retrieve":
        results = update.get("retrieval_results") or []
        return {"hit_count": len(results), "retrieval_round": update.get("retrieval_round", 1)}
    if node == "judge_sufficiency":
        return update.get("sufficiency", {})
    if node == "plan":
        return {"plan": update.get("plan", "")}
    if node == "follow_up":
        return {"follow_ups": update.get("follow_ups", [])}
    if node in ("clarify", "refuse", "small_talk", "generate_answer", "deep_explore"):
        return {"answer_preview": (update.get("answer") or "")[:120]}
    return {}
