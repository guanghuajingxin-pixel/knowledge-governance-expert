"""chunk_vectors 单元测试：numpy 内核、缓存指纹、自愈回写、回填断点续跑。"""
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import numpy as np

from app.services import chunk_vectors
from app.services import library_retrieval as retrieval
from kb_common.rag.scoring import cosine, matrix_cosine, pack_vector, unpack_matrix


def chunk(text, parent=None):
    return NS(id=uuid.uuid4(), parent_id=parent, document_id=uuid.uuid4(),
              content=text, important_keywords=[], retrieval_enhancements={})


EMB_CFG = {'base_url': 'http://embedding/v1', 'api_key': '', 'model': 'test-model'}


class FakeResult:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def all(self):
        return self._rows

    def one(self):
        return self._one if self._one is not None else self._rows[0]

    def scalar_one(self):
        return self._one if self._one is not None else self._rows[0][0]

    def first(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return NS(all=lambda: self._rows)


class FakeSession:
    """按调用顺序返回预置结果的会话替身；多余/缺失调用都会报错。"""

    def __init__(self, results=()):
        self.results = list(results)
        self.statements = []
        self.committed = False

    async def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        if not self.results:
            raise AssertionError(f'unexpected execute: {stmt}')
        return self.results.pop(0)

    async def commit(self):
        self.committed = True


class FakeSessionFactory:
    """SessionLocal 替身：每次调用弹出下一个会话并包装为异步上下文。"""

    def __init__(self, sessions):
        self.sessions = list(sessions)
        self.opened = []

    def __call__(self):
        session = self.sessions.pop(0)
        self.opened.append(session)

        @asynccontextmanager
        async def cm():
            yield session
        return cm()


class NumpyKernelTests(unittest.TestCase):
    def test_pack_unpack_roundtrip(self):
        vec = [0.1, -0.2, 0.3]
        blob = pack_vector(vec)
        self.assertEqual(len(blob), 12)
        matrix = unpack_matrix([blob], 3)
        self.assertTrue(np.allclose(matrix, [[0.1, -0.2, 0.3]], atol=1e-7))

    def test_unpack_rejects_dim_mismatch(self):
        self.assertIsNone(unpack_matrix([pack_vector([1, 2])], 3))
        self.assertIsNone(unpack_matrix([], 3))

    def test_matrix_cosine_matches_cosine(self):
        vectors = [[1, 0], [.8, .6], [0, 0]]
        matrix = unpack_matrix([pack_vector(v) for v in vectors], 2)
        sims = matrix_cosine(matrix, [1, 0])
        self.assertAlmostEqual(float(sims[0]), cosine([1, 0], [1, 0]), places=6)
        self.assertAlmostEqual(float(sims[1]), cosine([1, 0], [.8, .6]), places=6)
        self.assertEqual(float(sims[2]), 0.0)  # 零范数行 → 0

    def test_matrix_cosine_dim_mismatch_raises(self):
        matrix = unpack_matrix([pack_vector([1, 0])], 2)
        with self.assertRaises(ValueError):
            matrix_cosine(matrix, [1, 0, 0])


class CacheTests(unittest.TestCase):
    def setUp(self):
        chunk_vectors.invalidate_cache()

    def tearDown(self):
        chunk_vectors.invalidate_cache()

    def test_cache_put_respects_budget(self):
        def entry(lib, nbytes):
            e = chunk_vectors._Entry(library_id=lib, model='m', fingerprint=(0, 0, None))
            e.nbytes = nbytes
            return e

        with patch('kb_common.config.get_settings',
                   return_value=NS(library_vector_cache_mb=0)):
            self.assertEqual(chunk_vectors._budget(), 0)
            chunk_vectors._cache_put(entry(1, 100))
            self.assertEqual(len(chunk_vectors._cache), 0)  # 0 预算=禁用缓存

        with patch('kb_common.config.get_settings',
                   return_value=NS(library_vector_cache_mb=1)):
            chunk_vectors._cache_put(entry(1, 600 * 1024))
            chunk_vectors._cache_put(entry(2, 600 * 1024))  # 超预算逐出最旧
            self.assertEqual(list(chunk_vectors._cache), [2])

    def test_entry_append_skips_duplicate_ids(self):
        entry = chunk_vectors._Entry(library_id=1, model='m', fingerprint=(0, 0, None))
        entry.matrix = np.zeros((1, 2), dtype=np.float32)
        entry.ids = {}
        cid = uuid.uuid4()
        items = [(cid, 'm', pack_vector([1, 0]))]
        chunk_vectors._entry_append(entry, items)
        chunk_vectors._entry_append(entry, items)  # 竞态重复回写：不重复入矩阵
        self.assertEqual(entry.matrix.shape, (2, 2))
        self.assertEqual(entry.ids, {cid: 1})

    def test_entry_append_rejects_dim_mismatch(self):
        entry = chunk_vectors._Entry(library_id=1, model='m', fingerprint=(0, 0, None))
        entry.matrix = np.zeros((1, 2), dtype=np.float32)
        entry.ids = {uuid.uuid4(): 0}
        chunk_vectors._entry_append(entry, [(uuid.uuid4(), 'm', pack_vector([1, 2, 3]))])
        self.assertEqual(entry.matrix.shape, (1, 2))  # 维度不一致整批忽略


class DenseScoresTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        chunk_vectors.invalidate_cache()

    def tearDown(self):
        chunk_vectors.invalidate_cache()

    async def test_selfheal_writes_via_independent_session(self):
        """缺失 ≤256：现场 embed 缺失分段、经独立 SessionLocal upsert 并入打分。"""
        c1, c2, c3 = chunk('a'), chunk('b'), chunk('c')
        fp_initial = (3, 2, datetime(2026, 10, 20, 12, 0, 0))
        session = FakeSession([
            FakeResult(one=fp_initial),                                     # 指纹
            FakeResult(rows=[(c1.id, pack_vector([1, 0])),
                              (c2.id, pack_vector([0, 1]))]),              # 构建窗口1
            FakeResult(rows=[]),                                            # 构建结束
            FakeResult(one=(3, 3, datetime(2026, 10, 20, 12, 0, 5))),      # 自愈后指纹
        ])
        heal_session = FakeSession([FakeResult(rows=[])])
        factory = FakeSessionFactory([heal_session])
        leaves = [(c1, 'n'), (c2, 'n'), (c3, 'n')]
        with patch.object(chunk_vectors, 'SessionLocal', factory), \
             patch.object(retrieval, 'embeddings', AsyncMock(return_value=[[.6, .8]])) as emb:
            scores = await chunk_vectors.dense_scores(session, 1, EMB_CFG, [1, 0], leaves)
        self.assertEqual(set(scores), {c1.id, c2.id, c3.id})
        self.assertAlmostEqual(scores[c1.id], 1.0)
        self.assertAlmostEqual(scores[c2.id], 0.0)
        self.assertAlmostEqual(scores[c3.id], cosine([1, 0], [.6, .8]), places=6)
        emb.assert_awaited_once_with(['c'], EMB_CFG)  # 只 embed 缺失分段
        self.assertEqual(len(heal_session.statements), 1)  # upsert 一次
        self.assertIn('library_chunk_embeddings', str(heal_session.statements[0]))
        self.assertTrue(heal_session.committed)  # 独立会话已提交

    async def test_missing_over_limit_degrades_without_heal(self):
        """缺失 >256（未回填/模型已变更）：不调 embedding、不写库，仅告警。"""
        leaves = [(chunk(f'text{i}'), 'n') for i in range(chunk_vectors._SELFHEAL_LIMIT + 1)]
        session = FakeSession([
            FakeResult(one=(len(leaves), 0, None)),  # 指纹：全缺
            FakeResult(rows=[]),                     # 构建：无新鲜向量
        ])
        with patch.object(retrieval, 'embeddings', AsyncMock()) as emb, \
             self.assertLogs('app.services.chunk_vectors', level='WARNING') as logs:
            scores = await chunk_vectors.dense_scores(session, 1, EMB_CFG, [1, 0], leaves)
        self.assertEqual(scores, {})
        emb.assert_not_called()
        self.assertTrue(any('backfill_chunk_embeddings' in message for message in logs.output))

    async def test_cache_hit_and_fingerprint_invalidation(self):
        """同指纹命中缓存只查指纹；指纹变化触发重建。"""
        c1 = chunk('a')
        blob = pack_vector([1, 0])
        fp = (1, 1, datetime(2026, 10, 20, 12, 0, 0))
        s1 = FakeSession([FakeResult(one=fp),
                          FakeResult(rows=[(c1.id, blob)]), FakeResult(rows=[])])
        first = await chunk_vectors.dense_scores(s1, 7, EMB_CFG, [1, 0], [(c1, 'n')])
        self.assertAlmostEqual(first[c1.id], 1.0)

        s2 = FakeSession([FakeResult(one=fp)])  # 命中：仅 1 条指纹查询
        again = await chunk_vectors.dense_scores(s2, 7, EMB_CFG, [1, 0], [(c1, 'n')])
        self.assertAlmostEqual(again[c1.id], 1.0)
        self.assertEqual(len(s2.statements), 1)

        fp_changed = (1, 1, datetime(2026, 10, 20, 13, 0, 0))
        s3 = FakeSession([FakeResult(one=fp_changed),
                          FakeResult(rows=[(c1.id, blob)]), FakeResult(rows=[])])
        rebuilt = await chunk_vectors.dense_scores(s3, 7, EMB_CFG, [1, 0], [(c1, 'n')])
        self.assertAlmostEqual(rebuilt[c1.id], 1.0)
        self.assertEqual(len(s3.statements), 3)  # 指纹 + 两窗构建

    async def test_upsert_uses_on_conflict(self):
        session = FakeSession([FakeResult(rows=[])])
        await chunk_vectors.upsert_embeddings(session, [(uuid.uuid4(), 'm', b'blob')])
        from sqlalchemy.dialects import postgresql
        compiled = str(session.statements[0].compile(dialect=postgresql.dialect()))
        self.assertIn('ON CONFLICT (chunk_id) DO UPDATE', compiled)


class LexicalDbTests(unittest.IsolatedAsyncioTestCase):
    async def test_covered_chunks_ranked_without_db_write(self):
        """全覆盖：BM25 召回直接基于持久化词频字典，无自愈写库。"""
        from kb_common.rag.scoring import prepare_query
        match, other = chunk('合同审批流程'), chunk('天气晴朗')
        session = FakeSession([FakeResult(rows=[
            (match.id, chunk_vectors.token_dict('合同审批流程', '手册', [])),
            (other.id, chunk_vectors.token_dict('天气晴朗', '手册', []))])])
        leaves = [(match, '手册'), (other, '手册')]
        texts = [{'text': '合同审批流程', 'title': '手册', 'keywords': []},
                 {'text': '天气晴朗', 'title': '手册', 'keywords': []}]
        with patch.object(chunk_vectors, 'SessionLocal', FakeSessionFactory([])) as factory:
            ids = await chunk_vectors.lexical_candidates_db(
                session, 1, prepare_query('合同审批'), leaves, texts, 10)
        self.assertEqual(ids, [0])  # 只有命中分段参与召回
        self.assertEqual(factory.opened, [])  # 全覆盖：无自愈写库

    async def test_selfheal_writes_missing_tokens(self):
        """缺失 ≤ 自愈上限：现场分词并经独立会话回写，随后参与召回。"""
        from kb_common.rag.scoring import prepare_query
        match, fresh = chunk('合同审批流程'), chunk('合同审批制度')
        session = FakeSession([FakeResult(rows=[(match.id,
                                                 chunk_vectors.token_dict('合同审批流程', '', []))])])
        heal_session = FakeSession([FakeResult(rows=[])])
        factory = FakeSessionFactory([heal_session])
        leaves = [(match, ''), (fresh, '')]
        texts = [{'text': '合同审批流程', 'title': '', 'keywords': []},
                 {'text': '合同审批制度', 'title': '', 'keywords': []}]
        with patch.object(chunk_vectors, 'SessionLocal', factory):
            ids = await chunk_vectors.lexical_candidates_db(
                session, 1, prepare_query('合同审批'), leaves, texts, 10)
        self.assertEqual(sorted(ids), [0, 1])
        self.assertEqual(len(heal_session.statements), 1)  # upsert 一次
        self.assertTrue(heal_session.committed)
        self.assertIn('library_chunk_tokens', str(heal_session.statements[0]))

    async def test_missing_over_limit_degrades_with_warning(self):
        """缺失 > 自愈上限（未回填）：告警并跳过，不写库不阻塞。"""
        from kb_common.rag.scoring import prepare_query
        leaves = [(chunk(f'内容{i}'), '') for i in range(chunk_vectors._SELFHEAL_LIMIT + 1)]
        texts = [{'text': '内容', 'title': '', 'keywords': []}] * len(leaves)
        session = FakeSession([FakeResult(rows=[])])
        with patch.object(chunk_vectors, 'SessionLocal', FakeSessionFactory([])) as factory, \
             self.assertLogs('app.services.chunk_vectors', level='WARNING') as logs:
            ids = await chunk_vectors.lexical_candidates_db(
                session, 1, prepare_query('合同审批'), leaves, texts, 10)
        self.assertEqual(ids, [])
        self.assertEqual(factory.opened, [])
        self.assertTrue(any('--scope tokens' in m for m in logs.output))


class BackfillTests(unittest.IsolatedAsyncioTestCase):
    async def test_backfill_batches_and_upserts(self):
        lib = NS(id=1, name='库A', library_type='document')
        cid1, cid2 = uuid.uuid4(), uuid.uuid4()
        cfg_session = FakeSession()
        libs_session = FakeSession([FakeResult(rows=[lib])])
        candidates_session = FakeSession([FakeResult(rows=[(cid1, 'text1'), (cid2, 'text2')])])
        upsert_session = FakeSession([FakeResult(rows=[])])
        empty_session = FakeSession([FakeResult(rows=[])])
        factory = FakeSessionFactory([cfg_session, libs_session, candidates_session,
                                      upsert_session, empty_session])
        with patch.object(chunk_vectors, 'SessionLocal', factory), \
             patch.object(retrieval, 'config', AsyncMock(return_value=EMB_CFG)), \
             patch.object(retrieval, 'embeddings', AsyncMock(return_value=[[1, 0], [0, 1]])) as emb:
            stats = await chunk_vectors.backfill(batch_size=2, scope='vectors')
        self.assertEqual(stats[1]['backfilled_vectors'], 2)
        self.assertEqual(stats[1]['failed_vectors'], 0)
        emb.assert_awaited_once_with(['text1', 'text2'], EMB_CFG)
        self.assertIn('library_chunk_embeddings', str(upsert_session.statements[0]))
        self.assertTrue(upsert_session.committed)  # 每批独立提交=断点续跑

    async def test_backfill_tokens_local_tokenization(self):
        """词项回填：本地分词（不调 embedding API），含增强文本与文档名标题。"""
        lib = NS(id=5, name='库E', library_type='document')
        libs_session = FakeSession([FakeResult(rows=[lib])])
        cand_session = FakeSession([FakeResult(rows=[
            (uuid.uuid4(), '合同审批流程', {'summary': '摘要'}, ['审批'], '员工手册')])])
        upsert_session = FakeSession([FakeResult(rows=[])])
        empty_session = FakeSession([FakeResult(rows=[])])
        factory = FakeSessionFactory([libs_session, cand_session, upsert_session, empty_session])
        with patch.object(chunk_vectors, 'SessionLocal', factory), \
             patch.object(retrieval, 'embeddings', AsyncMock()) as emb:
            stats = await chunk_vectors.backfill(library_id=5, scope='tokens')
        self.assertEqual(stats[5]['backfilled_tokens'], 1)
        self.assertEqual(stats[5]['failed_tokens'], 0)
        emb.assert_not_called()  # 词项回填无外部 API
        self.assertIn('library_chunk_tokens', str(upsert_session.statements[0]))
        self.assertTrue(upsert_session.committed)

    async def test_backfill_skips_failed_batch_and_resumes(self):
        lib = NS(id=2, name='库B', library_type='document')
        cfg_session = FakeSession()
        libs_session = FakeSession([FakeResult(rows=[lib])])
        candidates_session = FakeSession([FakeResult(rows=[(uuid.uuid4(), 'x')])])
        empty_session = FakeSession([FakeResult(rows=[])])
        factory = FakeSessionFactory([cfg_session, libs_session, candidates_session, empty_session])
        with patch.object(chunk_vectors, 'SessionLocal', factory), \
             patch.object(retrieval, 'config', AsyncMock(return_value=EMB_CFG)), \
             patch.object(retrieval, 'embeddings', AsyncMock(side_effect=ValueError('向量模型调用失败'))):
            stats = await chunk_vectors.backfill(library_id=2, batch_size=1, scope='vectors')
        self.assertEqual(stats[2]['backfilled_vectors'], 0)
        self.assertEqual(stats[2]['failed_vectors'], 1)

    async def test_backfill_dry_run_counts_only(self):
        lib = NS(id=3, name='库C', library_type='document')
        cfg_session = FakeSession()
        libs_session = FakeSession([FakeResult(rows=[lib])])
        count_session = FakeSession([FakeResult(rows=[(5,)])])
        factory = FakeSessionFactory([cfg_session, libs_session, count_session])
        with patch.object(chunk_vectors, 'SessionLocal', factory), \
             patch.object(retrieval, 'config', AsyncMock(return_value=EMB_CFG)), \
             patch.object(retrieval, 'embeddings', AsyncMock()) as emb:
            stats = await chunk_vectors.backfill(library_id=3, dry_run=True, scope='vectors')
        self.assertEqual(stats[3]['pending_vectors'], 5)
        emb.assert_not_called()

    async def test_backfill_requires_configured_model(self):
        factory = FakeSessionFactory([FakeSession(), FakeSession([FakeResult(rows=[])])])
        with patch.object(chunk_vectors, 'SessionLocal', factory), \
             patch.object(retrieval, 'config',
                          AsyncMock(return_value={'base_url': '', 'model': '', 'api_key': ''})):
            with self.assertRaisesRegex(ValueError, '向量模型未配置'):
                await chunk_vectors.backfill(scope='vectors')

    async def test_backfill_truncates_oversized_content(self):
        """病态超长分段（实测 8M 字符）截断到段首再送 embedding，避免服务端 400。"""
        lib = NS(id=4, name='库D', library_type='document')
        long_content = '超长内容' * 5000  # 2 万字符
        cfg_session = FakeSession()
        libs_session = FakeSession([FakeResult(rows=[lib])])
        candidates_session = FakeSession([FakeResult(rows=[(uuid.uuid4(), long_content)])])
        upsert_session = FakeSession([FakeResult(rows=[])])
        empty_session = FakeSession([FakeResult(rows=[])])
        factory = FakeSessionFactory([cfg_session, libs_session, candidates_session,
                                      upsert_session, empty_session])
        with patch.object(chunk_vectors, 'SessionLocal', factory), \
             patch.object(retrieval, 'config', AsyncMock(return_value=EMB_CFG)), \
             patch.object(retrieval, 'embeddings', AsyncMock(return_value=[[1, 0]])) as emb:
            stats = await chunk_vectors.backfill(library_id=4, batch_size=1, scope='vectors')
        self.assertEqual(stats[4]['backfilled_vectors'], 1)
        sent = emb.await_args.args[0][0]
        self.assertEqual(len(sent), chunk_vectors._EMBED_MAX_CHARS)


if __name__ == '__main__':
    unittest.main()
