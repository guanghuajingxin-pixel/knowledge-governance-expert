import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException

from app.routes import search


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_scope_and_memory_settings_are_applied_per_request(self):
        user=SimpleNamespace(id=uuid4(),role='editor')
        empty=SimpleNamespace(scalar_one_or_none=lambda:None)
        session=SimpleNamespace(execute=AsyncMock(return_value=empty))
        cfg={'top_k':7,'long_memory_enabled':False}
        with patch('app.services.agent.config.load_agent_config',AsyncMock(return_value=cfg)), \
             patch('app.services.llm_resolver.resolve_llm_config',AsyncMock(return_value={'api_key':'test'})):
            qa=await search._prepare_qa(search.ChatIn(query='审批条件',dify_dataset_ids=[],
                history=[{'role':'assistant','content':'上一轮未经核验的结论'}]),user,session)
            self.assertEqual(qa.history,[])
            self.assertEqual(qa.retriever.dataset_ids,[])
            self.assertEqual(qa.retriever.top_k,7)
            deep=await search._prepare_qa(search.ChatIn(query='审批条件',dify_dataset_ids=[],top_k=2,deep_think=True),user,session)
            self.assertEqual(deep.retriever.top_k,12)
            with self.assertRaises(HTTPException) as err:
                await search._prepare_qa(search.ChatIn(query='审批条件',dify_dataset_ids=[uuid4()]),user,session)
            self.assertEqual(err.exception.status_code,403)

    async def test_session_owner_is_verified_before_using_conversation(self):
        user=SimpleNamespace(id=uuid4(),role='editor')
        session=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda:None)))
        with patch('app.services.agent.config.load_agent_config',AsyncMock(return_value={})), \
             patch('app.services.llm_resolver.resolve_llm_config',AsyncMock(return_value={'api_key':'test'})), \
             patch('app.routes.chat_session_route._get_owned',AsyncMock(side_effect=HTTPException(404,'会话不存在'))):
            with self.assertRaises(HTTPException) as err:
                await search._prepare_qa(search.ChatIn(query='上一条是谁',session_id='another-session',dify_dataset_ids=[]),user,session)
            self.assertEqual(err.exception.status_code,404)

    async def test_json_and_stream_use_same_engine_and_final_contract(self):
        app=FastAPI(); app.include_router(search.router)
        app.dependency_overrides[search.get_principal]=lambda:SimpleNamespace(id='user',role='editor')
        app.dependency_overrides[search.get_session]=lambda:None
        expected={'answer':'已核实的事实 [1]','answer_status':'answered','citations':[]}
        async def events(_):
            yield {'type':'step','node':'retrieve','title':'检索','detail':'开始'}
            yield {'type':'final','result':expected}
        with patch.object(search,'_prepare_qa',AsyncMock(return_value=object())) as prepare, patch.object(search,'_qa_events',events), patch.object(search,'_log_usage'):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                ordinary=await client.post('/api/v1/search/chat',json={'query':'制度问题'})
                stream=await client.post('/api/v1/search/chat/stream',json={'query':'制度问题'})
            self.assertEqual(ordinary.json(),expected)
            chunks=[json.loads(c[6:]) for c in stream.text.strip().split('\n\n')]
            self.assertEqual(chunks[-1],{'type':'final','result':expected})
            self.assertEqual(prepare.await_count,2)

    async def test_cancel_cannot_cancel_another_users_session(self):
        sleeper=asyncio.create_task(asyncio.sleep(100))
        search._ACTIVE_QA[('owner','session')]=sleeper
        try:
            result=await search.chat_cancel(search.ChatCancelIn(session_id='session'),SimpleNamespace(id='other'))
            self.assertFalse(result['cancelled']); self.assertFalse(sleeper.cancelled())
            result=await search.chat_cancel(search.ChatCancelIn(session_id='session'),SimpleNamespace(id='owner'))
            self.assertTrue(result['cancelled'])
        finally:
            sleeper.cancel(); await asyncio.gather(sleeper,return_exceptions=True)
            search._ACTIVE_QA.clear()


if __name__=='__main__':
    unittest.main()
