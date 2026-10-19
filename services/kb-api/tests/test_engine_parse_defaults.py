"""知识库解析引擎默认参数回归。

背景：知识库文档解析（managed_library._do_parse → adapter.create_job）此前把
档位写死为均衡档（本地 standard / 云端 balanced→pipeline），OCR 依赖隐式默认。
按产品要求，知识库默认解析配置固定为「最高质量 + 自动 OCR」：
  - 本地 mineru-kit：tier=quality（resolve_tier 映射原值 advanced），ocr_mode=auto
  - 云端 SaaS：tier=quality（saas_create_job 经 resolve_tier 映射 vlm），ocr_mode=auto
知识库设置（ProcessingConfig.tier/ocr_mode）支持用户自行配置，默认值即上述默认；
文档级设置不提供该两项（存储时剔除，避免默认值覆盖库级自定义）。
"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.routes import managed_library as routes
from app.routes.managed_library import ProcessingConfig
from app.services.knowledge_engines import EngineError
from app.services.knowledge_engines.mineru import MinerUEngine, MinerUCloudEngine


class _FakeResp:
    def __init__(self, status_code=201, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"job_id": "j-123"}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class _FakeClient:
    """httpx.AsyncClient 替身：记录 post 调用并返回预置响应。"""

    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, **kw):
        self.calls.append({"url": url, "json": json})
        return self.resp


class LocalEngineTierTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_job_defaults_to_quality_tier_and_auto_ocr(self):
        """本地 kit：默认提交 advanced（最高质量）+ ocr_mode auto，且保留 zip 产物。"""
        fake = _FakeClient(_FakeResp())
        with patch.object(MinerUEngine, "_client", lambda self: fake):
            job_id = await MinerUEngine("http://127.0.0.1:8010").create_job("f-1")
        self.assertEqual(job_id, "j-123")
        body = fake.calls[0]["json"]
        self.assertEqual(body["tier"], "advanced")
        self.assertEqual(body["ocr_mode"], "auto")
        self.assertIn("zip", body["output_formats"])

    async def test_create_job_passes_custom_tier_and_ocr(self):
        """自定义配置透传：speed 映射本地原值 flash，ocr_mode 原样传递。"""
        fake = _FakeClient(_FakeResp())
        with patch.object(MinerUEngine, "_client", lambda self: fake):
            await MinerUEngine("http://127.0.0.1:8010").create_job(
                "f-1", tier="speed", ocr_mode="ocr")
        body = fake.calls[0]["json"]
        self.assertEqual(body["tier"], "flash")
        self.assertEqual(body["ocr_mode"], "ocr")

    async def test_create_job_unknown_tier_falls_back_balanced(self):
        """未知档位回退均衡档（resolve_tier 兜底），不因配置异常阻断解析。"""
        fake = _FakeClient(_FakeResp())
        with patch.object(MinerUEngine, "_client", lambda self: fake):
            await MinerUEngine("http://127.0.0.1:8010").create_job("f-1", tier="超频档")
        self.assertEqual(fake.calls[0]["json"]["tier"], "standard")

    async def test_create_job_error_raises_engine_error(self):
        """提交失败收敛为 EngineError（HTTP 非 2xx）。"""
        fake = _FakeClient(_FakeResp(status_code=500, payload={"detail": "boom"}))
        with patch.object(MinerUEngine, "_client", lambda self: fake):
            with self.assertRaises(EngineError):
                await MinerUEngine("http://127.0.0.1:8010").create_job("f-1")


class CloudEngineTierTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_job_defaults_to_quality_tier_and_auto_ocr(self):
        """云端 SaaS：默认提交语义 quality（resolve_tier 映射 vlm）+ ocr_mode auto。"""
        from app.routes import mineru_saas
        saas_call = AsyncMock(return_value={"job_id": "batch-1"})
        with patch.object(mineru_saas, "saas_create_job", saas_call):
            job_id = await MinerUCloudEngine().create_job("up-1")
        self.assertEqual(job_id, "batch-1")
        payload = saas_call.await_args.args[0]
        self.assertEqual(payload["tier"], "quality")
        self.assertEqual(payload["ocr_mode"], "auto")

    async def test_create_job_passes_custom_tier_and_ocr(self):
        """自定义配置透传云端：语义 speed 经 resolve_tier 映射 pipeline。"""
        from app.routes import mineru_saas
        saas_call = AsyncMock(return_value={"job_id": "batch-2"})
        with patch.object(mineru_saas, "saas_create_job", saas_call):
            await MinerUCloudEngine().create_job("up-2", tier="speed", ocr_mode="txt")
        payload = saas_call.await_args.args[0]
        self.assertEqual(payload["tier"], "speed")
        self.assertEqual(payload["ocr_mode"], "txt")

    async def test_quality_maps_to_vlm_in_saas_contract(self):
        """契约校验：语义 quality → 云端原值 vlm（最高质量档），兜底逻辑不影响。"""
        from app.routes.mineru_contract import resolve_tier
        self.assertEqual(resolve_tier("quality", "cloud"), ("quality", "vlm"))
        self.assertEqual(resolve_tier("advanced", "local"), ("quality", "advanced"))


class LibraryEngineConfigTests(unittest.TestCase):
    """知识库设置中的引擎参数：默认值、值域校验、库级配置 → 解析参数合并。"""

    def test_processing_config_defaults_to_quality_and_auto(self):
        """未配置的库（含旧库无 processing）经 Pydantic 校验补默认 quality/auto。"""
        cfg = ProcessingConfig()
        self.assertEqual(cfg.tier, "quality")
        self.assertEqual(cfg.ocr_mode, "auto")

    def test_processing_config_rejects_invalid_values(self):
        """档位/OCR 值域外拒绝（422 由框架统一抛出）。"""
        with self.assertRaises(ValidationError):
            ProcessingConfig(tier="ultra")
        with self.assertRaises(ValidationError):
            ProcessingConfig(ocr_mode="always")

    def test_processing_for_reads_tier_from_library_config(self):
        """库级配置的引擎参数进入解析合并结果（_do_parse 据此传给引擎）。"""
        lib = SimpleNamespace(engine_config={
            "processing": {"chunk_token_num": 256, "tier": "speed", "ocr_mode": "ocr"}})
        doc = SimpleNamespace(engine_config={}, name="手册.pdf")
        proc = routes._processing_for(lib, doc)
        self.assertEqual(proc.get("tier"), "speed")
        self.assertEqual(proc.get("ocr_mode"), "ocr")

    def test_processing_for_old_library_falls_back_to_defaults(self):
        """旧库 processing 无引擎参数：合并结果缺省，_do_parse 侧回退默认 quality/auto。"""
        lib = SimpleNamespace(engine_config={"processing": {"chunk_token_num": 512}})
        doc = SimpleNamespace(engine_config={}, name="手册.pdf")
        proc = routes._processing_for(lib, doc)
        self.assertIsNone(proc.get("tier"))
        self.assertIsNone(proc.get("ocr_mode"))
        # _do_parse 的兜底口径：缺省即最高质量 + 自动 OCR
        self.assertEqual(proc.get("tier") or "quality", "quality")
        self.assertEqual(proc.get("ocr_mode") or "auto", "auto")


if __name__ == "__main__":
    unittest.main()
