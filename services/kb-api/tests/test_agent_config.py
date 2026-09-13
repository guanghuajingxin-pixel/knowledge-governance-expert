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


if __name__ == '__main__':
    unittest.main()
