"""限时探索中间件：检索超时主动询问用户是否继续，到达硬上限强制收尾。

交互节奏（探索计时从用户明确同意钉钉探索起计，等待选择不计时）：
  0. 先检索企业知识库；证据不足时总结内容并评分，暂停等待是否探索钉钉的选择。
  1. 检索满 1 分钟仍未形成答案 → 由 wrap_model_call 直接合成一次
     ask_clarification 工具调用（ClarificationMiddleware 会拦截它并暂停
     运行），通过选择按钮问用户「继续探索 / 先这样回答」；
  2. 用户选择继续后，再检索满 5 分钟仍无答案 → 再次询问；
  3. 总时长满 10 分钟 → wrap_model_call 直接合成最终答复消息（不调用
     模型），明确告知「当前知识库无法获得准确答案」；
  4. 用户选择「先这样回答」→ before_model 注入停止指令，给模型一次
     基于已检索内容整合答案的机会；若模型仍调用工具，after_model
     剥除工具调用并给出兜底结论。

时间信号不依赖模型自觉：询问与硬上限都在 wrap_model_call 钩子里短路
（不调用模型），保证到点必触发；状态按 thread_id 保存在类级注册表中，
跨「澄清暂停 → 用户点选续跑」的多次 stream 调用保持。

阈值可用环境变量覆盖（便于测试）：
  KGE_EXPLORE_FIRST_ASK  （默认 60 秒）
  KGE_EXPLORE_SECOND_ASK （默认 300 秒，续跑后）
  KGE_EXPLORE_HARD_LIMIT （默认 600 秒，总时长）
"""

import logging
import math
import os
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


def _env_seconds(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, "").strip() or default)
    except (TypeError, ValueError):
        return default


_FIRST_ASK = _env_seconds("KGE_EXPLORE_FIRST_ASK", 60.0)
_SECOND_ASK = _env_seconds("KGE_EXPLORE_SECOND_ASK", 300.0)
_HARD_LIMIT = _env_seconds("KGE_EXPLORE_HARD_LIMIT", 600.0)
_MAX_TRACKED_THREADS = 200

#: 阶段：first（首问计时中）→ asked1（已发首次询问，等用户续跑）
#: → second（续跑计时中）→ asked2（已发二次询问）
#: → done（已强制收尾/正常完成）

#: 首次询问（满 1 分钟）
_ASK1_QUESTION = "已检索约 1 分钟，暂时还没有找到确切答案。是否继续深入探索？"
_ASK1_OPTIONS = ["继续探索（再给我一些时间）", "先基于已检索内容回答"]

#: 二次询问（继续后满 5 分钟）
_ASK2_QUESTION = (
    "又检索了约 5 分钟，仍在查找中。是否继续？"
    "（本次探索总时长上限为 10 分钟，到达上限后将基于现有结果作答）"
)
_ASK2_OPTIONS = ["继续探索", "先基于已检索内容回答"]

_STOP_NOW_MSG = (
    "【用户选择停止探索】用户要求先基于已检索内容作答。立即停止调用一切检索工具，"
    "用已获得的资料整合出当前最完整的答案；资料不足的部分明确说明，不要继续检索。"
)

#: 用户选择停止、模型仍坚持调用工具被 after_model 剥除时的兜底答复
_STOP_NOTE = (
    "已按您的选择停止继续探索。基于目前已检索到的资料，暂时无法给出确切答案；"
    "您可以换个问法，或提供更具体的文档名称、所在目录后再试。"
)

#: 硬上限（10 分钟）合成的最终答复
_HARD_STOP_NOTE = (
    "很抱歉，已达到最长探索时限（10 分钟），当前知识库无法获得该问题的准确答案。"
    "建议换个问法、提供更具体的文档名称或所在目录，或通过知识征集渠道补充相关文档后再问。"
)

#: 用户手动中断（点停止按钮）时合成的收尾消息（SSE 已断开，仅用于让图干净结束）
_CANCELLED_NOTE = "（本次回答已被用户中断）"


class ExplorationTimeoutMiddleware(AgentMiddleware[AgentState]):
    """按 thread 跟踪检索时长，到点合成询问 / 强制收尾。"""

    # 类级注册表：thread_id -> 计时状态（中间件实例可能随 agent 重建，状态类级共享）
    _lock = threading.Lock()
    _states: "OrderedDict[str, dict]" = OrderedDict()

    # ---- 生命周期控制（由 qa_server 在每次 stream 开始时调用） ----

    @classmethod
    def begin(cls, thread_id: str, action: str = "", *, question: str = "") -> None:
        """标记一次 stream 运行开始。

        action:
          - "" / "start"：用户提出新问题，重置计时；
          - "continue"：用户在澄清按钮中选择继续，进入下一计时阶段；
          - "stop"：用户选择先基于已检索内容回答，立即强制收尾。
        """
        now = time.monotonic()
        with cls._lock:
            st = cls._states.get(thread_id)
            if action == "continue" and st is not None:
                st["run_start"] = now
                if st.get("paused_at") is not None:
                    st["total_start"] += now - st.pop("paused_at")
                if st.get("stage") == "kb_choice":
                    st["stage"] = "first"
                    st["total_start"] = now
                    st["dingtalk_allowed"] = True
                elif st.get("stage") == "asked1":
                    st["stage"] = "second"
                st["stop_requested"] = False
                st["cancelled"] = False
                cls._states.move_to_end(thread_id)
                logger.info("[explore] thread=%s continue, stage=%s", thread_id, st["stage"])
            elif action == "stop":
                # 用户要求停止检索：即使没有进行中的计时状态（极端时序），也强制收尾
                if st is None:
                    st = {"total_start": now, "run_start": now, "stage": "kb",
                          "stop_requested": False, "force_stop": False, "cancelled": False}
                    cls._states[thread_id] = st
                st["stop_requested"] = True
                st["force_stop"] = True
                st["cancelled"] = False
                cls._states.move_to_end(thread_id)
                logger.info("[explore] thread=%s user asked to stop", thread_id)
            else:
                cls._states[thread_id] = {
                    "question": question,
                    "total_start": now,
                    "run_start": now,
                    "stage": "kb",
                    "stop_requested": False,
                    "force_stop": False,
                    "cancelled": False,
                }
                cls._states.move_to_end(thread_id)
            while len(cls._states) > _MAX_TRACKED_THREADS:
                cls._states.popitem(last=False)

    @classmethod
    def can_resume(cls, thread_id: str) -> bool:
        with cls._lock:
            st = cls._states.get(thread_id) or {}
            return bool(st and not st.get("cancelled") and not st.get("force_stop")
                        and st.get("stage") in {"kb", "kb_choice", "asked1", "asked2"})

    @classmethod
    def record_evidence(cls, thread_id: str, hits: list[dict]) -> None:
        with cls._lock:
            st = cls._states.get(thread_id)
            if st is not None and st.get("stage") == "kb":
                st["knowledge_attempted"] = True
                st["kb_evidence"] = (st.get("kb_evidence", []) + [h for h in hits if isinstance(h, dict) and str(h.get("content") or "").strip()])[:24]

    @classmethod
    def dingtalk_budget(cls, thread_id: str) -> float:
        """Tool-level fail-closed authorization, including subagent calls."""
        with cls._lock:
            st = cls._states.get(thread_id) or {}
            if not st.get("dingtalk_allowed") or st.get("stop_requested") or st.get("force_stop") or st.get("cancelled"):
                return 0
            stage = st.get("stage")
            if stage not in {"first", "second", "asked2"}:
                return 0
            now = time.monotonic()
            remaining = _HARD_LIMIT - (now - st["total_start"])
            if stage in {"first", "second"}:
                remaining = min(remaining, (_FIRST_ASK if stage == "first" else _SECOND_ASK) - (now - st["run_start"]))
            return max(0, remaining)

    def _gate_choice(self, state: AgentState, tid: str) -> dict | None:
        messages = state.get("messages", [])
        last = messages[-1] if messages else None
        calls = getattr(last, "tool_calls", None) or []
        with self._lock:
            st = self._states.get(tid)
            if not st or st.get("stage") != "kb":
                return None
            requested = next((c for c in calls if c["name"] == "ask_clarification"
                              and c.get("args", {}).get("clarification_type") == "approach_choice"), None)
            no_evidence_final = (getattr(last, "type", None) == "ai" and not calls
                                 and st.get("knowledge_attempted") and not st.get("kb_evidence"))
            if not requested and not no_evidence_final and not any(c["name"].startswith("dingtalk_") for c in calls):
                return None
            if not st.get("knowledge_attempted") and any(c["name"].startswith("dingtalk_") for c in calls):
                # Old/custom prompts may propose both sources at once. Complete local retrieval first.
                local = [c for c in calls if c["name"] == "knowledge_search"]
                if not local:
                    local = [{"name":"knowledge_search", "args":{"query":st.get("question") or "企业知识"},
                              "id":f"call_local_{uuid.uuid4().hex[:10]}", "type":"tool_call"}]
                st["knowledge_attempted"] = True
                return {"messages": [last.model_copy(update={"content":"", "tool_calls":local})]}
            args = dict(requested.get("args", {})) if requested else {}
            hits = st.get("kb_evidence", [])
            summary = str(args.get("evidence_summary") or "").strip()[:4000]
            if not hits:
                summary = "当前知识库未返回可用正文，尚无可总结的知识依据。"
            elif not summary:
                summary = "当前资料尚未完成充分性评估，已检索内容摘录：\n" + "\n".join(
                    str(h.get("document_title", "文档")) + "：" + str(h.get("content", ""))[:250] for h in hits[:3])
            score = args.get("confidence", 0)
            score = max(0, min(69, int(score))) if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score) else 0
            if not hits:
                score = 0
            args.update(question="知识库证据不足，是否继续从钉钉知识库探索？",
                        clarification_type="approach_choice", evidence_summary=summary,
                        confidence=score, confidence_reason=str(args.get("confidence_reason") or "尚无足够证据支持完整答案")[:500],
                        options=["继续从钉钉知识库探索", "基于知识库内容回答"], choice_kind="dingtalk_opt_in")
            st["stage"] = "kb_choice"
            st["paused_at"] = time.monotonic()
            call = {"name":"ask_clarification", "args":args, "id":f"call_gate_{uuid.uuid4().hex[:10]}", "type":"tool_call"}
            return {"messages": [last.model_copy(update={"content":"", "tool_calls":[call]})]}

    @classmethod
    def request_cancel(cls, thread_id: str) -> bool:
        """用户手动中断：标记取消，使进行中的图运行尽快收尾。

        返回 True 表示该 thread 有进行中的运行状态（已标记）；
        False 表示无状态（运行已结束/不存在），调用方无需处理。
        """
        with cls._lock:
            st = cls._states.get(thread_id)
            if st is None or st.get("stage") == "done":
                return False
            st["cancelled"] = True
            cls._states.move_to_end(thread_id)
        logger.warning("[explore] thread=%s cancel requested by user", thread_id)
        return True

    @classmethod
    def is_cancelled(cls, thread_id: str) -> bool:
        with cls._lock:
            st = cls._states.get(thread_id)
            return bool(st and st.get("cancelled"))

    @classmethod
    def _tid_from_runtime(cls, runtime: Runtime) -> str:
        tid = runtime.context.get("thread_id") if runtime else None
        return tid or "default"

    def _due_action(self, tid: str) -> tuple | None:
        """到点返回应执行的动作（同时推进阶段）：

        - None：正常调用模型；
        - ("ask", question, options)：合成 ask_clarification 工具调用，暂停等用户选择；
        - ("hard",)：合成最终答复消息（硬上限），直接结束。
        """
        now = time.monotonic()
        with self._lock:
            st = self._states.get(tid)
            if st is None:
                # 非 qa_server 引导的流程（极少）：初始化一份计时
                self._states[tid] = {
                    "total_start": now, "run_start": now, "stage": "kb",
                    "stop_requested": False, "force_stop": False, "cancelled": False,
                }
                return None
            # 用户手动中断：不调用模型，合成无工具调用的收尾消息让图立即结束
            if st.get("cancelled"):
                st["stage"] = "done"
                logger.warning("[explore] thread=%s cancelled by user, forcing wrap-up", tid)
                return ("cancelled",)
            # 用户选择停止：before_model 已注入停止指令，给模型一次整合答案的机会
            if st.get("stop_requested"):
                return None
            if st.get("stage") in {"kb", "kb_choice"}:
                return None
            elapsed_total = now - st["total_start"]
            elapsed_run = now - st["run_start"]
            stage = st.get("stage", "first")
            if st.get("force_stop") or (stage != "done" and elapsed_total >= _HARD_LIMIT):
                st["stage"] = "done"
                st["force_stop"] = True
                logger.warning(
                    "[explore] thread=%s hard limit reached (total %.0fs), forcing wrap-up",
                    tid, elapsed_total)
                return ("hard",)
            if stage == "first" and elapsed_run >= _FIRST_ASK:
                st["stage"] = "asked1"
                st["paused_at"] = now
                logger.info("[explore] thread=%s first ask due (%.0fs)", tid, elapsed_run)
                return ("ask", _ASK1_QUESTION, _ASK1_OPTIONS)
            if stage == "second" and elapsed_run >= _SECOND_ASK:
                st["stage"] = "asked2"
                st["paused_at"] = now
                logger.info("[explore] thread=%s second ask due (run %.0fs, total %.0fs)",
                            tid, elapsed_run, elapsed_total)
                return ("ask", _ASK2_QUESTION, _ASK2_OPTIONS)
        return None

    # ---- 中间件钩子 ----

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        """用户选择停止时，注入停止指令（给模型一次基于已有资料作答的机会）。

        询问/硬上限不走消息注入，而是在 wrap_model_call 中确定性短路。
        """
        tid = self._tid_from_runtime(runtime)
        with self._lock:
            st = self._states.get(tid)
            if st and st.get("stop_requested"):
                return {"messages": [SystemMessage(content=_STOP_NOW_MSG)]}
            if st and st.get("stage") == "kb":
                return {"messages": [SystemMessage(content=(
                    "【本轮检索策略，优先于旧技能】先仅用 knowledge_search 检索知识库。证据充分则直接回答。"
                    "证据不足时必须调用 ask_clarification，clarification_type=approach_choice，"
                    "evidence_summary 用中文总结已查原文能支持的内容并说明缺口（无内容要如实说明），"
                    "confidence 为0到69的整数，表示完整回答原问题的证据支持程度，confidence_reason说明评分原因。"
                    "此分数是未校准的模型评估，不是准确率或向量相似度。"
                    "选项为【继续从钉钉知识库探索】和【基于知识库内容回答】。"
                    "用户明确选择前禁止调用所有 dingtalk 工具或通过子智能体绕过，也不要自行作最终拒答。"
                ))]}
        return None

    @override
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self.before_model(state, runtime)

    def _short_circuit(self, tid: str) -> ModelResponse | None:
        """到点时不调用模型，直接合成模型响应（询问工具调用 / 硬上限答复）。"""
        due = self._due_action(tid)
        if due is None:
            return None
        if due[0] == "ask":
            _, question, options = due
            call_id = f"call_clarify_{uuid.uuid4().hex[:10]}"
            msg = AIMessage(content="", tool_calls=[{
                "name": "ask_clarification",
                "args": {
                    "question": question,
                    "clarification_type": "approach_choice",
                    "choice_kind": "exploration_timeout",
                    "options": list(options),
                },
                "id": call_id,
                "type": "tool_call",
            }])
            logger.info("[explore] thread=%s forced clarification pause: %s", tid, question[:40])
            return ModelResponse(result=[msg])
        # 硬上限 / 用户中断：合成无工具调用的最终答复，图路由看到后即结束
        note = _CANCELLED_NOTE if due[0] == "cancelled" else _HARD_STOP_NOTE
        logger.warning("[explore] thread=%s forced final answer (%s)", tid, due[0])
        return ModelResponse(result=[AIMessage(content=note)])

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        sc = self._short_circuit(self._tid_from_runtime(request.runtime))
        return sc if sc is not None else handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        sc = self._short_circuit(self._tid_from_runtime(request.runtime))
        return sc if sc is not None else await handler(request)

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        """强制收尾/用户中断后模型仍返回工具调用：剥除工具调用并给出收尾消息。"""
        tid = self._tid_from_runtime(runtime)
        gate = self._gate_choice(state, tid)
        if gate is not None:
            return gate
        with self._lock:
            st = self._states.get(tid)
            forced = bool(st and st.get("force_stop"))
            cancelled = bool(st and st.get("cancelled"))
            by_user_stop = bool(st and st.get("stop_requested"))
        if not forced and not cancelled:
            return None
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else None
        if getattr(last_msg, "type", None) != "ai":
            return None
        if not getattr(last_msg, "tool_calls", None):
            return None
        if cancelled:
            note = _CANCELLED_NOTE
        else:
            note = _STOP_NOTE if by_user_stop else _HARD_STOP_NOTE
        # 被剥除的消息本身是"准备继续调用工具"的过渡消息，其文本是规划独白，
        # 不能作为答案；直接替换为兜底结论。
        stripped = last_msg.model_copy(update={
            "tool_calls": [],
            "content": note,
        })
        logger.info("[explore] thread=%s stripped tool_calls to force final answer", tid)
        return {"messages": [stripped]}

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)

    def _cleanup_if_finished(self, state: AgentState, runtime: Runtime) -> None:
        """运行正常结束（末尾为最终 AI 答复）时清理计时；澄清暂停则保留待续跑。"""
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else None
        if getattr(last_msg, "type", None) == "tool" and getattr(last_msg, "name", "") == "ask_clarification":
            return  # 澄清暂停：状态保留，等待用户点选后 begin(continue/stop)
        tid = self._tid_from_runtime(runtime)
        with self._lock:
            self._states.pop(tid, None)

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        self._cleanup_if_finished(state, runtime)
        return None

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        self._cleanup_if_finished(state, runtime)
        return None
