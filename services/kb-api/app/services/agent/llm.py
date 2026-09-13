"""问答链共享的 LLM 构造与追问建议提示词。

旧 LangGraph 工作流（workflow.py）废弃后，DeerFlow 链路的追问建议生成
仍需要一个按智能体配置构造 ChatOpenAI 的入口与追问提示词，收敛在本模块。
"""
from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from kb_common.config import get_settings

# ============ 下一步问题建议 ============
FOLLOW_UP_SYSTEM = """你是问答助手。用户刚完成一轮提问，请基于用户的问题和本次回答，生成 3 个用户可能继续追问的相关问题。

规则：
1. 问题必须与本次主题相关、具体可答、符合公司知识库场景（流程步骤、参数、例外情况、关联制度等）。
2. 每行一个问题，用「1. 2. 3.」编号，每个问题以问号结尾，不超过 40 字。
3. 不要重复本次已问过的问题，不要输出与业务无关的寒暄。"""


def build_llm(llm_cfg: dict[str, str], agent_cfg: dict[str, Any] | None = None,
              temperature: float | None = None) -> ChatOpenAI:
    """按系统配置 + 智能体超参构造 ChatOpenAI；temperature 显式传入时优先。"""
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
