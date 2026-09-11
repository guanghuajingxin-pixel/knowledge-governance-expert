"""Request-scoped retrieval; keyword and semantic lanes never share mutable credentials."""
from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

import httpx
from sqlalchemy import or_, select

from .evidence import fuse


def passages(hit: dict, query: str, max_passages: int = 3) -> list[dict]:
    text = hit.get("content") or ""
    if len(text) <= 3500:
        return [hit] if text.strip() else []
    # Overlapping windows preserve table row headers and nearby conditions. Truncation is explicit.
    windows = [(i, text[i:i + 3500]) for i in range(0, len(text), 3000)]
    tokens = re.findall(r"[a-zA-Z0-9_.-]+|[\u4e00-\u9fff]{2}", query.lower())
    ranked = sorted(windows, key=lambda w: sum(w[1].lower().count(t) for t in tokens), reverse=True)
    return [{**hit, "content": txt, "segment_id": f"{hit.get('segment_id', '')}:{offset}",
             "partial": True} for offset, txt in ranked[:max_passages]]


class EnterpriseRetriever:
    def __init__(self, dify: dict, dataset_ids: list[str], kb_ids: list[str], top_k: int):
        self.dify, self.dataset_ids, self.kb_ids = dify, dataset_ids, kb_ids
        self.top_k = min(20, max(1, top_k))
        self.errors: list[str] = []
        self._sem = asyncio.Semaphore(6)
        # 各知识库在 Dify 控制台保存的检索配置（含 Rerank 模型），首次检索时懒加载
        self._dataset_configs: dict[str, dict] | None = None

    async def local(self, queries: list[str]) -> list[dict]:
        rankings: list[list[dict]] = []
        dify_rankings: list[list[dict]] = []
        local_rankings: list[list[dict]] = []
        if self.dataset_ids and self.dify.get("api_key"):
            headers = {"Authorization": f"Bearer {self.dify['api_key']}"}
            async with httpx.AsyncClient(timeout=20, headers=headers) as client:
                await self._load_dataset_configs(client)
                tasks = [self._dify_lane(client, did, q)
                         for q in queries[:3] for did in self.dataset_ids]
                for result in await asyncio.gather(*tasks, return_exceptions=True):
                    if isinstance(result, BaseException):
                        self.errors.append("Dify 部分检索失败，请检查数据集权限和检索模型")
                    else:
                        dify_rankings.append(result)
            rankings.extend(dify_rankings)
        elif self.dataset_ids:
            self.errors.append("Dify 未配置，已尝试其他可用来源")
        if self.kb_ids:
            from kb_common.rag import searcher
            for q in queries[:3]:
                try:
                    hits = await asyncio.wait_for(searcher.hybrid(self.kb_ids, q, self.top_k, rerank=True), 30)
                    # ES may lag a soft-delete. Verify both current visibility and live DB state.
                    from kb_common.database import SessionLocal
                    from kb_common.models import Document
                    from uuid import UUID
                    ids = []
                    for h in hits:
                        try:
                            ids.append(UUID(str(h.get("document_id"))))
                        except ValueError:
                            continue
                    async with SessionLocal() as session:
                        docs = (await session.execute(select(Document).where(
                            Document.id.in_(ids), Document.kb_id.in_([UUID(k) for k in self.kb_ids]),
                            Document.is_deleted.is_(False),
                        ))).scalars().all()
                    allowed = {str(d.id): d for d in docs}
                    ranking = []
                    for h in hits:
                        doc = allowed.get(str(h.get("document_id")))
                        if doc:
                            ranking.extend(passages({**h, "content": h.get("text", ""), "source": "local",
                                                    "document_title": doc.original_filename}, q))
                    local_rankings.append(ranking)
                except Exception:
                    self.errors.append("本地知识库检索暂不可用")
            rankings.extend(local_rankings)
        # 仅单一 Dify 知识库有召回时：分数已由该知识库的 Rerank 模型打好，
        # 直接按 Rerank 分数与顺序合并，不做本地 RRF 融合
        datasets_in_hits = {h.get("dataset_id") for r in dify_rankings for h in r}
        if dify_rankings and not local_rankings and len(datasets_in_hits) == 1:
            return fuse(dify_rankings, limit=24, mode="score")
        return fuse(rankings, limit=24)

    async def _load_dataset_configs(self, client) -> None:
        """预取各知识库在 Dify 控制台保存的检索配置（含 Rerank 模型），仅放大 top_k 后复用。"""
        if self._dataset_configs is not None:
            return
        self._dataset_configs = {}

        async def one(did: str) -> None:
            try:
                resp = await client.get(f"{self.dify['base_url'].rstrip('/')}/datasets/{quote(did, safe='')}")
                resp.raise_for_status()
                raw = (resp.json() or {}).get("retrieval_model_dict")
                if not (isinstance(raw, dict) and raw.get("search_method")):
                    return
                cfg = {k: v for k, v in raw.items() if v not in (None, [], {})}
                rerank = raw.get("reranking_model") or {}
                if not (cfg.get("reranking_enable") and rerank.get("reranking_model_name")):
                    cfg.pop("reranking_model", None)
                cfg["top_k"] = max(int(cfg.get("top_k") or 0), self.top_k)
                self._dataset_configs[did] = cfg
            except Exception:
                return  # 拉取失败：检索时不传 retrieval_model，由 Dify 使用知识库自身默认配置

        await asyncio.gather(*(one(d) for d in self.dataset_ids))

    async def _dify_lane(self, client, did, query):
        async with self._sem:
            payload = {"query": query}
            # 复用知识库自身检索配置（检索方式、Rerank 模型、分数阈值均以控制台配置为准）
            cfg = (self._dataset_configs or {}).get(did)
            if cfg:
                payload["retrieval_model"] = cfg
            resp = await client.post(
                f"{self.dify['base_url'].rstrip('/')}/datasets/{quote(did, safe='')}/retrieve",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data.get("records"), list):
                raise ValueError("Missing records")
            hits = []
            for record in data["records"]:
                seg = record.get("segment") or {}
                if seg.get("enabled") is False or seg.get("status", "completed") != "completed":
                    continue
                doc = seg.get("document") or {}
                hit = {"content": seg.get("content") or "", "score": record.get("score", 0),
                       "document_id": seg.get("document_id") or doc.get("id", ""),
                       "document_title": doc.get("name", ""), "dataset_id": did,
                       "segment_id": seg.get("id", ""), "source": "dify", "partial": True}
                hits.extend(passages(hit, query))
            return hits

    async def hints(self, query: str, hits: list[dict]) -> list[str]:
        """Tags/summaries/graph only propose searches. Fetch live text before citing it."""
        if not self.dataset_ids:
            return []
        from kb_common.database import SessionLocal
        from kb_common.models import ProcessedDocument, KnowledgeRelation
        ids = [h["document_id"] for h in hits if h.get("document_id")]
        try:
            async with SessionLocal() as session:
                target_ids = []
                if ids:
                    relations = (await session.execute(select(KnowledgeRelation).where(
                        or_(KnowledgeRelation.source_doc_id.in_(ids), KnowledgeRelation.target_doc_id.in_(ids)),
                    ).order_by(KnowledgeRelation.weight.desc()).limit(12))).scalars().all()
                    target_ids = [r.target_doc_id if r.source_doc_id in ids else r.source_doc_id for r in relations]
                # Dataset boundary applies to graph expansion and metadata search alike.
                terms = re.findall(r"[A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", query)[:5]
                predicates = [ProcessedDocument.document_id.in_(target_ids)]
                for term in terms:
                    predicates += [ProcessedDocument.name.contains(term, autoescape=True),
                                   ProcessedDocument.summary.contains(term, autoescape=True),
                                   ProcessedDocument.tags.any(term), ProcessedDocument.keywords.any(term)]
                rows = (await session.execute(select(ProcessedDocument).where(
                    ProcessedDocument.dataset_id.in_(self.dataset_ids),
                    ProcessedDocument.process_status == "completed", or_(*predicates),
                ).order_by(ProcessedDocument.updated_at.desc()).limit(3))).scalars().all()
                return [r.name[:200] for r in rows]
        except Exception:
            self.errors.append("摘要与关系导航暂不可用，继续使用原文检索")
            return []

    async def enrich_links(self, hits: list[dict]) -> list[dict]:
        from kb_common.database import SessionLocal
        from kb_common.models import DifyDingtalkDocMapping
        ids = [h.get("document_id") for h in hits if h.get("source") == "dify"]
        if not ids:
            return hits
        try:
            async with SessionLocal() as session:
                rows = (await session.execute(select(DifyDingtalkDocMapping).where(
                    DifyDingtalkDocMapping.dify_document_id.in_(ids),
                    DifyDingtalkDocMapping.dify_dataset_id.in_(self.dataset_ids),
                ))).scalars().all()
                mapping = {r.dify_document_id: r for r in rows}
                for hit in hits:
                    row = mapping.get(hit.get("document_id"))
                    if row and hit.get("source") == "dify" and row.dify_dataset_id == hit.get("dataset_id"):
                        hit["url"], hit["node_id"] = row.dingtalk_url, row.dingtalk_node_id
        except Exception:
            self.errors.append("部分原文链接暂不可用")
        return hits
