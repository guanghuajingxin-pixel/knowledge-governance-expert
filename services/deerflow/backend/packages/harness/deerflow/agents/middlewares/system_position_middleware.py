"""System message position normalization middleware.

部分严格的 OpenAI 兼容网关（如某些 vLLM chat template）要求 system 消息只能
以唯一一条出现在消息序列开头，否则返回 400 "System message must be at the
beginning."。而 DeerFlow 的限时探索（检索策略/停止指令）、循环检测等
middleware 会在对话中途通过 before_model/after_model 向 state 追加
SystemMessage——标准 OpenAI API 接受这种序列，严格网关则直接拒绝。

本 middleware 在 model call 出口做规范化：把 request.messages 中的全部
system 消息提取出来，去重后合并进 request.system_message（LangChain factory
会将其作为唯一首条 system 拼接），messages 中不再残留 system。仅影响本次
LLM 请求的消息视图，不改动 agent state 与 checkpointer 中的原始历史。
"""

from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage


class SystemPositionMiddleware(AgentMiddleware):
    """把消息列表中的 system 消息合并为唯一首条，兼容严格 OpenAI 兼容网关。"""

    @staticmethod
    def _apply(request: ModelRequest) -> ModelRequest | None:
        """存在需要搬运的 system 消息时返回规范化后的新 request，否则 None。

        - messages 中的 system 文本（按出现顺序去重）以空行拼接到
          system_message 末尾；system_message 缺失时新建。
        - 合并保留 system_message 原有元数据（id 等）。
        """
        texts: list[str] = []
        others: list = []
        for msg in request.messages:
            if getattr(msg, "type", None) == "system":
                content = getattr(msg, "content", "")
                text = content if isinstance(content, str) else str(content)
                if text.strip():
                    texts.append(text.strip())
            else:
                others.append(msg)
        if not texts:
            return None
        seen: set[str] = set()
        unique = [t for t in texts if not (t in seen or seen.add(t))]
        head = request.system_message
        if head is not None:
            head_text = head.content if isinstance(head.content, str) else str(head.content)
            merged = head_text.rstrip() + "\n\n" + "\n\n".join(unique)
            new_head: SystemMessage = head.model_copy(update={"content": merged})
        else:
            new_head = SystemMessage(content="\n\n".join(unique))
        return request.override(messages=others, system_message=new_head)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        normalized = self._apply(request)
        return handler(normalized if normalized is not None else request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        normalized = self._apply(request)
        return await handler(normalized if normalized is not None else request)
