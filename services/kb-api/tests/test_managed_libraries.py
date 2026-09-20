import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from app.services.knowledge_engines.ragflow import RagflowEngine, EngineError, document_state
from app.services.knowledge_engines.mineru import job_state
from app.services.knowledge_engines.local_chunker import chunk_markdown, clean_markdown, est_tokens
from app.routes import managed_library as routes


class EngineContractTests(unittest.IsolatedAsyncioTestCase):
    async def request_with(self, method, path, responses, **kwargs):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.request.side_effect = responses
        with patch('app.services.knowledge_engines.ragflow.httpx.AsyncClient', return_value=client):
            result = await RagflowEngine('http://engine/api/v1', 'test').request(method, path, **kwargs)
        return result, client

    def response(self, code=200, body=None):
        return httpx.Response(code, json=body or {'code': 0, 'data': {}}, request=httpx.Request('GET', 'http://engine'))

    async def test_legacy_patch_fallback_only_on_405(self):
        _, client = await self.request_with('PATCH', '/datasets/a/documents/b', [self.response(405), self.response()], json={'chunk_method':'naive'})
        self.assertEqual([c.args[0] for c in client.request.call_args_list], ['PATCH', 'PUT'])
        self.assertEqual(client.request.call_args_list[1].kwargs['json'], {'chunk_method':'naive'})

    async def test_ambiguous_mutation_not_retried(self):
        with self.assertRaises(EngineError):
            await self.request_with('PATCH', '/datasets/a/documents/b', [self.response(500)])

    async def test_business_failure_rejected(self):
        with self.assertRaisesRegex(EngineError, 'No access'):
            await self.request_with('POST', '/datasets', [self.response(body={'code': 102, 'message':'No access'})])

    async def test_wire_contracts(self):
        adapter = RagflowEngine('http://engine', 'test')
        adapter.request = AsyncMock(return_value={'chunks': [], 'total': 0})
        await adapter.parse('ds', 'doc')
        adapter.request.assert_awaited_with('POST', '/datasets/ds/chunks', json={'document_ids':['doc']})
        await adapter.parse('ds', 'doc', stop=True)
        adapter.request.assert_awaited_with('DELETE', '/datasets/ds/chunks', json={'document_ids':['doc']})
        await adapter.delete_chunk('ds', 'doc', 'chunk')
        adapter.request.assert_awaited_with('DELETE', '/datasets/ds/documents/doc/chunks', json={'chunk_ids':['chunk']})
        await adapter.chunks('ds', 'doc', 3, 20)
        adapter.request.assert_awaited_with('GET', '/datasets/ds/documents/doc/chunks', params={'page':3, 'page_size':20})

    def test_state_mapping(self):
        for run in ['3', 'DONE']:
            self.assertEqual(document_state({'run':run,'progress':1}), ('COMPLETED', 1))
        self.assertEqual(document_state({'run':'RUNNING','progress':-1}), ('FAILED',0))
        self.assertEqual(document_state({'run':'2','progress':0}), ('CANCELLED',0))
        self.assertEqual(document_state({'run':'future_state'}), ('UNKNOWN',0))

    def test_validation(self):
        for payload in [{'name':'   '}, {'name':'x','chunk_token_num':0}, {'name':'x','chunk_token_num':2049}, {'name':'x','delimiter':''}]:
            with self.assertRaises(ValidationError): routes.LibraryIn(**payload)
        lib = routes.LibraryIn(name='知识库')
        self.assertEqual(lib.chunk_method, 'naive')
        self.assertEqual(lib.delimiter, '\n。！？；')
        self.assertEqual(lib.chunk_token_num, 512)

    async def test_no_edit_while_parsing(self):
        lib = SimpleNamespace(dataset_id='ds')
        doc = SimpleNamespace(engine_document_id='doc', status='PARSING')
        with patch.object(routes, 'bound_document', AsyncMock(return_value=(lib, doc))):
            with self.assertRaises(HTTPException) as raised:
                await routes.chunk_context(None, 1, 'doc', writing=True)
            self.assertEqual(raised.exception.status_code, 409)

    async def test_reparse_running_is_rejected(self):
        lib = SimpleNamespace(dataset_id='ds')
        doc = SimpleNamespace(engine_document_id='doc', status='PARSING')
        with patch.object(routes, 'bound_document', AsyncMock(return_value=(lib, doc))):
            with self.assertRaises(HTTPException): await routes.parse(1, 'doc', None)

    async def test_wrong_library_document_is_not_found(self):
        session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
        with patch.object(routes, 'library', AsyncMock(return_value=object())):
            with self.assertRaises(HTTPException) as raised:
                await routes.bound_document(session, 1, 'doc')
            self.assertEqual(raised.exception.status_code, 404)

    async def test_engine_unconfigured_is_503(self):
        with patch.object(routes, 'get_settings', return_value=SimpleNamespace(structured_kit_base_url='')):
            with self.assertRaises(HTTPException) as raised:
                routes.engine()
            self.assertEqual(raised.exception.status_code, 503)

    async def test_legacy_parsing_doc_marked_failed_on_refresh(self):
        lib = SimpleNamespace(engine_config={'processing': {}})
        doc = SimpleNamespace(engine_document_id='old-ragflow-id', engine_job_id=None,
                              status='PARSING', progress=0.5, message='')
        await routes.refresh_state(SimpleNamespace(), None, lib, doc)
        self.assertEqual(doc.status, 'FAILED')
        self.assertIn('MinerU', doc.message)



class UpgradeAndIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_models_normalize_source_response(self):
        adapter = RagflowEngine('http://engine', 'test')
        adapter.request = AsyncMock(return_value=[{'model_id':'id','name':'bge-m3','instance_name':'local','provider_name':'Xinference'}])
        self.assertEqual(await adapter.embedding_models(), [{'id':'id','name':'bge-m3@local@Xinference'}])

    async def test_new_disabled_chunk_updates_returned_id(self):
        adapter = RagflowEngine('http://engine','test')
        adapter.request = AsyncMock(side_effect=[{'chunk':{'id':'new'}}, None])
        await adapter.write_chunk('ds','doc',{'content':'text','available':False})
        adapter.request.assert_awaited_with('PATCH','/datasets/ds/documents/doc/chunks/new',json={'available':False})

    def test_parent_child_config(self):
        cfg = routes.ProcessingConfig(enable_children=True, children_delimiter='。')
        self.assertTrue(cfg.enable_children)
        with self.assertRaises(ValidationError): routes.ProcessingConfig(enable_children=True, chunk_method='table')

    async def test_query_does_not_leave_project_for_wrong_engine(self):
        from kb_common.clients import ragflow_client
        settings = SimpleNamespace(ragflow_base_url='http://other/api/v1',ragflow_api_key='key',ragflow_retrieval_top_k=8,
            ragflow_similarity_threshold=0.2,ragflow_vector_similarity_weight=0.3,ragflow_rerank_id='')
        with patch.object(ragflow_client,'get_settings',return_value=settings), patch.object(ragflow_client,'_binding_errors',AsyncMock(return_value=[{'dataset_id':'ds','error':'changed'}])), patch.object(ragflow_client.httpx,'AsyncClient') as client:
            result = await ragflow_client.retrieve_with_report(['ds'],'private query')
        self.assertEqual(result['hits'],[])
        self.assertEqual(result['skipped'][0]['dataset_id'],'ds')
        client.assert_not_called()



class MinerULocalTests(unittest.TestCase):
    def test_job_state_mapping(self):
        self.assertEqual(job_state({'status': 'queued'}), ('PARSING', 0.05))
        self.assertEqual(job_state({'status': 'running'}), ('PARSING', 0.5))
        self.assertEqual(job_state({'status': 'completed'}), ('COMPLETED', 1.0))
        self.assertEqual(job_state({'status': 'partial'}), ('COMPLETED', 1.0))
        self.assertEqual(job_state({'status': 'failed'}), ('FAILED', 0.0))
        self.assertEqual(job_state({'status': 'canceled'}), ('CANCELLED', 0.0))
        self.assertEqual(job_state({'status': 'weird'}), ('UNKNOWN', 0.0))

    def test_one_method_single_chunk(self):
        pieces = chunk_markdown('# 标题\n\n第一段。第二段！', {'chunk_method': 'one'})
        self.assertEqual(len(pieces), 1)
        self.assertIsNone(pieces[0]['children'])

    def test_naive_window_aggregation(self):
        text = '。'.join(f'句子{i}内容' for i in range(20)) + '。'
        pieces = chunk_markdown(text, {'chunk_method': 'naive', 'chunk_token_num': 20, 'delimiter': '。'})
        self.assertGreater(len(pieces), 1)
        for piece in pieces:
            self.assertLessEqual(est_tokens(piece['content']), 20 + 8)  # 单句不硬拆

    def test_children_materialized(self):
        text = '第一行内容\n第二行内容\n第三行内容'
        pieces = chunk_markdown(text, {'chunk_method': 'naive', 'chunk_token_num': 500,
                                       'delimiter': '。', 'enable_children': True, 'children_delimiter': '\n'})
        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0]['children'], ['第一行内容', '第二行内容', '第三行内容'])

    def test_data_uri_images_stripped(self):
        md = '# 标题\n\n![img](data:image/png;base64,AAAA)\n\n正文内容。'
        self.assertNotIn('data:image', clean_markdown(md))
        pieces = chunk_markdown(md, {'chunk_method': 'one'})
        self.assertIn('正文内容', pieces[0]['content'])
        self.assertNotIn('AAAA', pieces[0]['content'])

    def test_empty_markdown(self):
        self.assertEqual(chunk_markdown('   \n\n', {'chunk_method': 'naive'}), [])

    def test_auto_splits_at_headings(self):
        md = '# 第一章 概述\n\n这是概述内容。\n\n## 背景\n\n背景内容。\n\n# 第二章 实现\n\n实现内容。'
        pieces = chunk_markdown(md, {'chunk_method': 'auto', 'chunk_token_num': 512, 'delimiter': '\n。'})
        self.assertEqual(len(pieces), 3)
        self.assertTrue(pieces[0]['content'].startswith('# 第一章 概述'))
        self.assertTrue(pieces[1]['content'].startswith('## 背景'))
        self.assertTrue(pieces[2]['content'].startswith('# 第二章 实现'))

    def test_auto_oversized_section_splits_with_path_prefix(self):
        body = '。'.join(f'第{i}句内容较长一些' for i in range(60)) + '。'
        md = f'## 3.2 接口设计\n\n{body}'
        pieces = chunk_markdown(md, {'chunk_method': 'auto', 'chunk_token_num': 60, 'delimiter': '\n。'})
        self.assertGreater(len(pieces), 1)
        self.assertTrue(pieces[0]['content'].startswith('## 3.2 接口设计'))
        for piece in pieces[1:]:
            self.assertTrue(piece['content'].startswith('3.2 接口设计\n'))

    def test_auto_fence_heading_ignored(self):
        md = '# 真标题\n\n```python\n# 这是注释不是标题\nprint(1)\n```\n\n正文内容。'
        pieces = chunk_markdown(md, {'chunk_method': 'auto', 'chunk_token_num': 512, 'delimiter': '\n。'})
        self.assertEqual(len(pieces), 1)
        self.assertIn('# 这是注释不是标题', pieces[0]['content'])

    def test_auto_table_stays_atomic(self):
        intro = ''.join(f'前文说明第{i}句。' for i in range(10))
        outro = ''.join(f'后续补充第{i}句。' for i in range(10))
        rows = '\n'.join(f'| 参数名称{i} | 详细说明文字{i} |' for i in range(6))
        md = f'## 参数表\n\n{intro}\n\n| 参数 | 说明 |\n| --- | --- |\n{rows}\n\n{outro}'
        pieces = chunk_markdown(md, {'chunk_method': 'auto', 'chunk_token_num': 100, 'delimiter': '\n。'})
        self.assertGreater(len(pieces), 1)
        table_chunks = [p for p in pieces if '| 参数 | 说明 |' in p['content']]
        self.assertEqual(len(table_chunks), 1)
        self.assertIn('| 参数名称5 | 详细说明文字5 |', table_chunks[0]['content'])

    def test_auto_texttile_fallback_structureless(self):
        topic_a = ''.join(f'数据库索引结构影响查询性能和事务吞吐{i}。' for i in range(24))
        topic_b = ''.join(f'烹饪火候时长决定食材口感与调味层次{i}。' for i in range(24))
        pieces = chunk_markdown(topic_a + topic_b, {'chunk_method': 'auto', 'chunk_token_num': 512, 'delimiter': '。'})
        self.assertEqual(len(pieces), 2)
        self.assertIn('数据库', pieces[0]['content'])
        self.assertNotIn('烹饪', pieces[0]['content'])
        self.assertIn('烹饪', pieces[1]['content'])

    def test_auto_short_text_single_chunk(self):
        pieces = chunk_markdown('简短内容。', {'chunk_method': 'auto'})
        self.assertEqual(len(pieces), 1)

    def test_auto_texttile_noisy_within_topic(self):
        # 主题内用词多样（主题内相似度低）时，仍应只在真实主题切换处切分
        db = ''.join(s + '。' for s in (
            '数据库索引结构直接影响查询性能和事务吞吐能力', '合理的索引设计可以显著降低磁盘读取次数',
            '查询优化器根据统计信息选择执行计划', '事务隔离级别决定了并发读写的可见性规则',
            '缓冲池命中率是衡量存储引擎效率的重要指标', '慢查询日志帮助定位性能瓶颈的SQL语句',
            '主从复制通过二进制日志实现数据同步', '分库分表策略解决单表数据量过大的问题',
            '数据库连接池需要合理配置最大连接数', '定期执行表分析可以保证统计信息准确'))
        cooking = ''.join(s + '。' for s in (
            '烹饪火候的时长决定食材口感与调味层次', '大火快炒能够锁住蔬菜的水分和色泽',
            '炖汤需要小火慢煨才能释放食材鲜味', '调味讲究先后顺序与比例搭配',
            '翻炒的锅气来源于高温与美拉德反应', '食材的腌制时间影响入味程度',
            '蒸制能够最大程度保留营养成分', '刀工的粗细均匀影响受热一致性',
            '勾芡的浓稠度决定菜肴的挂汁效果', '油温的判断可以通过竹筷气泡观察'))
        pieces = chunk_markdown(db + '\n' + cooking,
                                {'chunk_method': 'auto', 'chunk_token_num': 512, 'delimiter': '\n。'})
        self.assertEqual(len(pieces), 2)
        self.assertIn('数据库', pieces[0]['content'])
        self.assertNotIn('烹饪', pieces[0]['content'])
        self.assertIn('烹饪', pieces[1]['content'])
        self.assertNotIn('数据库', pieces[1]['content'])

    def test_auto_texttile_uniform_text_not_split(self):
        # 高相似均匀文本：段落间相对波动不应触发误切
        uniform = '\n'.join(''.join(f'数据库索引影响查询性能{i}{j}。' for j in range(5)) for i in range(4))
        pieces = chunk_markdown(uniform, {'chunk_method': 'auto', 'chunk_token_num': 512, 'delimiter': '\n。'})
        self.assertEqual(len(pieces), 1)

    def test_auto_empty_markdown(self):
        self.assertEqual(chunk_markdown('   \n\n', {'chunk_method': 'auto'}), [])

if __name__ == '__main__': unittest.main()
