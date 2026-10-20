"""SystemPositionMiddleware 单元测试。

背景：严格 OpenAI 兼容网关（部分 vLLM chat template）要求 system 消息
只能以唯一一条出现在序列开头；DeerFlow 限时探索等 middleware 会在对话
中途追加 SystemMessage，规范化必须把这些消息合并进 system_message 并
从 messages 中移除。
"""

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from deerflow.agents.middlewares.system_position_middleware import (
    SystemPositionMiddleware,
)


class _Recorder:
    """记录 handler 收到的 request，模拟 model call。"""

    def __init__(self):
        self.request: ModelRequest | None = None

    def __call__(self, request: ModelRequest):
        self.request = request
        from langchain.agents.middleware.types import ModelResponse

        return ModelResponse(result=[AIMessage(content="ok")])


def _request(messages, system_prompt=None):
    return ModelRequest(
        model=object(),
        messages=messages,
        system_message=SystemMessage(content=system_prompt) if system_prompt else None,
    )


def test_merges_midway_system_into_head():
    """中途 system（限时探索策略注入场景）合并进 system_message 末尾。"""
    rec = _Recorder()
    req = _request(
        [HumanMessage(content="问题"), SystemMessage(content="【本轮检索策略】先检索")],
        system_prompt="主提示词",
    )
    SystemPositionMiddleware().wrap_model_call(req, rec)
    out = rec.request
    # messages 中不再有 system
    assert [m.type for m in out.messages] == ["human"]
    merged = out.system_message.content
    assert merged.startswith("主提示词")
    assert "【本轮检索策略】先检索" in merged


def test_creates_head_when_missing():
    """无 system_message 时新建首位 system 承载全部指令。"""
    rec = _Recorder()
    req = _request([HumanMessage(content="hi"), SystemMessage(content="指令")])
    SystemPositionMiddleware().wrap_model_call(req, rec)
    out = rec.request
    assert out.system_message is not None
    assert out.system_message.content == "指令"
    assert [m.type for m in out.messages] == ["human"]


def test_multiple_systems_deduped_and_tools_kept():
    """多条中途 system 去重合并；工具消息等非 system 消息原样保留。"""
    rec = _Recorder()
    strategy = "【本轮检索策略】先检索"
    req = _request(
        [
            HumanMessage(content="Q"),
            AIMessage(content="", tool_calls=[{"name": "knowledge_search",
                                               "args": {}, "id": "c1", "type": "tool_call"}]),
            ToolMessage(content="R", tool_call_id="c1"),
            SystemMessage(content=strategy),
            SystemMessage(content=strategy),  # 历史轮次遗留的相同文本
            SystemMessage(content="停止指令"),
        ],
        system_prompt="S",
    )
    SystemPositionMiddleware().wrap_model_call(req, rec)
    out = rec.request
    assert [m.type for m in out.messages] == ["human", "ai", "tool"]
    content = out.system_message.content
    assert content.count(strategy) == 1, "相同指令文本应去重"
    assert "停止指令" in content


def test_noop_without_midway_system():
    """无中途 system 时 request 原样透传（不 override）。"""
    rec = _Recorder()
    req = _request([HumanMessage(content="Q")], system_prompt="S")
    SystemPositionMiddleware().wrap_model_call(req, rec)
    assert rec.request is req


def test_head_system_metadata_preserved():
    """合并保留原 system_message 的元数据（id 等）。"""
    rec = _Recorder()
    head = SystemMessage(content="主提示词", id="head-1")
    req = ModelRequest(
        model=object(),
        messages=[HumanMessage(content="Q"), SystemMessage(content="指令")],
        system_message=head,
    )
    SystemPositionMiddleware().wrap_model_call(req, rec)
    assert rec.request.system_message.id == "head-1"
    assert "指令" in rec.request.system_message.content


@pytest.mark.anyio
async def test_async_path():
    """awrap_model_call 与同步路径行为一致。"""

    class _AsyncRecorder(_Recorder):
        async def __call__(self, request: ModelRequest):
            return _Recorder.__call__(self, request)

    rec = _AsyncRecorder()
    req = _request([HumanMessage(content="Q"), SystemMessage(content="指令")],
                   system_prompt="S")
    await SystemPositionMiddleware().awrap_model_call(req, rec)
    assert [m.type for m in rec.request.messages] == ["human"]
    assert "指令" in rec.request.system_message.content
