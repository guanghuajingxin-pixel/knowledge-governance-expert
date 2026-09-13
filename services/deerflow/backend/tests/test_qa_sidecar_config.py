"""配置页配置项对 DeerFlow 问答链生效的回归测试。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app import qa_server
from extensions import kb_tools


class TestRetrievalMode:
    def test_force_injects_platform_prefix(self):
        msg = qa_server._apply_retrieval_mode("你好", "force")
        assert msg.startswith("【平台约束·强制检索模式】")
        assert msg.endswith("你好")

    @pytest.mark.parametrize("mode", ["smart", "", None])
    def test_smart_passthrough(self, mode):
        assert qa_server._apply_retrieval_mode("你好", mode) == "你好"


class TestKnowledgeSearchCap:
    def _invoke(self, monkeypatch, ctx, calls_made):
        monkeypatch.setattr(kb_tools, "RUNTIME_CTX", ctx)

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"results": []}

        class _Client:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def post(self, url, json=None, headers=None):
                calls_made.append(json)
                return _Resp()

        monkeypatch.setattr(kb_tools.httpx, "Client", _Client)

    def test_cap_blocks_beyond_rounds_times_three(self, monkeypatch):
        ctx = {"t1": {"dataset_ids": [], "kb_ids": [], "max_retrieval_rounds": 1, "search_calls": 3}}
        calls = []
        self._invoke(monkeypatch, ctx, calls)
        out = json.loads(kb_tools.knowledge_search_tool.func("差旅", config={"configurable": {"thread_id": "t1"}}))
        assert out["cap_reached"] is True
        assert out["results"] == []
        assert calls == []  # 超限不再请求 kb-api

    def test_under_cap_increments_counter(self, monkeypatch):
        ctx = {"t1": {"dataset_ids": [], "kb_ids": [], "max_retrieval_rounds": 2, "search_calls": 0}}
        calls = []
        self._invoke(monkeypatch, ctx, calls)
        kb_tools.knowledge_search_tool.func("差旅", config={"configurable": {"thread_id": "t1"}})
        assert ctx["t1"]["search_calls"] == 1
        assert len(calls) == 1


class TestWriteConfigAndPersona:
    def test_top_p_written_when_provided(self, tmp_path, monkeypatch):
        target = tmp_path / "config.yaml"
        monkeypatch.setattr(qa_server, "CONFIG_PATH", target)
        qa_server.write_config({"model": "m", "api_key": "k", "base_url": "http://x/v1",
                                "temperature": 0, "top_p": 0.85, "max_tokens": 4096})
        text = target.read_text(encoding="utf-8")
        assert "top_p: 0.85" in text

    def test_top_p_omitted_when_absent(self, tmp_path, monkeypatch):
        target = tmp_path / "config.yaml"
        monkeypatch.setattr(qa_server, "CONFIG_PATH", target)
        qa_server.write_config({"model": "m", "api_key": "k", "base_url": "http://x/v1",
                                "temperature": 0, "max_tokens": 4096})
        assert "top_p" not in target.read_text(encoding="utf-8")

    def test_persona_replaces_agent_name(self, tmp_path, monkeypatch):
        custom = tmp_path / "persona.custom.md"
        custom.write_text("你是「杰克百晓生」，助手。", encoding="utf-8")
        monkeypatch.setattr(qa_server, "PERSONA_CUSTOM_PATH", custom)
        monkeypatch.setattr(qa_server, "_BOOT_AGENT_NAME", "小杰")
        assert "小杰" in qa_server._effective_persona()
        monkeypatch.setattr(qa_server, "_BOOT_AGENT_NAME", "")
        assert "杰克百晓生" in qa_server._effective_persona()


def test_output_scope_applies_to_custom_persona_without_overwriting_it(tmp_path, monkeypatch):
    custom = tmp_path / 'persona.custom.md'
    custom.write_text('用户自定义人格', encoding='utf-8')
    monkeypatch.setattr(qa_server, 'PERSONA_CUSTOM_PATH', custom)
    assert '平台最终答复规则' in qa_server._effective_persona()
    assert custom.read_text() == '用户自定义人格'
