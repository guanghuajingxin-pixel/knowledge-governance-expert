import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.services.agent import deerflow_runner


def sse(*events) -> str:
    result = [{"type": "ready", "thread_id": "t1", "run_id": "run1"}]
    pending = {}
    for i, raw in enumerate(events):
        e = {"thread_id": "t1", "run_id": "run1", **raw}
        if e["type"] == "ai_text":
            e.update(type="answer_final", message_id=f"m{i}", source_node="model")
        if e["type"] == "tool_start":
            e.setdefault("call_id", f"call{i}")
            pending.setdefault(e["name"], []).append(e["call_id"])
        if e["type"] == "tool_end":
            e.setdefault("call_id", (pending.get(e["name"]) or [f"call{i}"]).pop(0))
        result.append(e)
    return "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in result)


RETRIEVE_START = {"type": "tool_start", "name": "knowledge_search", "args": {"query": "差旅报销 审批"}}
END = {"type": "end", "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, body: str) -> list[dict]:
        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            return real_client(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=body.encode())))
        events = []
        with patch.object(deerflow_runner.httpx, "AsyncClient", factory), \
             patch.object(deerflow_runner, "_generate_follow_ups", AsyncMock(return_value=[])):
            async for evt in deerflow_runner.run_deerflow_stream("差旅报销谁审批", thread_id="t1"):
                events.append(evt)
        return events

    def final_of(self, events):
        finals = [e for e in events if e["type"] == "final"]
        self.assertEqual(len(finals), 1)
        return finals[0]["result"]

    async def test_cited_retrieval_yields_answered_with_enriched_citations(self):
        hits = {"results": [{"document_title": "差旅报销管理制度", "document_id": "d1",
                             "segment_id": "s1", "score": 0.8,
                             "content": "报销需部门经理审批。"}]}
        body = sse(
            RETRIEVE_START,
            {"type": "tool_end", "name": "knowledge_search", "content": json.dumps(hits, ensure_ascii=False)},
            {"type": "ai_text", "content": "报销需部门经理审批 [1]。依据差旅报销管理制度"},
            END,
        )
        result = self.final_of(await self.collect(body))
        self.assertEqual(result["answer_status"], "answered")
        self.assertEqual(result["engine"], "deerflow")
        cite = result["citations"][0]
        self.assertEqual(cite["citation_id"], 1)
        self.assertEqual(cite["document_id"], "d1")
        self.assertEqual(cite["quote"], "报销需部门经理审批。")
        self.assertEqual(cite["text"], "报销需部门经理审批。")
        self.assertEqual(result["quality"]["dws"], "not_needed")
        self.assertEqual(result["usage"]["total_tokens"], 15)
        self.assertTrue(result["sufficiency"]["sufficient"])

    async def test_citations_event_streams_live(self):
        hits = {"results": [{"document_title": "差旅报销管理制度", "document_id": "d1",
                             "content": "报销需部门经理审批。"}]}
        body = sse(
            RETRIEVE_START,
            {"type": "tool_end", "name": "knowledge_search", "content": json.dumps(hits, ensure_ascii=False)},
            {"type": "ai_text", "content": "报销需部门经理审批 [1]。差旅报销管理制度"},
            END,
        )
        events = await self.collect(body)
        live = [e for e in events if e["type"] == "citations"]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["citations"][0]["citation_id"], 1)
        self.assertEqual(live[0]["citations"][0]["document_title"], "差旅报销管理制度")

    async def test_searched_but_empty_yields_insufficient(self):
        body = sse(
            RETRIEVE_START,
            {"type": "tool_end", "name": "knowledge_search", "content": json.dumps({"results": []})},
            {"type": "ai_text", "content": "知识库中暂未检索到相关内容。"},
            END,
        )
        result = self.final_of(await self.collect(body))
        self.assertEqual(result["answer_status"], "insufficient")
        self.assertEqual(result["citations"], [])
        self.assertFalse(result["sufficiency"]["sufficient"])
        self.assertTrue(result["sufficiency"]["missing"])

    async def test_conversational_reply_without_search_is_answered(self):
        body = sse({"type": "ai_text", "content": "你好，我是企业知识问答助手。"}, END)
        result = self.final_of(await self.collect(body))
        self.assertEqual(result["answer_status"], "answered")
        self.assertEqual(result["quality"]["dws"], "not_needed")

    async def test_hallucinated_markers_without_search_are_stripped(self):
        # 本轮未检索（复用历史/自有知识作答）却自带 [1]：标记必须清除，引用区为空
        body = sse({"type": "ai_text", "content": "上市公司考核基准分为 100 分 [1]。"}, END)
        result = self.final_of(await self.collect(body))
        self.assertNotIn("[1]", result["answer"])
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["answer_status"], "answered")

    async def test_dingtalk_hits_mark_quality_dws_hit(self):
        hits = {"results": [{"title": "差旅指引", "url": "https://alidocs.dingtalk.com/i/nodes/x",
                             "node_id": "x", "extension": "adoc"}]}
        body = sse(
            {"type": "tool_start", "name": "dingtalk_search", "args": {"query": "差旅"}},
            {"type": "tool_end", "name": "dingtalk_search", "content": json.dumps(hits, ensure_ascii=False)},
            {"type": "ai_text", "content": "可参阅钉钉文档《差旅指引》。"},
            END,
        )
        result = self.final_of(await self.collect(body))
        self.assertEqual(result["quality"]["dws"], "hit")
        self.assertEqual(result["citations"][0]["document_title"], "[钉钉] 差旅指引")
        self.assertEqual(result["answer_status"], "answered")


    async def test_refs_remap_to_document_level_citations(self):
        hits = {"results": [
            {"document_title": "安全事故调查处理制度", "document_id": "a1", "content": "现场人员立即报告。"},
            {"document_title": "安全事故调查处理制度", "document_id": "a2", "content": "负责人1小时内上报。"},
        ]}
        body = sse(
            RETRIEVE_START,
            {"type": "tool_end", "name": "knowledge_search", "content": json.dumps(hits, ensure_ascii=False)},
            {"type": "ai_text", "content": "条款一 [1]。条款二 [2]。无法解析 [9]。安全事故调查处理制度"},
            END,
        )
        events = await self.collect(body)
        result = self.final_of(events)
        # 同文档两个 ref 合并为同一文档级编号；悬空序号删除
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["citation_id"], 1)
        self.assertIn("条款二 [1]", result["answer"])
        self.assertNotIn("[9]", result["answer"])
        self.assertNotIn("[2]", result["answer"])

    async def test_internal_and_foreign_events_never_become_answers(self):
        foreign = {"type": "ai_text", "content": "用户当前问题：上一轮问题"}
        other = {"type": "answer_final", "thread_id": "other", "run_id": "other", "message_id": "bad", "source_node": "model", "content": "串台"}
        wire = json.dumps(foreign)  # raw unknown event before ready
        wire = 'data: ' + wire + '\n\n' + sse(other, {"type": "answer_final", "source_node": "model", "message_id": "m", "content": "本轮正式回答"}, END)
        events = await self.collect(wire)
        self.assertEqual(self.final_of(events)["answer"], "本轮正式回答")
        self.assertNotIn("上一轮", str(events))
        self.assertNotIn("串台", str(events))

    async def test_unknown_origin_or_truncated_response_fails_closed(self):
        for body in [sse({"type": "answer_final", "source_node": "summary", "message_id": "s", "content": "摘要"}, END),
                     sse({"type": "answer_final", "source_node": "model", "message_id": "m", "content": "未完成"})]:
            events = await self.collect(body)
            self.assertFalse(any(e["type"] == "final" for e in events))
            self.assertTrue(any(e["type"] == "config_error" for e in events))

    async def test_browse_failure_marks_step_failed(self):
        body = sse(
            {"type": "tool_start", "name": "dingtalk_browse", "call_id": "browse", "args": {}},
            {"type": "tool_end", "name": "dingtalk_browse", "call_id": "browse", "content": '{"error":"失败"}'},
            {"type": "ai_text", "content": "暂未找到依据"}, END)
        events = await self.collect(body)
        self.assertEqual([e["status"] for e in events if e.get("step_id") == "browse"], ["running", "failed"])
        self.assertIn("浏览钉钉目录失败", self.final_of(events)["quality"]["warnings"])
        self.assertEqual(self.final_of(events)["quality"]["verification"], "unverified")

    async def test_clarification_ends_with_clarification_answer(self):
        choice = {"type": "tool_start", "name": "ask_clarification", "call_id": "c1",
                  "args": {"question": "继续探索？", "options": ["继续", "停止"]}}
        events = await self.collect(sse(choice, END))
        # 新语义：澄清暂停不发 final，下发 choice_pause 供前端渲染选择按钮续跑
        pauses = [e for e in events if e["type"] == "choice_pause"]
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0]["question"], "继续探索？")
        self.assertEqual(pauses[0]["options"], ["继续", "停止"])
        self.assertFalse(any(e["type"] == "final" for e in events))


class NotifyReconfigTests(unittest.IsolatedAsyncioTestCase):
    """LLM 配置保存后通知 sidecar 热更新（fire-and-forget，失败静默）。"""

    async def test_posts_reconfig_and_swallows_errors(self):
        real_client = httpx.AsyncClient
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(str(request.url))
            return httpx.Response(200, json={"ok": True})

        def factory(*args, **kwargs):
            return real_client(transport=httpx.MockTransport(handler))

        with patch.object(deerflow_runner.httpx, "AsyncClient", factory):
            await deerflow_runner.notify_reconfig()
        self.assertEqual(captured, [f"{deerflow_runner.DEERFLOW_URL}/v1/reconfig"])

        def failing(*args, **kwargs):
            return real_client(transport=httpx.MockTransport(
                lambda request: httpx.Response(500)))

        with patch.object(deerflow_runner.httpx, "AsyncClient", failing):
            await deerflow_runner.notify_reconfig()  # 不抛异常即通过

        def unreachable(*args, **kwargs):
            raise httpx.ConnectError("refused")

        with patch.object(deerflow_runner.httpx, "AsyncClient", unreachable):
            await deerflow_runner.notify_reconfig()  # sidecar 未启动时静默


class RetryOnBusyTests(unittest.IsolatedAsyncioTestCase):
    """上游个人级并发限额（429 personal_rolling_*）自动退避重试。"""

    @staticmethod
    def _fake_stream(frames):
        async def _run(**kwargs):
            for f in frames:
                yield f
        return _run

    async def _collect(self, runs_frames):
        calls = {"n": 0}

        def factory(**kwargs):
            frames = runs_frames[min(calls["n"], len(runs_frames) - 1)]
            calls["n"] += 1
            return self._fake_stream(frames)(**kwargs)

        with patch.object(deerflow_runner, "run_deerflow_stream", factory):
            return [e async for e in deerflow_runner.run_deerflow_stream_with_retry(
                query="q", thread_id="t1")]

    async def test_busy_then_success_retries(self):
        busy = {"type": "config_error", "message": "RateLimitError: personal_rolling_7d_concurrent_attempt"}
        events = await self._collect([
            [{"type": "ready"}, busy],
            [{"type": "ready"}, {"type": "answer_delta", "text": "答案"},
             {"type": "final", "result": {"answer": "答案"}}],
        ])
        retries = [e for e in events if e.get("step_id") == "upstream_retry"]
        self.assertEqual(len(retries), 1)
        self.assertFalse(any(e["type"] == "config_error" for e in events))
        self.assertTrue(any(e["type"] == "final" for e in events))

    async def test_busy_after_progress_not_retried(self):
        busy = {"type": "config_error", "message": "personal_rolling 上游拒绝"}
        events = await self._collect([
            [{"type": "tool_start", "call_id": "c1", "name": "knowledge_search"}, busy],
        ])
        self.assertTrue(any(e["type"] == "config_error" for e in events))
        self.assertFalse(any(e.get("step_id") == "upstream_retry" for e in events))

    async def test_persistent_busy_exhausts_and_forwards_last_error(self):
        busy = {"type": "config_error", "message": "personal_rolling"}
        events = await self._collect([[{"type": "ready"}, busy]] * 3)
        retries = [e for e in events if e.get("step_id") == "upstream_retry"]
        self.assertEqual(len(retries), 2)  # 前两次重试，第三次透传原始错误
        self.assertEqual(sum(1 for e in events if e["type"] == "config_error"), 1)
