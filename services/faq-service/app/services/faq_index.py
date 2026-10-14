"""FAQ 条目向量化索引：主问题与每条相似问各写一条 ES 文档（faq_entry_id 相同）。

检索命中任意相似问文档即通过 faq_entry_id 关联回主问题与答案；
document_title 恒存标准问题，保证召回结果展示口径统一。
"""
import httpx
from kb_common.clients import es_client
from kb_common.config import get_settings
from datetime import datetime, timezone

async def _embed(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{s.kb_api_internal_url}/internal/embed", json={"texts": texts})
        r.raise_for_status()
        return r.json()["vectors"]

def _doc(kb, entry, text: str, vec: list[float]) -> dict:
    return {
        "text": text, "vector": vec,
        "kb_id": str(kb.id), "kb_type": "FAQ",
        "faq_entry_id": str(entry.id), "source_type": "FAQ",
        "document_title": entry.question, "faq_answer": entry.answer,
        "directory_id": str(entry.directory_id) if entry.directory_id else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

async def index_entry(kb, entry):
    """（重新）索引问答：先清该条目全部旧文档，再写入主问题 + 相似问。"""
    texts = [entry.question] + list(entry.similar_questions or [])
    vecs = await _embed(texts)
    index = await es_client.ensure_index(str(kb.id))
    # 清旧文档（覆盖主问题及历史相似问），避免编辑后残留已删除/改写的问题变体
    await es_client.es.delete_by_query(
        index=index, body={"query": {"term": {"faq_entry_id": str(entry.id)}}},
        conflicts="proceed", refresh=True)
    for i, (text, vec) in enumerate(zip(texts, vecs)):
        doc_id = f"faq_{entry.id}" if i == 0 else f"faq_{entry.id}_s{i}"
        await es_client.es.index(index=index, id=doc_id,
                                 document=_doc(kb, entry, text, vec), refresh=True)

async def delete_entry(kb_id, entry_id):
    """删除条目全部索引文档（主问题 + 相似问）。"""
    index = f"kb_{kb_id.replace('-', '')}"
    if await es_client.es.indices.exists(index=index):
        try:
            await es_client.es.delete_by_query(
                index=index, body={"query": {"term": {"faq_entry_id": str(entry_id)}}},
                conflicts="proceed", refresh=True)
        except Exception:
            pass
