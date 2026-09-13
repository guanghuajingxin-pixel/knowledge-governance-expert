"""只把主模型、当前运行的最终状态投影为用户答案。"""
import re
from uuid import uuid4

ANSWER_SCOPE = """## 平台最终答复规则
当前问题决定回答对象和范围，历史摘要不能替代当前任务。
仅输出当前问题的结论、必要解释及引用；对照问题优先用表格，不附加未询问的时限、处罚、职责。
不要输出内部摘要、用户当前问题、已完成动作、检索结论、回答注意、node_id 或工具参数。
不添加泛泛的继续追问结尾。引用必须对应正文中的同一对象，尤其不能混用表格中相邻类别的数值。
引用编号 [n] 只能指向本轮 knowledge_search 实际召回的 ref；本轮未检索或检索零召回时，
答案中不得出现任何引用编号，并说明企业知识库未检索到相关原文。
"""

_INTERNAL = re.compile(r"(?m)^\s*(?:[-*#]\s*)*(?:用户当前问题|已完成动作|检索结论|回答注意|建议最终回答口径|已完成检索)\s*[:：]")


def _chunk_text(content) -> str:
    """从流式消息块中提取文本增量（兼容 str 与 content blocks）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and isinstance(b.get("text"), str):
                parts.append(b["text"])
        return "".join(parts)
    return ""


def current_question(message: str, action: str) -> str:
    if action in {"continue", "stop"}:
        return message
    return ("【本轮问题】\n" + message + "\n【作答范围】\n"
            "以本轮问题为任务，历史摘要仅作背景，不继续回答上一轮问题。只回答本轮询问的维度；"
            "不附加未询问的时限、处罚、职责或泛泛追问。答案直接给结论和必要引用，"
            "禁止输出上下文摘要、检索笔记、工具参数或 node_id。")


class AnswerProjection:
    """updates 提供节点来源，values 提供最终正文；主模型答案轮 token 以 ai_text 流式外发。"""

    # 首段缓冲阈值：短于此的过渡语（"让我先检索一下"）不外发
    STREAM_FORWARD_THRESHOLD = 24

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.run_id = str(uuid4())
        self.baseline: set[str] | None = None
        self.model_ids: set[str] = set()
        self.started: set[str] = set()
        self.ended: set[str] = set()
        self.usage_ids: set[str] = set()
        self.usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self.last_messages = []
        self.phases: set[str] = set()
        self.stream_states: dict[str, dict] = {}

    def event(self, kind: str, **data) -> dict:
        return {"type": kind, "thread_id": self.thread_id, "run_id": self.run_id, **data}

    def feed(self, mode: str, chunk: dict) -> list[dict]:
        events = []
        if mode == "messages":
            # 只读取根图 model 节点的来源元数据与 token：答案轮 token 以 ai_text 流式外发，
            # 其余（子图、摘要等内部节点）的 token 一律不投影给用户。
            if not isinstance(chunk, tuple) or len(chunk) != 2:
                return events
            msg, metadata = chunk
            node = metadata.get("langgraph_node")
            namespace = metadata.get("langgraph_checkpoint_ns", "")
            if node == "model" and "|" not in namespace and getattr(msg, "id", None):
                phase = f"model:{msg.id}"
                if phase not in self.phases:
                    self.phases.add(phase)
                    events.append(self.event("phase", phase=phase, status="running"))
                self._emit_stream_events(msg, events)
            return events
        if mode == "updates":
            for node, update in chunk.items():
                if ("SummarizationMiddleware" in node and node not in self.phases
                        and isinstance(update, dict) and update.get("messages")):
                    self.phases.add(node)
                    events.append(self.event("phase", phase="context", status="completed"))
                # 根图 model 的结果包含经过模型中间件处理后的消息。
                # before_model 摘要、子图和未知节点从来不是答案来源。
                if node != "model" or not isinstance(update, dict):
                    continue
                for msg in update.get("messages", []):
                    if getattr(msg, "type", None) != "ai" or not msg.id:
                        continue
                    self.model_ids.add(msg.id)
                    phase = f"model:{msg.id}"
                    if phase in self.phases:
                        events.append(self.event("phase", phase=phase, status="completed",
                                                 has_tools=bool(msg.tool_calls)))
                    if msg.id not in self.usage_ids:
                        self.usage_ids.add(msg.id)
                        usage = getattr(msg, "usage_metadata", None) or {}
                        for key in self.usage:
                            self.usage[key] += usage.get(key, 0) or 0
                    for tc in msg.tool_calls or []:
                        call_id = tc.get("id")
                        if call_id and call_id not in self.started:
                            self.started.add(call_id)
                            events.append(self.event("tool_start", call_id=call_id,
                                                     name=tc.get("name"), args=tc.get("args") or {}))
        elif mode == "values":
            self.last_messages = chunk.get("messages", [])
            if self.baseline is None:
                self.baseline = {m.id for m in self.last_messages if getattr(m, "id", None)}
                return events
            for msg in self.last_messages:
                # A trusted after_model gate can replace the root model's planned tools.
                # Project the replacement ask_clarification without accepting foreign AI messages.
                if getattr(msg, "type", None) == "ai" and msg.id in self.model_ids:
                    for tc in getattr(msg, "tool_calls", []) or []:
                        if tc.get("name") == "ask_clarification" and tc.get("id") not in self.started:
                            self.started.add(tc["id"])
                            events.append(self.event("tool_start", call_id=tc["id"], name=tc["name"], args=tc.get("args") or {}))
                if (getattr(msg, "type", None) == "tool" and msg.id
                        and msg.id not in self.baseline and msg.id not in self.ended):
                    self.ended.add(msg.id)
                    events.append(self.event("tool_end", call_id=msg.tool_call_id, name=msg.name,
                                             content=msg.content, status=getattr(msg, "status", "success")))
        return events

    def _emit_stream_events(self, msg, events: list) -> None:
        """把根图 model 节点的 token 流投影为 ai_text / ai_discard。

        抑制条件（避免把过程文本当答案流出）：
          - 该条消息出现工具调用块 → 整轮不外发；若已外发过则补发 ai_discard 让前端清空；
          - 累积文本命中内部记录特征（与 finish 的拒绝口径一致）→ 整轮不外发。
        首段先缓冲到阈值再外发，过滤"让我先检索一下"之类的短过渡语。
        """
        mid = msg.id
        st = self.stream_states.setdefault(mid, {"forwarded": False, "suppressed": False, "buf": ""})
        if getattr(msg, "tool_call_chunks", None):
            st["suppressed"] = True
            st["buf"] = ""
            if st["forwarded"]:
                st["forwarded"] = False
                events.append(self.event("ai_discard", message_id=mid))
            return
        if st["suppressed"]:
            return
        text = _chunk_text(getattr(msg, "content", ""))
        if not text:
            return
        st["buf"] += text
        if not st["forwarded"]:
            if _INTERNAL.search(st["buf"]):
                st["suppressed"] = True
                st["buf"] = ""
                return
            if len(st["buf"]) >= self.STREAM_FORWARD_THRESHOLD:
                events.append(self.event("ai_text", message_id=mid, text=st["buf"]))
                st["forwarded"] = True
                st["buf"] = ""
        else:
            events.append(self.event("ai_text", message_id=mid, text=text))

    def finish(self, extract_text) -> dict | None:
        # 只能是本次主模型产生且留在最终状态中的最后一条 AI 消息。
        # 工具调用末尾（暂停）不倒退寻找历史答案。
        msg = next((m for m in reversed(self.last_messages) if getattr(m, "type", None) == "ai"), None)
        if msg is None or msg.id not in self.model_ids or msg.id in (self.baseline or set()):
            raise ValueError("本轮未生成可确认的最终答案，请重试")
        if msg.tool_calls:
            if any(tc.get("name") == "ask_clarification" for tc in msg.tool_calls):
                return None
            raise ValueError("检索尚未完成，未生成最终答案")
        text = extract_text(msg.content).strip()
        if not text or _INTERNAL.search(text):
            raise ValueError("本轮回答包含内部记录或为空，未展示该内容，请重试")
        return self.event("answer_final", message_id=msg.id, source_node="model", content=text)
