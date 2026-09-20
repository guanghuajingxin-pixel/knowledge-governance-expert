"""Shared retrieval kernel backed by the vendored RAGFlow query implementation."""
import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from .ragflow_nlp.query import FulltextQueryer
from .ragflow_nlp import rag_tokenizer


@lru_cache(maxsize=1)
def queryer() -> FulltextQueryer:
    return FulltextQueryer()


@lru_cache(maxsize=4096)
def tokens(text: str) -> tuple[str, ...]:
    return tuple(rag_tokenizer.tokenize(text).split())


@dataclass(frozen=True)
class Query:
    text: str
    expression: str
    keywords: tuple[str, ...]
    scoring_keywords: tuple[str, ...]


@lru_cache(maxsize=256)
def prepare_query(text: str) -> Query:
    expression, keywords = queryer().question(text, min_match=0.3)
    # Upstream question() keywords include an unsegmented phrase and reorder
    # terms by weight. Those are recall expansions, not the original phrase
    # order required by token_similarity's adjacency weights. Keep them for
    # recall, but score the cleaned query in its actual token order.
    normalized = rag_tokenizer.tradi2simp(rag_tokenizer.strQ2B(text.lower()))
    cleaned = queryer().rmWWW(queryer().add_space_between_eng_zh(normalized))
    score_terms = tuple(queryer().tw.pretoken(cleaned, num=True))
    return Query(text, expression.matching_text if expression else '', tuple(keywords), score_terms)


def document_tokens(text: str, title: str = '', keywords=()) -> list[str]:
    # Ported from RAGFlow Dealer.rerank: preserve first occurrence order, boost
    # title/important keywords. Do not concatenate natural text across fields.
    return list(dict.fromkeys(tokens(text))) + list(tokens(title)) * 2 + list(keywords) * 5


def term_scores(query: Query, documents: list[list[str]]) -> list[float]:
    if not query.scoring_keywords:
        return [0.0] * len(documents)
    return [float(s) for s in queryer().token_similarity(query.scoring_keywords, documents)]


def rerank_term_scores(query: str, hits: list[dict]) -> list[float]:
    # RAGFlow rerank_by_model keeps natural token order and does not repeat fields.
    fields = [list(tokens(h.get('matched_content', h.get('text', h.get('content', '')))))
              + list(tokens(h.get('document_title', '')))
              + list(h.get('important_keywords') or []) for h in hits]
    return term_scores(prepare_query(query), fields)


def term_similarity(query: str, text: str) -> float:
    return term_scores(prepare_query(query), [document_tokens(text)])[0]


def cosine(a, b) -> float:
    if not a or len(a) != len(b) or not all(math.isfinite(v) for v in [*a, *b]):
        raise ValueError('向量维度不一致或包含无效值')
    norm = math.sqrt(sum(v*v for v in a) * sum(v*v for v in b))
    if not norm:
        raise ValueError('模型返回了零向量')
    return max(-1.0, min(1.0, sum(x*y for x, y in zip(a, b)) / norm))


def blend(token: float, semantic: float, weight: float) -> float:
    """RAGFlow rerank_with_knn / rerank_by_model formula; never rank-normalize."""
    if not 0 <= weight <= 1 or not all(math.isfinite(s) for s in (token, semantic)):
        raise ValueError('无效的检索权重或分数')
    return (1 - weight) * token + weight * semantic


def apply_rerank(hits: list[dict], rows: list[dict], weight: float = 0.7) -> None:
    """Validate the entire response before modifying hits; preserve raw scores."""
    scores = {}
    for row in rows:
        index, score = row.get('index'), row.get('relevance_score')
        if type(index) is not int or not 0 <= index < len(hits) or index in scores:
            raise ValueError('重排模型返回无效或重复索引')
        if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('重排模型必须返回 0～1 的 relevance_score')
        scores[index] = float(score)
    if len(scores) != len(hits):
        raise ValueError('重排模型未返回完整候选评分')
    for i, hit in enumerate(hits):
        effective_weight = hit.get('semantic_weight', weight)
        hit.update(retrieval_score=hit['score'], rerank_score=scores[i],
                   score=blend(hit['token_similarity'], scores[i], effective_weight),
                   score_type='ragflow_rerank', semantic_weight=effective_weight)


def lexical_candidates(query: Query, documents: list[dict], limit: int) -> list[int]:
    """BM25 candidate recall for SQL-backed chunks; final score is RAGFlow's.

    RAGFlow's query field boosts (content=2, title=10, important keywords=30)
    are applied at recall time. BM25 is never presented as cosine similarity.
    """
    if not query.keywords or not documents:
        return []
    query_weights = queryer().tw.weights(list(query.keywords), preprocess=False)
    fields = [(Counter(tokens(d['text'])), Counter(tokens(d.get('title', ''))),
               Counter(t for k in d.get('keywords', []) for t in tokens(k))) for d in documents]
    lengths = [[sum(field.values()) for field in row] for row in fields]
    averages = [sum(length[j] for length in lengths) / len(fields) or 1 for j in range(3)]
    df = Counter(t for row in fields for t in set().union(*(set(f) for f in row)))
    scores = []
    for i, row in enumerate(fields):
        score = 0.0
        for term, weight in query_weights:
            idf = math.log(1 + (len(fields) - df[term] + .5) / (df[term] + .5))
            for j, boost in enumerate((2, 10, 30)):
                tf = row[j][term]
                if tf:
                    norm = tf + 1.2 * (.25 + .75 * lengths[i][j] / averages[j])
                    score += weight * idf * boost * tf * 2.2 / norm
        if score > 0:
            scores.append((i, score))
    return [i for i, _ in sorted(scores, key=lambda pair: (-pair[1], pair[0]))[:limit]]
