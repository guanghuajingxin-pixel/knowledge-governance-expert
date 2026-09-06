"""杰克百晓生智能体配置 —— 以 JSON 存储于 settings 表（key=agent_config）。

参考 DeerFlow（规划 → 检索 → 反思 → 报告）与平台智能体配置项，
将知识库调用策略、任务规划、长期记忆、追问建议、生成超参等全部配置化。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.models import Setting

CONFIG_KEY = "agent_config"

# 智能问答可绑定工具目录（key 与 DeerFlow sidecar 工具注册名一致）
TOOL_CATALOG: list[dict[str, str]] = [
    {"key": "knowledge_search", "name": "知识库检索",
     "desc": "检索企业知识库（Dify 数据集），答案的主要来源"},
    {"key": "dingtalk_search", "name": "钉钉知识库检索",
     "desc": "检索钉钉文档/知识库中同步的企业资料"},
    {"key": "dingtalk_read_doc", "name": "钉钉文档读取",
     "desc": "读取钉钉文档正文，用于引用原文与来源"},
    {"key": "ask_clarification", "name": "澄清提问",
     "desc": "用户问题模糊时主动反问，确认意图后再作答"},
    {"key": "present_files", "name": "文件展示",
     "desc": "在回答中以卡片形式展示关联文件/附件"},
]

DEFAULT_CONFIG: dict[str, Any] = {
    # —— 基础设置 ——
    "agent_name": "杰克百晓生",
    "models": [],                 # 参与调度的模型名列表（最多 10）；为空则用系统配置的 llm_model
    "retrieval_mode": "smart",    # smart=智能调用（闲聊/问候不检索）；force=强制调用（每问必检索）
    "greeting_enabled": True,     # 对话开场白
    "greeting": "你好！我是杰克百晓生，公司知识问答助手。\n我可以帮你查询产品技术文档、流程制度、审批规则等。试试下面的问题，或直接输入你想了解的内容：",
    "suggested_questions": [      # 开场白下的推荐问题
        "安全标识管理制度包含哪些内容？",
        "设备保养流程怎么走？",
        "差旅报销需要哪些审批角色？",
    ],
    "follow_up_enabled": True,    # 下一步问题建议（回答后生成 3 个追问）
    # —— 工具开关（key=DeerFlow 工具名；False=该工具不绑定给智能体）——
    "tools_enabled": {
        "knowledge_search": True,   # 知识库检索（Dify 数据集，答案主要来源）
        "dingtalk_search": True,    # 钉钉知识库检索
        "dingtalk_read_doc": True,  # 钉钉文档正文读取
        "ask_clarification": True,  # 澄清提问（问题模糊时主动反问）
        "present_files": True,      # 文件/附件展示
    },
    # —— 高级设置 ——
    "planning_enabled": True,     # 任务规划（TodoList 中间件，复杂问题先拆解计划）
    "subagent_enabled": False,    # 子智能体协作（Lead Agent 按需并行派发 Sub-Agent 调研）
    "long_memory_enabled": True,  # 长期记忆（跨会话记忆 + 同会话 thread 上下文持久化）
    "deep_think_default": False,  # 新会话默认开启深度思考
    # —— 超参维护 ——
    "temperature": 0.7,           # 生成温度
    "top_p": 0.9,                 # top-p 采样
    "max_tokens": 2048,           # 单次回答最大 token
    "top_k": 5,                   # 知识库召回条数（深度思考时自动提升至 ≥10）
    "max_retrieval_rounds": 2,    # 检索反思轮数（不充分时改写查询重检，DeerFlow Researcher 反思循环）
}

# 数值字段的合法区间（保存时钳制）
_NUM_BOUNDS = {
    "temperature": (0.0, 2.0),
    "top_p": (0.1, 1.0),
    "max_tokens": (256, 8192),
    "top_k": (1, 20),
    "max_retrieval_rounds": (1, 4),
}


def _clamp(key: str, val: Any) -> Any:
    if key not in _NUM_BOUNDS:
        return val
    try:
        lo, hi = _NUM_BOUNDS[key]
        v = float(val)
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return DEFAULT_CONFIG[key]


async def load_agent_config(session: AsyncSession) -> dict[str, Any]:
    """读取智能体配置；无记录或解析失败时返回默认值。"""
    row = (await session.execute(select(Setting).where(Setting.key == CONFIG_KEY))).scalar_one_or_none()
    if not row or not row.value:
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(row.value)
        if not isinstance(data, dict):
            return dict(DEFAULT_CONFIG)
    except (json.JSONDecodeError, TypeError):
        return dict(DEFAULT_CONFIG)
    out = dict(DEFAULT_CONFIG)
    for k in DEFAULT_CONFIG:
        if k in data:
            out[k] = _clamp(k, data[k])
    # 枚举/列表兜底
    if out.get("retrieval_mode") not in ("smart", "force"):
        out["retrieval_mode"] = "smart"
    out["models"] = [str(m).strip() for m in (out.get("models") or []) if str(m).strip()][:10]
    out["suggested_questions"] = [str(q).strip() for q in (out.get("suggested_questions") or []) if str(q).strip()][:6]
    out["tools_enabled"] = _normalize_tools(data.get("tools_enabled"))
    return out


def _normalize_tools(raw: Any) -> dict[str, bool]:
    """工具开关白名单：未知 key 忽略，缺失 key 默认启用。"""
    base = {t["key"]: True for t in TOOL_CATALOG}
    if isinstance(raw, dict):
        for k in base:
            if k in raw:
                base[k] = bool(raw[k])
    return base


async def save_agent_config(session: AsyncSession, cfg: dict[str, Any]) -> dict[str, Any]:
    """保存（白名单字段 + 钳制），返回落库后的完整配置。"""
    data = dict(DEFAULT_CONFIG)
    for k in DEFAULT_CONFIG:
        if k in cfg:
            data[k] = _clamp(k, cfg[k])
    if data.get("retrieval_mode") not in ("smart", "force"):
        data["retrieval_mode"] = "smart"
    data["models"] = [str(m).strip() for m in (data.get("models") or []) if str(m).strip()][:10]
    data["suggested_questions"] = [str(q).strip() for q in (data.get("suggested_questions") or []) if str(q).strip()][:6]
    data["tools_enabled"] = _normalize_tools(cfg.get("tools_enabled"))
    for bool_key in ("greeting_enabled", "follow_up_enabled", "planning_enabled",
                     "subagent_enabled", "long_memory_enabled", "deep_think_default"):
        data[bool_key] = bool(data.get(bool_key))
    data["agent_name"] = str(data.get("agent_name") or DEFAULT_CONFIG["agent_name"]).strip()[:20]
    data["greeting"] = str(data.get("greeting") or "").strip()[:1000]

    row = (await session.execute(select(Setting).where(Setting.key == CONFIG_KEY))).scalar_one_or_none()
    payload = json.dumps(data, ensure_ascii=False)
    if row:
        row.value = payload
    else:
        session.add(Setting(key=CONFIG_KEY, value=payload, is_secret=False))
    await session.commit()
    return data
