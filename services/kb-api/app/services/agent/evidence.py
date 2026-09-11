"""Evidence identities and deterministic citation checks shared by QA and evaluation."""
from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import urlparse


def safe_url(value: str) -> str:
    try:
        parsed = urlparse(value or "")
    except ValueError:
        return ""
    return value if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username else ""


def normalize(text: str) -> str:
    # Ignore presentation escapes/emphasis, never words, numbers, negation or units.
    text = html.unescape(text or "")
    text = re.sub(r"\\([\\`*_{}\[\]()#+.!>|-])", r"\1", text)
    text = text.replace("**", "")
    return re.sub(r"\s+", "", text)


def identity(hit: dict) -> str:
    # Never deduplicate on the first 80 characters: templates share long prefixes.
    source = hit.get("dataset_id") or hit.get("kb_id") or hit.get("source") or ""
    document = hit.get("document_id") or hit.get("node_id") or ""
    digest = hashlib.sha256(normalize(hit.get("content", "")).encode()).hexdigest()
    return f"{source}:{document}:{digest}"


def fuse(rankings: list[list[dict]], limit: int = 24, per_doc: int = 4, mode: str = "rrf") -> list[dict]:
    """合并多路召回。

    mode=rrf（默认）：跨知识库/本地多源融合，按排名倒数计分，与各源分数体系无关。
    mode=score：单一 Dify 知识库召回时使用——分数即该知识库 Rerank 模型的打分，
    直接按分数排序并取多查询下的最高分，保留 Dify 已重排好的顺序。
    """
    scores, items = {}, {}
    for ranking in rankings:
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            if not (hit.get("content") or "").strip():
                continue
            key = identity(hit)
            if key in seen:
                continue
            seen.add(key)
            if mode == "score":
                scores[key] = max(scores.get(key, 0.0), float(hit.get("score") or 0.0))
            else:
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
            items[key] = hit
    counts, selected, used_chars = {}, [], 0
    for key in sorted(scores, key=scores.get, reverse=True):
        hit = dict(items[key])
        if used_chars + len(hit["content"]) > 32000:
            continue
        doc = (hit.get("dataset_id") or hit.get("source"), hit.get("document_id"))
        if counts.get(doc, 0) >= per_doc:
            continue
        counts[doc] = counts.get(doc, 0) + 1
        hit["fusion_score"] = scores[key]  # rrf 模式为排名分；score 模式为知识库 Rerank 分，均非置信度
        hit["evidence_id"] = f"E{len(selected) + 1}"
        selected.append(hit)
        used_chars += len(hit["content"])
        if len(selected) >= limit:
            break
    return selected


def context(evidence: list[dict]) -> str:
    import json
    return json.dumps([{
        "id": h["evidence_id"], "title": h.get("document_title", ""),
        "source": h.get("source", "dify"), "partial": h.get("partial", False),
        "content": h["content"],
    } for h in evidence], ensure_ascii=False)


def validate_claims(claims: list, evidence: list[dict]) -> list[str]:
    """Exact quotes are necessary, but entailment is checked separately by a reviewer."""
    by_id = {h["evidence_id"]: h for h in evidence}
    errors = []
    for i, claim in enumerate(claims, 1):
        if not claim.text.strip() or not claim.supports:
            errors.append(f"论断{i}缺少证据")
        # Only the server emits citations/links; disallow invented markdown references.
        if re.search(r"\[[^\]]*\]|https?://|<[^>]+>", claim.text):
            errors.append(f"论断{i}包含自行生成的引用或链接")
        for support in claim.supports:
            hit = by_id.get(support.evidence_id)
            quote = normalize(support.quote)
            if not hit or len(quote) < 4 or quote not in normalize(hit["content"]):
                errors.append(f"论断{i}引用原文不匹配")
    return errors


def render_claims(claims: list, evidence: list[dict]) -> tuple[str, list[dict]]:
    by_id = {h["evidence_id"]: h for h in evidence}
    numbers, citations, lines = {}, [], []
    for claim in claims:
        refs = []
        for support in claim.supports:
            key = support.evidence_id
            if key not in numbers:
                h = by_id[key]
                numbers[key] = len(citations) + 1
                citations.append({
                    **h, "citation_id": numbers[key], "text": h["content"],
                    "quote": support.quote, "chunk_id": h.get("segment_id") or key,
                    "url": safe_url(h.get("url", "")), "source_type": "DOCUMENT",
                    "page_number": h.get("page_number"),
                })
            citation = citations[numbers[key] - 1]
            quotes = citation.setdefault("quotes", [])
            if support.quote not in quotes:
                quotes.append(support.quote)
                citation["quote"] = "\n\n".join(quotes)
            if numbers[key] not in refs:
                refs.append(numbers[key])
        lines.append(claim.text.strip() + " " + "".join(f"[{n}]" for n in refs))
    return "\n\n".join(lines), citations
