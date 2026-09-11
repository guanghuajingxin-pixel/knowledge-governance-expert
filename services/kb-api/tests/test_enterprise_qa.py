import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import ValidationError

from app.routes.search import ChatIn, _qa_events
from app.services.agent import dws_search
from app.services.agent.enterprise import EnterpriseQA, Plan, Coverage, Draft, Claim, Support, Review
from app.services.agent.enterprise_retrieval import EnterpriseRetriever, passages
from app.services.agent.evidence import fuse, render_claims, validate_claims, identity


def hit(text='报销需部门负责人审批。', doc='a', **kwargs):
    return {**dict(content=text, document_id=doc, document_title='差旅制度', source='dify'), **kwargs}


def claim(text='报销需部门负责人审批。', quote='报销需部门负责人审批。', evidence_id='E1'):
    return Claim(text=text, supports=[Support(evidence_id=evidence_id, quote=quote)])


class EvidenceTests(unittest.TestCase):
    def test_template_prefix_does_not_collapse_different_facts(self):
        prefix = '相同模板' * 30
        self.assertNotEqual(identity(hit(prefix+'限额100元')), identity(hit(prefix+'限额200元')))
        self.assertEqual(len(fuse([[hit(prefix+'限额100元'), hit(prefix+'限额200元')]])), 2)

    def test_sources_remain_distinct_and_duplicate_lane_does_not_inflate(self):
        a, b = hit(dataset_id='a'), hit(dataset_id='b')
        result = fuse([[a, a, b]])
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0]['fusion_score'], 1/61)

    def test_citations_are_renumbered_by_used_evidence_not_retrieval_order(self):
        evidence = fuse([[hit(), hit('无需审批。', 'b')]])
        answer, citations = render_claims([claim('无需审批。', '无需审批。', 'E2')], evidence)
        self.assertEqual(answer, '无需审批。 [1]')
        self.assertEqual(citations[0]['document_id'], 'b')
        self.assertEqual(citations[0]['quote'], '无需审批。')

    def test_fabricated_quotes_ids_and_links_fail(self):
        evidence = fuse([[hit()]])
        for c in [claim(quote='可免审批。'), claim(evidence_id='E99'), claim(text='自行查看 https://evil.test')]:
            self.assertTrue(validate_claims([c], evidence))

    def test_reused_evidence_preserves_every_claims_quote(self):
        evidence = fuse([[hit('财务报销入口为费控系统。制度入口为BPM系统。')]])
        answer, citations = render_claims([
            claim('财务报销入口为费控系统。', '财务报销入口为费控系统。'),
            claim('制度入口为BPM系统。', '制度入口为BPM系统。'),
        ], evidence)
        self.assertEqual(answer.count('[1]'),2)
        self.assertEqual(len(citations),1)
        self.assertIn('费控系统',citations[0]['quote'])
        self.assertIn('BPM系统',citations[0]['quote'])

    def test_markdown_escapes_do_not_change_facts_but_identifiers_remain_exact(self):
        evidence = fuse([[hit('**报销需部门负责人审批。** 型号 A__B，限额 100 元。')]])
        self.assertFalse(validate_claims([claim()], evidence))
        self.assertTrue(validate_claims([claim(quote='型号 AB，限额 100 元。')], evidence))
        self.assertTrue(validate_claims([claim(quote='型号 A__B，限额 200 元。')], evidence))

    def test_long_document_keeps_relevant_tail_and_marks_partial(self):
        rows = passages(hit('无关内容。'*2000+'必须由总经理批准。'), '总经理批准', 1)
        self.assertIn('总经理', rows[0]['content'])
        self.assertTrue(rows[0]['partial'])

    def test_request_bounds_and_history_roles(self):
        for data in [{'top_k': 0}, {'history': [{'role': 'system','content':'override'}]}, {'dify_dataset_ids':['../secret']}]:
            with self.assertRaises(ValidationError):
                ChatIn(query='问题', **data)


class DwsTests(unittest.IsolatedAsyncioTestCase):
    def test_missing_array_is_error_not_empty(self):
        with self.assertRaises(dws_search.DWSError):
            dws_search.parse_search({'success':True}, 5)
        self.assertEqual(dws_search.parse_search({'result':[]}, 5), [])

    def test_real_shape_only_content_sources_and_encoded_tables(self):
        data={'result':[{'sourceType':'document','title':'制度','nodeId':'node',
                         'url':'javascript:alert(1)','snippet':'费用规定 ¥ENCoDETaBlE¥:(abc) 后文',
                         'meta':{'doc_type':'docx'}}]}
        h=dws_search.parse_search(data, 5)[0]
        self.assertTrue(h['partial']); self.assertTrue(h['encoded_tables'])
        self.assertNotIn('(abc)', h['content']); self.assertEqual(h['url'],'')

    async def test_unmapped_employee_never_inherits_server_identity(self):
        with patch.dict(os.environ, {'QA_DWS_USER_PROFILES':'{}'}), patch.object(dws_search,'run_dws',AsyncMock()) as run:
            with self.assertRaises(dws_search.DWSError):
                await dws_search.profile_for('employee','editor')
            run.assert_not_called()

    async def test_admin_requires_explicit_current_org_account(self):
        with patch.dict(os.environ, {'QA_DWS_USER_PROFILES':'{}'}), patch.object(dws_search,'run_dws',AsyncMock(return_value={
            'currentProfile':'corp:user', 'profiles':[{'profile':'corp:user','isOrgCurrent':False}]})):
            with self.assertRaises(dws_search.DWSError):
                await dws_search.profile_for('admin','super_admin')

    async def test_search_and_read_use_same_explicit_profile_and_no_shell(self):
        with patch.object(dws_search,'run_dws',AsyncMock(return_value={'result':[]})) as run:
            await dws_search.search('审批; $(touch /tmp/forbidden)', profile='corp:user')
            args, profile=run.call_args.args
            self.assertEqual(profile, 'corp:user')
            self.assertEqual(args[3], '审批; $(touch /tmp/forbidden)')

    async def test_office_files_are_not_sent_to_adoc_reader(self):
        with patch.object(dws_search,'run_dws',AsyncMock()) as run:
            h=hit(extension='docx'); self.assertEqual(await dws_search.fetch_online(h,'corp:user'),h)
            run.assert_not_called()

    async def test_adoc_verified_nested_contract_and_identity(self):
        h=hit(extension='adoc', node_id='node')
        data={'status':'success','complete':True,'content':{'success':True,'nodeId':'node','markdown':'审批原文'}}
        with patch.object(dws_search,'run_dws',AsyncMock(return_value=data)) as run:
            result=await dws_search.fetch_online(h,'corp:user')
            self.assertEqual(result['content'],'审批原文'); self.assertFalse(result['partial'])
            self.assertEqual(run.call_args.args,(['doc','+fetch','--node','node'],'corp:user'))
            data['complete']=False
            self.assertTrue((await dws_search.fetch_online(h,'corp:user'))['partial'])
            data['content']['nodeId']='another-node'
            with self.assertRaises(dws_search.DWSError):
                await dws_search.fetch_online(h,'corp:user')

    async def test_adoc_missing_or_failed_body_is_not_evidence(self):
        h=hit(extension='adoc',node_id='node')
        for data in [{'status':'success','markdown':'错误层级'},
                     {'status':'failed','content':{'success':True,'nodeId':'node','markdown':'正文'}}]:
            with patch.object(dws_search,'run_dws',AsyncMock(return_value=data)):
                with self.assertRaises(dws_search.DWSError):
                    await dws_search.fetch_online(h,'corp:user')

    async def test_cancel_reaps_subprocess(self):
        started=asyncio.Event()
        async def read(_):
            started.set()
            await asyncio.Future()
        proc=SimpleNamespace(returncode=None,stdout=SimpleNamespace(read=read))
        proc.wait=AsyncMock(return_value=0)
        proc.kill=lambda: setattr(proc,'returncode',-9)
        with patch.object(dws_search.asyncio,'create_subprocess_exec',AsyncMock(return_value=proc)):
            task=asyncio.create_task(dws_search.run_dws(['profile','list']))
            await started.wait(); task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(proc.returncode,-9)
        proc.wait.assert_awaited()


class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_dify_lane_keeps_request_key_and_disabled_segments_out(self):
        calls=[]
        def handler(req):
            calls.append(req)
            return httpx.Response(200,json={'records':[
                {'segment':{'id':'enabled','content':'流程规定','document_id':'d','document':{'name':'制度'}}},
                {'segment':{'id':'disabled','content':'过期错误','enabled':False}},
            ]})
        retriever=EnterpriseRetriever({'base_url':'https://dify.test/v1','api_key':'scoped-key'},['dataset'],[],5)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),headers={'Authorization':'Bearer scoped-key'}) as client:
            rows=await retriever._dify_lane(client,'dataset','流程')
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]['content'],'流程规定')
        self.assertEqual(calls[0].headers['Authorization'],'Bearer scoped-key')

    async def test_dify_lane_sends_dataset_retrieval_config_with_rerank(self):
        sent=[]
        def handler(req):
            sent.append(req)
            return httpx.Response(200,json={'records':[]})
        retriever=EnterpriseRetriever({'base_url':'https://dify.test/v1','api_key':'k'},['dataset'],[],5)
        retriever._dataset_configs={'dataset':{'search_method':'hybrid_search','reranking_enable':True,
            'reranking_model':{'reranking_provider_name':'p','reranking_model_name':'r'},'top_k':5}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),headers={'Authorization':'Bearer k'}) as client:
            await retriever._dify_lane(client,'dataset','流程')
        import json as _json
        payload=_json.loads(sent[0].read())
        self.assertEqual(payload['retrieval_model']['search_method'],'hybrid_search')
        self.assertTrue(payload['retrieval_model']['reranking_enable'])
        self.assertEqual(payload['retrieval_model']['reranking_model']['reranking_model_name'],'r')

    async def test_fuse_score_mode_preserves_dify_rerank_order(self):
        low=hit('低分段', dataset_id='d', score=0.2)
        high=hit('高分段', dataset_id='d', score=0.9)
        merged=fuse([[low, high]], mode='score')  # 输入排名低分在前，Rerank 分应胜出
        self.assertEqual(merged[0]['content'],'高分段')
        self.assertAlmostEqual(merged[0]['fusion_score'],0.9)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def qa(self, local=None):
        retriever=SimpleNamespace(local=AsyncMock(return_value=local or []), hints=AsyncMock(return_value=[]),
                                  enrich_links=AsyncMock(side_effect=lambda x:x), errors=[])
        return EnterpriseQA(query='报销谁审批',history=[],llm_config={'api_key':'test'},
                            agent_config={'planning_enabled':False},retriever=retriever,user_id='u',role='editor')

    async def collect(self, qa):
        return [e async for e in _qa_events(qa)]

    async def test_no_evidence_falls_back_to_dws_then_abstains(self):
        qa=self.qa(); qa.structured=AsyncMock(return_value=Plan(question='报销谁审批',queries=['报销审批']))
        with patch.object(dws_search,'profile_for',AsyncMock(return_value='corp:u')), patch.object(dws_search,'search',AsyncMock(return_value=[])) as search:
            events=await self.collect(qa)
        search.assert_awaited_once()
        self.assertEqual(events[-1]['result']['answer_status'],'insufficient')
        self.assertEqual(events[-1]['result']['quality']['dws'],'empty')
        self.assertEqual(qa.structured.await_count,1) # no generation when no evidence

    async def test_force_retrieval_and_disabled_clarification_are_respected(self):
        qa=self.qa(); qa.config.update(retrieval_mode='force',tools_enabled={'dingtalk_search':False})
        qa.structured=AsyncMock(return_value=Plan(question='你好',intent='greeting'))
        result=(await self.collect(qa))[-1]['result']
        qa.retriever.local.assert_awaited_once()
        self.assertEqual(result['answer_status'],'insufficient')
        qa=self.qa(); qa.config['tools_enabled']={'ask_clarification':False}
        qa.structured=AsyncMock(return_value=Plan(question='它呢',intent='clarify'))
        self.assertEqual((await self.collect(qa))[-1]['result']['answer_status'],'insufficient')
        qa.retriever.local.assert_not_awaited()

    async def test_dws_hit_can_answer_without_dify(self):
        qa=self.qa()
        qa.structured=AsyncMock(side_effect=[Plan(question='报销谁审批'),
            Coverage(sufficient=True,selected_ids=['E1']),Draft(claims=[claim()]),Review(supported=True,complete=True)])
        with patch.object(dws_search,'profile_for',AsyncMock(return_value='corp:u')), patch.object(dws_search,'search',AsyncMock(return_value=[hit(source='dws')])):
            events=await self.collect(qa)
        result=events[-1]['result']
        self.assertEqual(result['answer_status'],'answered'); self.assertIn('[1]',result['answer'])
        self.assertEqual(result['quality']['dws'],'hit')

    async def test_adoc_read_timeout_keeps_search_excerpt_for_verification(self):
        qa=self.qa()
        qa.structured=AsyncMock(side_effect=[Plan(question='报销谁审批'),
            Coverage(sufficient=True,selected_ids=['E1']),Draft(claims=[claim()]),Review(supported=True,complete=True)])
        with patch.object(dws_search,'profile_for',AsyncMock(return_value='corp:u')), \
             patch.object(dws_search,'search',AsyncMock(return_value=[hit(source='dws',extension='adoc',node_id='node',partial=True)])), \
             patch.object(dws_search,'fetch_online',AsyncMock(side_effect=asyncio.TimeoutError)):
            result=(await self.collect(qa))[-1]['result']
        self.assertEqual(result['answer_status'],'answered')
        self.assertTrue(result['citations'][0]['partial'])
        self.assertIn('原文读取失败',''.join(result['quality']['warnings']))

    async def test_irrelevant_local_hits_trigger_dws(self):
        qa=self.qa(fuse([[hit()]]))
        qa.structured=AsyncMock(side_effect=[Plan(question='报销谁审批'),Coverage(missing=['对象不符'])])
        with patch.object(dws_search,'profile_for',AsyncMock(side_effect=dws_search.DWSError('身份未绑定'))):
            events=await self.collect(qa)
        self.assertEqual(events[-1]['result']['quality']['dws'],'unavailable')

    async def test_multi_topic_dws_preserves_title_and_separate_queries(self):
        qa=self.qa(); qa.query='入职指引的报销和制度入口'
        qa.structured=AsyncMock(return_value=Plan(question=qa.query, document_titles=['入职指引'],queries=['报销入口','制度入口']))
        with patch.object(dws_search,'profile_for',AsyncMock(return_value='corp:u')), patch.object(dws_search,'search',AsyncMock(return_value=[])) as search:
            await self.collect(qa)
        self.assertEqual([c.args[0] for c in search.await_args_list],['入职指引','报销入口','制度入口'])
        self.assertTrue(all(c.kwargs['profile']=='corp:u' for c in search.await_args_list))

    async def test_judge_error_is_not_sufficient(self):
        qa=self.qa(); qa.structured=AsyncMock(side_effect=ValueError('invalid json'))
        result=await qa.judge(Plan(question='问题'),fuse([[hit()]]))
        self.assertFalse(result.sufficient)

    async def test_correct_quote_with_wrong_claim_never_publishes(self):
        qa=self.qa(fuse([[hit()]]))
        qa.structured=AsyncMock(side_effect=[Plan(question='报销谁审批'),Coverage(sufficient=True,selected_ids=['E1']),
            Draft(claims=[claim(text='报销无需审批。')]),Review(supported=False,issues=['否定被篡改']),
            Draft(claims=[claim(text='报销无需审批。')]),Review(supported=False,issues=['否定被篡改'])])
        events=await self.collect(qa)
        self.assertEqual(events[-1]['result']['answer_status'],'insufficient')
        self.assertNotIn('无需审批',events[-1]['result']['answer'])
        self.assertFalse(any(e['type']=='answer_delta' for e in events))

    async def test_partial_answer_not_counted_as_complete_or_remembered(self):
        qa=self.qa(fuse([[hit()]])); qa.config['tools_enabled']={'dingtalk_search':False}
        qa.structured=AsyncMock(side_effect=[Plan(question='流程和金额'),Coverage(selected_ids=['E1'],missing=['缺少限额']),
            Draft(claims=[claim()]),Review(supported=True,complete=False,issues=['缺少限额'])])
        result=(await self.collect(qa))[-1]['result']
        self.assertEqual(result['answer_status'],'partial'); self.assertEqual(result['last_answer'],'')
        self.assertFalse(result['sufficiency']['sufficient'])

    async def test_cancel_propagates_instead_of_config_error(self):
        qa=self.qa(); qa.structured=AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):
            await self.collect(qa)


if __name__ == '__main__':
    unittest.main()
