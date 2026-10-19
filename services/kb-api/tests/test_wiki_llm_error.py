"""Wiki 生成 LLM 错误翻译回归。

背景：SAP Wiki 库原料解析完成但页面全部生成失败，根因是 LLM 服务
余额不足（Error 402 Insufficient Balance），原始报错用户无法读懂、
也无从处理。_chat 统一把 LLM API 报错翻译为可行动的中文提示
（充值 / 换模型配置），失败原因直接落 WikiGenerationRun.error。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.services.wiki.generator as gen


class FriendlyLlmErrorTests(unittest.TestCase):
    def test_402_insufficient_balance(self):
        """402 余额不足 → 提示充值或切换模型配置。"""
        raw = ("Error code: 402 - {'error': {'message': 'Insufficient Balance "
               "(request_id: 7a9b)', 'type': 'unknown_error'}}")
        out = gen.friendly_llm_error(RuntimeError(raw))
        self.assertIn('余额不足', out)
        self.assertIn('模型配置', out)
        self.assertIn('402', out)

    def test_401_invalid_key(self):
        """401 鉴权失败 → 提示检查密钥。"""
        out = gen.friendly_llm_error(RuntimeError(
            "Error code: 401 - {'error': {'message': 'Authentication Fails'}}"))
        self.assertIn('API Key', out)
        self.assertIn('模型配置', out)

    def test_429_rate_limit(self):
        """429 限流 → 提示稍后重试。"""
        out = gen.friendly_llm_error(RuntimeError("Error code: 429 - Rate limit reached"))
        self.assertIn('429', out)
        self.assertIn('稍后重试', out)

    def test_unknown_error_kept_as_is(self):
        """未知错误保留原文，便于排查。"""
        out = gen.friendly_llm_error(RuntimeError("connection reset by peer"))
        self.assertEqual(out, "connection reset by peer")


class ChatWrapsErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_raises_llm_error_with_friendly_message(self):
        """_chat 内部异常统一包装为 LLMError（ValueError 子类，路由层可转 422）。"""
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(side_effect=RuntimeError(
                "Error code: 402 - Insufficient Balance")))))
        with patch.object(gen, "AsyncOpenAI", return_value=client):
            with self.assertRaises(gen.LLMError) as raised:
                await gen._chat({"base_url": "http://x", "api_key": "k", "model": "m"},
                                "sys", "user")
        self.assertIn('余额不足', str(raised.exception))
        # ValueError 子类：regenerate_page 路由层 except ValueError 转 422
        self.assertIsInstance(raised.exception, ValueError)

    async def test_chat_returns_content_on_success(self):
        """正常路径不受影响。"""
        resp = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="  ok  "))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=resp))))
        with patch.object(gen, "AsyncOpenAI", return_value=client):
            out = await gen._chat({"base_url": "http://x", "api_key": "k", "model": "m"},
                                  "sys", "user")
        self.assertEqual(out, "ok")


if __name__ == '__main__':
    unittest.main()
