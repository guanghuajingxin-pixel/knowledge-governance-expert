"""Verify the port against the checked-out RAGFlow algorithm, not a reimplementation."""
import ast
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from kb_common.rag.scoring import (queryer, tokens, prepare_query, term_scores,
    term_similarity, apply_rerank, blend, lexical_candidates)


class RagflowKernelTests(unittest.TestCase):
    def test_source_token_weight_parity(self):
        source = Path(__file__).resolve().parents[3] / 'ragflow/rag/nlp/query.py'
        if not source.exists():
            self.skipTest('Optional upstream checkout not packaged in service image')
        tree = ast.parse(source.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FulltextQueryer')
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {'token_similarity', 'similarity'}]
        namespace = {'defaultdict': defaultdict}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), namespace)
        upstream = SimpleNamespace(tw=queryer().tw)
        upstream.similarity = lambda q, d: namespace['similarity'](upstream, q, d)
        for query in [['合同', '审批', '流程'], ['a5e', '针杆'], ['run', 'car']]:
            documents = [query, list(reversed(query)), query[:1], ['unrelated']]
            expected = namespace['token_similarity'](upstream, query, documents)
            actual = queryer().token_similarity(query, documents)
            for a, b in zip(actual, expected):
                self.assertAlmostEqual(a, b, places=8)  # only deliberate epsilon correction differs

    def test_dictionary_segmentation_and_normalization(self):
        self.assertEqual(tokens('合同审批流程'), ('合同', '审批', '流程'))
        self.assertEqual(tokens('合同審批流程'), tokens('合同审批流程'))
        self.assertEqual(tokens('Ａ５Ｅ'), tokens('A5E'))

    def test_query_cleaning_preserves_scoring_order(self):
        q = prepare_query('请问合同如何审批？')
        self.assertEqual(q.scoring_keywords, ('合同', '审批'))
        self.assertEqual(term_similarity(q.text, '合同审批'), 1)
        self.assertIn('合同', q.expression)
        self.assertEqual(term_similarity('!!!', '合同'), 0)

    def test_adjacent_pair_weights_from_ragflow(self):
        # Independent arithmetic: a=.1, b=.3, ab=.45 -> denominator .85.
        original = queryer().tw
        try:
            queryer().tw = Mock()
            queryer().tw.weights.side_effect = lambda tks, preprocess: [(t, {'a': .25, 'b': .75}[t]) for t in tks]
            scores = queryer().token_similarity(['a', 'b'], [['a'], ['b','a'], ['a','b'], []])
            for actual, expected in zip(scores, [2/17, 8/17, 1, 0]):
                self.assertAlmostEqual(actual, expected)
        finally:
            queryer().tw = original

    def test_bm25_candidates_include_keyword_and_title(self):
        docs = [{'text': '无需审批', 'title': '合同审批流程'},
                {'text': '天气晴朗', 'title': ''},
                {'text': '参见附录', 'keywords': ['合同', '审批']}]
        found = lexical_candidates(prepare_query('合同审批'), docs, 10)
        self.assertEqual(set(found), {0, 2})

    def test_rerank_score_uses_ragflow_weighted_formula(self):
        hits = [{'score': .1, 'token_similarity': .8, 'semantic_weight': .7},
                {'score': .9, 'token_similarity': .1, 'semantic_weight': .7}]
        apply_rerank(hits, [{'index':1,'relevance_score':.3},{'index':0,'relevance_score':.9}])
        self.assertAlmostEqual(hits[0]['score'], .87)
        self.assertAlmostEqual(hits[1]['score'], .24)
        self.assertEqual(hits[0]['rerank_score'], .9)
        self.assertEqual(hits[0]['retrieval_score'], .1)

    def test_invalid_reranker_cannot_partially_mutate_results(self):
        for rows in [[{'index':0,'relevance_score':float('nan')}],
                     [{'index':0,'relevance_score':.3},{'index':0,'relevance_score':.4}], []]:
            hits = [{'score':.8,'token_similarity':.5}]
            with self.assertRaises(ValueError): apply_rerank(hits, rows)
            self.assertEqual(hits, [{'score':.8,'token_similarity':.5}])

    def test_weights_never_depend_on_other_candidates(self):
        self.assertEqual(blend(.4, .8, 0), .4)
        self.assertEqual(blend(.4, .8, 1), .8)
        q = prepare_query('合同审批')
        self.assertEqual(term_scores(q, [['合同','审批']])[0],
                         term_scores(q, [['天气'], ['合同','审批']])[1])


class TraceScoreTests(unittest.TestCase):
    def test_trace_preserves_final_blended_score(self):
        from kb_common.rag import tracer
        from unittest.mock import patch
        with patch.object(tracer.minio_client.minio, 'presigned_get_object', side_effect=ValueError()):
            result = tracer.trace({'score': .87, 'rerank_score': .9, 'score_type': 'ragflow_rerank'}, {})
        self.assertEqual(result['score'], .87)
        self.assertEqual(result['rerank_score'], .9)
