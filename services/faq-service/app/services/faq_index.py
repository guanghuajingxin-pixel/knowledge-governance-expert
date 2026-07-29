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

async def index_entry(kb, entry):
    vec = (await _embed([entry.question]))[0]
    index = await es_client.ensure_index(str(kb.id))
    doc = {
        "text": entry.question, "vector": vec,
        "kb_id": str(kb.id), "kb_type": "FAQ",
        "faq_entry_id": str(entry.id), "source_type": "FAQ",
        "document_title": entry.question, "faq_answer": entry.answer,
        "directory_id": str(entry.directory_id) if entry.directory_id else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await es_client.es.index(index=index, id=f"faq_{entry.id}", document=doc, refresh=True)

async def delete_entry(kb_id, entry_id):
    index = f"kb_{kb_id.replace('-', '')}"
    if await es_client.es.indices.exists(index=index):
        try: await es_client.es.delete(index=index, id=f"faq_{entry_id}", refresh=True)
        except Exception: pass
