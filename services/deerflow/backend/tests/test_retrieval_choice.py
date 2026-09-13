from types import SimpleNamespace
from unittest.mock import patch
import json
from langchain_core.messages import AIMessage, ToolMessage
from deerflow.agents.middlewares.exploration_timeout_middleware import ExplorationTimeoutMiddleware as Gate
from extensions import kb_tools
from app.qa_events import AnswerProjection


def setup_function():
    Gate._states.clear()


def choice(hits=None):
    Gate.begin('t', question='审批由谁负责')
    Gate.record_evidence('t', hits or [])
    msg = AIMessage(id='model1', content='', tool_calls=[{'id':'c1','name':'ask_clarification',
        'args':{'clarification_type':'approach_choice','question':'继续吗', 'confidence':88,
                'confidence_reason':'只覆盖部分条件', 'evidence_summary':'现有制度涉及审批流程，但没有明确负责人。'}}])
    return Gate().after_model({'messages':[msg]}, SimpleNamespace(context={'thread_id':'t'}))['messages'][0]


def test_no_network_before_consent_for_every_dingtalk_tool():
    Gate.begin('t')
    with patch.object(kb_tools.httpx, 'Client') as client:
        cfg={'configurable':{'thread_id':'t'}}
        for tool,args in [(kb_tools.dingtalk_search_tool,{'query':'审批'}),
                          (kb_tools.dingtalk_browse_tool,{'action':'map'}),
                          (kb_tools.dingtalk_read_doc_tool,{'node_id':'x'})]:
            assert 'error' in json.loads(tool.func(**args, config=cfg))
        client.assert_not_called()


def test_summary_score_and_buttons_are_emitted_before_consent():
    args=choice([{'document_title':'制度','content':'报销需要审批'}]).tool_calls[0]['args']
    assert args['choice_kind']=='dingtalk_opt_in'
    assert args['evidence_summary'].startswith('现有制度')
    assert args['confidence']==69
    assert args['options']==['继续从钉钉知识库探索','基于知识库内容回答']
    assert Gate.dingtalk_budget('t')==0


def test_no_evidence_never_has_positive_confidence():
    args=choice().tool_calls[0]['args']
    assert args['confidence']==0
    assert '未返回可用正文' in args['evidence_summary']


def test_timer_begins_only_after_opt_in_and_excludes_user_wait():
    clock='deerflow.agents.middlewares.exploration_timeout_middleware.time.monotonic'
    with patch(clock,return_value=100):
        choice()
    with patch(clock,return_value=5000):
        assert Gate()._due_action('t') is None
        Gate.begin('t','continue')
        assert 59 < Gate.dingtalk_budget('t') <= 60
    with patch(clock,return_value=5061):
        due=Gate()._short_circuit('t')
        assert due.result[0].tool_calls[0]['args']['choice_kind']=='exploration_timeout'
    with patch(clock,return_value=9000):
        Gate.begin('t','continue')
        assert Gate._states['t']['stage']=='second'
        assert Gate.dingtalk_budget('t')==300
    with patch(clock,return_value=9301):
        assert Gate()._due_action('t')[0]=='ask'


def test_stop_and_new_question_remove_permission():
    choice(); Gate.begin('t','continue'); assert Gate.dingtalk_budget('t')>0
    Gate.begin('t','stop'); assert Gate.dingtalk_budget('t')==0
    Gate.begin('t',question='新问题'); assert Gate.dingtalk_budget('t')==0
    Gate.begin('unknown','continue'); assert Gate.dingtalk_budget('unknown')==0


def test_old_parallel_prompt_is_restricted_to_knowledge_first():
    Gate.begin('t',question='原问题')
    msg=AIMessage(id='m',content='',tool_calls=[{'id':'d','name':'dingtalk_browse','args':{'action':'map'}}])
    updated=Gate().after_model({'messages':[msg]},SimpleNamespace(context={'thread_id':'t'}))['messages'][0]
    assert updated.tool_calls[0]['name']=='knowledge_search'
    assert updated.tool_calls[0]['args']['query']=='原问题'


def test_replaced_gate_is_projected_without_exposing_other_nodes():
    p=AnswerProjection('t'); p.feed('values',{'messages':[]})
    original=AIMessage(id='model1',content='',tool_calls=[{'id':'d','name':'dingtalk_search','args':{'query':'审批'}}])
    p.feed('updates',{'model':{'messages':[original]}})
    updated=choice()
    events=p.feed('values',{'messages':[updated,ToolMessage(id='tool',tool_call_id=updated.tool_calls[0]['id'],name='ask_clarification',content='等待选择')]})
    assert any(e['type']=='tool_start' and e['args'].get('choice_kind')=='dingtalk_opt_in' for e in events)
    assert p.finish(str) is None


def test_real_graph_pauses_before_network_and_stop_uses_existing_evidence():
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.tools import tool
    from langgraph.checkpoint.memory import InMemorySaver
    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
    from deerflow.tools.builtins.clarification_tool import ask_clarification_tool

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    calls=[]
    @tool
    def knowledge_search(query: str) -> str:
        """Search local knowledge."""
        calls.append('knowledge')
        Gate.record_evidence('t',[{'content':'报销需要审批','document_title':'制度'}])
        return '报销需要审批；未说明角色'

    @tool
    def dingtalk_search(query: str) -> str:
        """Search DingTalk after consent."""
        calls.append('dingtalk')
        return '角色原文'

    model=Model(responses=[
        AIMessage(id='m1',content='',tool_calls=[{'id':'c1','name':'dingtalk_search','args':{'query':'审批'}}]),
        AIMessage(id='m2',content='',tool_calls=[{'id':'c2','name':'ask_clarification','args':{'question':'继续吗','clarification_type':'approach_choice','evidence_summary':'制度规定报销需要审批，但未说明审批人。','confidence':30}}]),
        AIMessage(id='m3',content='制度规定报销需要审批，但尚不能确认审批人。'),
    ])
    graph=create_agent(model,tools=[knowledge_search,dingtalk_search,ask_clarification_tool],
                       middleware=[Gate(),ClarificationMiddleware()],checkpointer=InMemorySaver())
    cfg={'configurable':{'thread_id':'t'}}
    Gate.begin('t',question='审批人是谁')
    first=graph.invoke({'messages':[{'role':'user','content':'审批人是谁'}]},config=cfg,context={'thread_id':'t'})
    assert calls==['knowledge']
    assert first['messages'][-1].name=='ask_clarification'
    assert Gate._states['t']['stage']=='kb_choice'
    Gate.begin('t','stop')
    second=graph.invoke({'messages':[{'role':'user','content':'基于知识库内容回答'}]},config=cfg,context={'thread_id':'t'})
    assert calls==['knowledge']
    assert '尚不能确认' in second['messages'][-1].content


def test_empty_knowledge_cannot_skip_choice_by_returning_final_refusal():
    Gate.begin('t'); Gate.record_evidence('t',[])
    msg=AIMessage(id='m',content='未检索到任何内容。')
    result=Gate().after_model({'messages':[msg]},SimpleNamespace(context={'thread_id':'t'}))
    assert result['messages'][0].tool_calls[0]['args']['choice_kind']=='dingtalk_opt_in'
    assert result['messages'][0].tool_calls[0]['args']['confidence']==0


def test_http_stream_cleanup_preserves_opt_in_for_next_connection(monkeypatch):
    from fastapi.testclient import TestClient
    from app import qa_server
    monkeypatch.setattr(qa_server, 'CONFIG_PATH', SimpleNamespace(exists=lambda:True))
    resumed=[]
    def stream(body):
        if body.action:
            Gate.begin(body.thread_id, body.action)
            resumed.append(Gate.dingtalk_budget(body.thread_id)>0)
        else:
            choice()
        yield qa_server._sse({'type':'end'})
    monkeypatch.setattr(qa_server,'_event_stream',stream)
    with TestClient(qa_server.app) as client:
        result=client.post('/v1/chat/stream',json={'thread_id':'t','message':'问题'})
        assert result.status_code==200
        assert Gate.can_resume('t')  # A normal SSE close must not cancel a paused graph.
        result=client.post('/v1/chat/stream',json={'thread_id':'t','message':'继续','action':'continue'})
        assert result.status_code==200
        assert resumed==[True]


def test_expired_choice_returns_visible_error_instead_of_cancelled(monkeypatch):
    from fastapi.testclient import TestClient
    from app import qa_server
    monkeypatch.setattr(qa_server, 'CONFIG_PATH', SimpleNamespace(exists=lambda:True))
    choice(); Gate.request_cancel('t')
    with TestClient(qa_server.app) as client:
        result=client.post('/v1/chat/stream',json={'thread_id':'t','message':'继续','action':'continue'})
    assert '已过期' in result.text
    assert 'cancelled' not in result.text
