from kb_common.rag import searcher, tracer
from kb_common.clients import llm_client
from kb_common.config import get_settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from kb_common.models import Document, Setting
import logging

logger = logging.getLogger(__name__)

SYS_PROMPT = "你是一个严谨的知识库问答助手。只根据下方【参考资料】回答问题。"
TMPL = """【参考资料】
{ctx}

【问题】{q}

要求：
1. 仅依据参考资料作答，不要编造。
2. 在答案末尾用 [1][2]... 标注引用的资料编号。
3. 资料不足时回答"根据现有知识库无法回答"。
"""


async def _effective(s: AsyncSession, key: str) -> str:
    row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return (row.value if row else None) or getattr(get_settings(), key)


async def answer(query: str, kb_ids: list[str], top_k: int, s: AsyncSession) -> dict:
    hits = await searcher.hybrid(kb_ids, query, top_k, rerank=True)
    doc_ids = {h.get("document_id") for h in hits if h.get("document_id")}
    docs = (await s.execute(select(Document).where(Document.id.in_(doc_ids)))).scalars().all()
    dmap = {str(d.id): (d.original_filename, d.storage_path, d.file_type) for d in docs}
    cited = [tracer.trace(h, dmap) for h in hits]

    ctx = "\n\n".join(f"[{i+1}] ({c['document_title']} p.{c['page_number']})\n{c['text']}"
                      for i, c in enumerate(cited)) or "（无相关资料）"
    messages = [{"role": "system", "content": SYS_PROMPT},
                {"role": "user", "content": TMPL.format(ctx=ctx, q=query)}]
    base_url = await _effective(s, "llm_base_url")
    api_key = await _effective(s, "llm_api_key")
    model = await _effective(s, "llm_model")
    try:
        ans = await llm_client.chat(messages, model=model, base_url=base_url, api_key=api_key)
    except Exception as e:
        # 服务端记录原始异常（含上游状态/响应体），对客户端返回固定友好提示避免信息泄漏
        logger.warning("LLM chat failed: %s", e)
        ans = "（LLM 问答暂不可用，请在 设置 页检查 LLM API Key 配置。）"
    return {"answer": ans, "citations": cited}
