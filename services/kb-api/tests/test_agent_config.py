"""智能体默认模型（default_model）配置生效的回归测试。"""
import unittest
from types import SimpleNamespace

from app.services.agent.config import (DEFAULT_CONFIG, load_agent_config,
                                       resolve_agent_model, save_agent_config)


class ResolveModelTests(unittest.TestCase):
    def test_default_model_wins_when_in_list(self):
        cfg = {'models': ['a', 'b'], 'default_model': 'b'}
        self.assertEqual(resolve_agent_model(cfg, 'sys'), 'b')

    def test_default_model_used_when_list_empty(self):
        self.assertEqual(resolve_agent_model({'models': [], 'default_model': 'x'}, 'sys'), 'x')

    def test_falls_back_to_first_model(self):
        self.assertEqual(resolve_agent_model({'models': ['a', 'b'], 'default_model': ''}, 'sys'), 'a')

    def test_falls_back_to_system_model(self):
        self.assertEqual(resolve_agent_model({'models': [], 'default_model': ''}, 'sys'), 'sys')

    def test_stale_default_outside_list_ignored(self):
        self.assertEqual(resolve_agent_model({'models': ['a'], 'default_model': 'zz'}, 'sys'), 'a')


class FakeSession:
    """最小 AsyncSession 替身：单行 settings 存储。"""

    def __init__(self):
        self.row = None

    async def execute(self, stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self.row)

    def add(self, obj):
        self.row = obj

    async def commit(self):
        return None


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_clears_default_model_not_in_models(self):
        db = FakeSession()
        saved = await save_agent_config(db, {'models': ['a', 'b'], 'default_model': 'zz'})
        self.assertEqual(saved['default_model'], '')
        saved = await save_agent_config(db, {'models': ['a', 'b'], 'default_model': 'b'})
        self.assertEqual(saved['default_model'], 'b')
        loaded = await load_agent_config(db)
        self.assertEqual(loaded['default_model'], 'b')
        self.assertEqual(loaded['models'], ['a', 'b'])

    async def test_default_key_present_when_absent(self):
        db = FakeSession()
        loaded = await load_agent_config(db)
        self.assertEqual(loaded['default_model'], DEFAULT_CONFIG['default_model'])


class SanitizeAgentModelTests(unittest.TestCase):
    """agent_bootstrap 加固：智能体配置 resolve 出脏模型（引用已删除的模型配置）
    时回退系统模型，防止模型名与 LLM 端点不匹配导致问答 400（生产实锤：
    models 残留 glm-5.3 而 llm_profiles 只有 deepseek 系列）。"""

    def test_valid_model_kept(self):
        from app.routes.agent_internal import _sanitize_agent_model
        self.assertEqual(
            _sanitize_agent_model('deepseek-flash', {'deepseek-flash', 'deepseek-v4-pro'}, 'deepseek-flash'),
            'deepseek-flash')

    def test_stale_model_falls_back_to_system(self):
        from app.routes.agent_internal import _sanitize_agent_model
        self.assertEqual(
            _sanitize_agent_model('glm-5.3', {'deepseek-flash', 'deepseek-v4-pro'}, 'deepseek-flash'),
            'deepseek-flash')

    def test_all_invalid_keeps_original(self):
        """系统模型也无效时不改写：让请求自然报错暴露配置问题，不静默换错配置。"""
        from app.routes.agent_internal import _sanitize_agent_model
        self.assertEqual(_sanitize_agent_model('x', set(), ''), 'x')


class EffectiveModelsTests(unittest.IsolatedAsyncioTestCase):
    """有效模型集合：全部 LLM profile 模型 + 系统 llm_model 合并。"""

    async def test_merges_profiles_and_system_model(self):
        import json as _json
        from types import SimpleNamespace as _NS
        from app.routes.agent_internal import _effective_models

        class _Session:
            async def execute(self, stmt):
                if 'llm_profiles' in str(stmt):
                    rows = [_NS(models=_json.dumps(
                        [{"name": "deepseek-flash"}, {"name": "deepseek-v4-pro"}]))]
                    return _NS(scalars=lambda: _NS(all=lambda: rows))
                return _NS(scalar_one_or_none=lambda: _NS(value='deepseek-flash'))

        self.assertEqual(await _effective_models(_Session()),
                         {'deepseek-flash', 'deepseek-v4-pro'})


if __name__ == '__main__':
    unittest.main()
