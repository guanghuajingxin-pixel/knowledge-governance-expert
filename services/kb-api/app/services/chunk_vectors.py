"""文档库分段持久化索引（向量 + 词项）的读取、缓存、自愈与回填。

检索链路（library_retrieval.search）只 embed 查询语句本身；分段向量从
library_chunk_embeddings 表读取，按库聚合成 numpy 矩阵打分（毫秒级），
取代旧「每次查询整库实时 embed」（大库 15k 分段需数分钟，必然超时）。

词项召回同理：分段分词结果持久化在 library_chunk_tokens（弱 CPU 服务器上
15k 分段实时分词需 5 分钟+，BM25 召回必然超时），查询期只做 BM25 打分。

- 缓存：进程内按库 LRU（bytes 预算 LIBRARY_VECTOR_CACHE_MB，0=禁用），
  失效指纹 = (合格叶子数, 新鲜向量数, max(updated_at), model)，
  每次检索固定 +1 条聚合 SQL（毫秒级）。
- 打分按「当前 leaves ∩ 缓存 fresh_ids」取行：指纹碰撞只会损失性能不会出错
  （已删 chunk 的残留向量不会进入结果；新增 chunk 走缺失自愈）。
- 自愈：缺失 ≤256 时现场补 embed/分词并经独立 SessionLocal 回写（不碰调用方事务）。
- 回填：backfill() 供 CLI（scripts/backfill_chunk_embeddings.py）与运维调用。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from kb_common.database import SessionLocal
from kb_common.models import (KnowledgeLibrary, LibraryChunk, LibraryChunkEmbedding,
                              LibraryChunkToken, LibraryDocument)
from kb_common.rag.scoring import (lexical_candidates_from_fields, matrix_cosine,
                                   pack_vector, tokens, unpack_matrix)

logger = logging.getLogger(__name__)

# 单库窗口式拉取向量的行数（2000×10KB≈20MB/窗）
_LOAD_WINDOW = 2000
# 查询期自愈上限：超过则视为「未回填/模型已变更」，本轮缺失分段仅词项召回
_SELFHEAL_LIMIT = 256
# 分段向量截断上限：与 rerank 同口径（bge 系上下文 8192 token，中文约 1 字 1 token；
# 实测存在 8M 字符的病态分段，超限内容 embedding 服务直接 400 拒绝）
_EMBED_MAX_CHARS = 4000
# 词项回填批大小：本地 CPU 分词无 API 约束，大批减少往返
_TOKEN_BATCH = 200


def embed_text(content: str) -> str:
    """分段向量输入截断：超长病态分段取段首，保证可嵌入（词项检索不受影响）。"""
    return content[:_EMBED_MAX_CHARS]


@dataclass
class _Entry:
    library_id: int
    model: str
    fingerprint: tuple          # (叶子数, 新鲜向量数, max_updated_at)
    ids: dict = field(default_factory=dict)   # chunk_id -> 矩阵行号
    matrix: object = None       # np.ndarray (n, dim) float32
    nbytes: int = 0


_cache: OrderedDict[int, _Entry] = OrderedDict()


def _budget() -> int:
    from kb_common.config import get_settings
    return get_settings().library_vector_cache_mb * 1024 * 1024


def _cache_size() -> int:
    return sum(e.nbytes for e in _cache.values())


def _cache_put(entry: _Entry) -> None:
    budget = _budget()
    if budget <= 0 or entry.nbytes > budget:
        return  # 0 预算=禁用；单库超预算不缓存（每次直读，仍可用）
    _cache[entry.library_id] = entry
    while _cache_size() > budget:
        _cache.popitem(last=False)


def _cache_get(library_id: int, model: str, fingerprint: tuple) -> _Entry | None:
    entry = _cache.get(library_id)
    if entry is not None and entry.model == model and entry.fingerprint == fingerprint:
        _cache.move_to_end(library_id)
        return entry
    return None


def _leaf_ids(library_id: int):
    """合格叶子分段 id 集合：判定口径与 library_retrieval.search 逐字对齐
    （enabled 文档 + available 分段 + 非父块 + 父块在集合内）。"""
    eligible = (select(LibraryChunk.id.label('cid'), LibraryChunk.parent_id.label('pid'))
                .join(LibraryDocument, LibraryDocument.id == LibraryChunk.document_id)
                .where(LibraryDocument.library_id == library_id,
                       LibraryDocument.enabled.is_(True),
                       LibraryChunk.available.is_(True))
                .subquery())
    parents = select(eligible.c.pid).where(eligible.c.pid.isnot(None))
    return (select(eligible.c.cid)
            .where(eligible.c.cid.not_in(parents),
                   or_(eligible.c.pid.is_(None),
                       eligible.c.pid.in_(select(eligible.c.cid)))))


async def _fingerprint(session, library_id: int, model: str) -> tuple:
    """失效指纹：任何增删分段/文档开关/向量回写/模型切换都会改变其中至少一项。"""
    leaf_sq = _leaf_ids(library_id).subquery()
    emb = LibraryChunkEmbedding
    q = (select(func.count(leaf_sq.c.cid),
                func.count(emb.chunk_id).filter(emb.model == model),
                func.max(emb.updated_at).filter(emb.model == model))
         .select_from(leaf_sq)
         .outerjoin(emb, emb.chunk_id == leaf_sq.c.cid))
    row = (await session.execute(q)).one()
    return (row[0], row[1], row[2])


async def _build_entry(session, library_id: int, model: str, fingerprint: tuple) -> _Entry:
    """窗口式拉取该库全部新鲜向量，聚合成单个矩阵（SQL 端过滤 stale 行）。"""
    entry = _Entry(library_id=library_id, model=model, fingerprint=fingerprint)
    emb = LibraryChunkEmbedding
    windows: list = []   # [(起始行号, 矩阵), ...]
    count = 0
    last: uuid.UUID | None = None
    while True:
        q = (select(emb.chunk_id, emb.embedding)
             .where(emb.model == model, emb.chunk_id.in_(_leaf_ids(library_id)))
             .order_by(emb.chunk_id)
             .limit(_LOAD_WINDOW))
        if last is not None:
            q = q.where(emb.chunk_id > last)
        rows = (await session.execute(q)).all()
        if not rows:
            break
        last = rows[-1][0]
        dim = len(rows[0][1]) // 4
        matrix = unpack_matrix([r[1] for r in rows], dim)
        if matrix is None:
            logger.warning("库 %s 存在维度异常的向量行（chunk %s 起），本窗口跳过",
                           library_id, rows[0][0])
            continue
        for r in rows:
            entry.ids[r[0]] = count
            count += 1
        windows.append(matrix)
    if windows:
        import numpy as np
        entry.matrix = np.vstack(windows) if len(windows) > 1 else windows[0]
        entry.nbytes = entry.matrix.nbytes + len(entry.ids) * 64
    return entry


async def upsert_embeddings(session, items: list[tuple[uuid.UUID, str, bytes]]) -> None:
    """批量写入向量行（同 chunk_id 覆盖 model/embedding/updated_at）。"""
    if not items:
        return
    stmt = pg_insert(LibraryChunkEmbedding).values(
        [{"chunk_id": cid, "model": model, "embedding": blob} for cid, model, blob in items])
    stmt = stmt.on_conflict_do_update(
        index_elements=['chunk_id'],
        set_={"model": stmt.excluded.model, "embedding": stmt.excluded.embedding,
              "updated_at": func.now()})
    await session.execute(stmt)


# ===== 词项持久化（BM25 召回不再整库实时分词）=====

def token_dict(text: str, title: str, keywords: list) -> dict:
    """三字段词频字典（正文/标题/关键词），形态与 lexical_candidates 的
    Counter 字段一致（dict(Counter)），BM25 打分可直接查找。"""
    return {"t": dict(Counter(tokens(text))),
            "h": dict(Counter(tokens(title))),
            "k": dict(Counter(t for k in keywords or [] for t in tokens(k)))}


def build_token_rows(leaf_chunks, title: str) -> list:
    """入库钩子用：叶子分段 → [(chunk_id, token_dict)]。

    词项链路与检索同口径：正文取 retrieval_text(content, enhancements)
    （增强信息参与词项召回），标题为文档名。纯 CPU，调用方建议 to_thread。
    """
    from app.services.knowledge_engines.chunk_enhancer import retrieval_text
    return [(c.id, token_dict(retrieval_text(c.content, c.retrieval_enhancements or {}),
                              title, c.important_keywords or []))
            for c in leaf_chunks]


async def upsert_tokens(session, items: list[tuple[uuid.UUID, dict]]) -> None:
    """批量写入词项行（同 chunk_id 覆盖 tokens/updated_at）。"""
    if not items:
        return
    stmt = pg_insert(LibraryChunkToken).values(
        [{"chunk_id": cid, "tokens": tok} for cid, tok in items])
    stmt = stmt.on_conflict_do_update(
        index_elements=['chunk_id'],
        set_={"tokens": stmt.excluded.tokens, "updated_at": func.now()})
    await session.execute(stmt)


async def lexical_candidates_db(session, library_id: int, prepared, leaves, texts,
                                recall_count: int) -> list[int]:
    """持久化词项召回：读 library_chunk_tokens 做 BM25，返回 leaves 下标列表。

    缺失 ≤_SELFHEAL_LIMIT 现场分词自愈回写（独立会话）；更大缺失（未回填）
    告警并跳过这些分段的词项召回（不阻塞、不超时；向量召回不受影响）。
    """
    tk = LibraryChunkToken
    rows = (await session.execute(
        select(tk.chunk_id, tk.tokens).where(tk.chunk_id.in_(_leaf_ids(library_id)))
    )).all()
    covered = {cid: tok for cid, tok in rows if isinstance(tok, dict)}

    fields, indices, missing_idx = [], [], []
    for i, (c, _) in enumerate(leaves):
        tok = covered.get(c.id)
        if tok is not None:
            fields.append((tok.get('t') or {}, tok.get('h') or {}, tok.get('k') or {}))
            indices.append(i)
        else:
            missing_idx.append(i)
    if missing_idx:
        if len(missing_idx) <= _SELFHEAL_LIMIT:
            try:
                built = await asyncio.to_thread(
                    lambda: [(leaves[i][0].id,
                              token_dict(texts[i]['text'], texts[i]['title'],
                                         texts[i].get('keywords') or []))
                             for i in missing_idx])
                async with SessionLocal() as ws:
                    await upsert_tokens(ws, built)
                    await ws.commit()
                for (cid, tok) in built:
                    fields.append((tok['t'], tok['h'], tok['k']))
                indices.extend(missing_idx)
            except Exception as e:  # noqa: BLE001 - 自愈失败本轮这些分段不参与词项召回
                logger.warning("库 %s %d 个缺失词项自愈失败: %s", library_id, len(missing_idx), e)
        else:
            logger.warning("库 %s 有 %d 个分段无词项统计（未回填，请运行 "
                           "scripts/backfill_chunk_embeddings.py --scope tokens），"
                           "本轮这些分段不参与词项召回", library_id, len(missing_idx))
    cands = await asyncio.to_thread(lexical_candidates_from_fields, prepared, fields, recall_count)
    return [indices[k] for k in cands]


async def _selfheal(missing: list, cfg: dict) -> list[tuple[uuid.UUID, str, bytes]]:
    """现场补 embed 缺失分段并回写（独立短会话，不碰调用方事务）。"""
    from app.services.library_retrieval import embeddings
    vectors = await embeddings([embed_text(c.content) for c, _ in missing], cfg)
    items = [(c.id, cfg['model'], pack_vector(v))
             for (c, _), v in zip(missing, vectors) if v]
    async with SessionLocal() as ws:
        await upsert_embeddings(ws, items)
        await ws.commit()
    return items


def _entry_append(entry: _Entry, items: list[tuple[uuid.UUID, str, bytes]]) -> None:
    """自愈结果并入缓存 entry（新建数组，不原地改共享矩阵；单事件循环内无锁）。

    已存在的 chunk_id 跳过（自愈竞态下重复回写不产生重复矩阵行）。
    """
    items = [it for it in items if it[0] not in entry.ids]
    if not items:
        return
    import numpy as np
    dim = len(items[0][2]) // 4
    fresh = unpack_matrix([b for _, _, b in items], dim)
    if fresh is None:
        return
    if entry.matrix is None:
        entry.matrix, offset = fresh, 0
    else:
        if entry.matrix.shape[1] != dim:
            logger.warning("自愈向量维度与缓存矩阵不一致，忽略本批自愈并入")
            return
        offset = entry.matrix.shape[0]
        entry.matrix = np.vstack([entry.matrix, fresh])
    for cid, _, _ in items:
        entry.ids[cid] = offset
        offset += 1
    entry.nbytes = entry.matrix.nbytes + len(entry.ids) * 64


async def dense_scores(session, library_id: int, cfg: dict, query_vec, leaves) -> dict:
    """返回 {chunk_id: 余弦相似度}，仅覆盖当前 leaves 与新鲜向量的交集。"""
    model = cfg['model']
    fingerprint = await _fingerprint(session, library_id, model)
    entry = _cache_get(library_id, model, fingerprint)
    if entry is None:
        entry = await _build_entry(session, library_id, model, fingerprint)
        _cache_put(entry)

    wanted = {c.id for c, _ in leaves}
    missing = [(c, _) for c, _ in leaves if c.id not in entry.ids]
    if missing:
        if len(missing) <= _SELFHEAL_LIMIT:
            try:
                items = await _selfheal(missing, cfg)
                if items:
                    _entry_append(entry, items)
                    entry.fingerprint = await _fingerprint(session, library_id, model)
            except Exception as e:  # noqa: BLE001 - 自愈失败本轮仅词项召回
                logger.warning("库 %s %d 个缺失分段向量自愈失败（本轮仅词项召回）: %s",
                               library_id, len(missing), e)
        else:
            logger.warning("库 %s 有 %d 个分段无有效向量（未回填或模型已变更，"
                           "请运行 scripts/backfill_chunk_embeddings.py），本轮这些分段仅词项召回",
                           library_id, len(missing))
    if entry.matrix is None or not entry.ids:
        return {}
    sims = await asyncio.to_thread(matrix_cosine, entry.matrix, query_vec)
    return {cid: float(sims[row]) for cid, row in entry.ids.items() if cid in wanted}


def invalidate_cache() -> None:
    """清空进程内向量矩阵缓存（测试/运维用）。"""
    _cache.clear()


# ===== 回填（存量分段批量补向量/词项，供 CLI 调用）=====

async def backfill(library_id: int | None = None, batch_size: int = 32,
                   model: str | None = None, dry_run: bool = False,
                   scope: str = 'both') -> dict:
    """按库按 chunk_id 顺序批量回填缺失/过期向量与词项；每批独立 commit 断点续跑。

    结构叶子（无子块的块）全量回填，不过滤 enabled/available（禁用文档
    重新启用即有向量）。单批失败记日志跳过，汇总进返回值。
    scope: vectors | tokens | both（词项为本地分词，无外部 API 依赖）。
    """
    from app.services.library_retrieval import config as lr_config, embeddings

    if scope not in ('vectors', 'tokens', 'both'):
        raise ValueError(f'未知的回填范围: {scope}')
    need_vectors = scope in ('vectors', 'both')
    cfg = {}
    if need_vectors or dry_run and scope == 'vectors':
        async with SessionLocal() as s:
            cfg = await lr_config(s, 'embedding')
    model = model or cfg.get('model', '')
    if need_vectors and (not cfg.get('base_url') or not model):
        raise ValueError('向量模型未配置（EMBEDDING_BASE_URL/EMBEDDING_MODEL），无法回填')

    async with SessionLocal() as s:
        lib_q = select(KnowledgeLibrary).where(KnowledgeLibrary.library_type == 'document')
        if library_id is not None:
            lib_q = lib_q.where(KnowledgeLibrary.id == library_id)
        libs = (await s.execute(lib_q)).scalars().all()
    if not libs:
        raise ValueError(f'未找到文档库: library_id={library_id}')

    stats: dict = {}
    for lib in libs:
        child = aliased(LibraryChunk)
        has_children = select(child.id).where(child.parent_id == LibraryChunk.id).exists()
        lib_stats: dict = {'name': lib.name}

        if need_vectors:
            lib_stats.update(await _backfill_vectors(lib, has_children, batch_size, cfg,
                                                     model, dry_run))
        if scope in ('tokens', 'both'):
            lib_stats.update(await _backfill_tokens(lib, has_children, dry_run))
        stats[lib.id] = lib_stats
    return stats


def _vector_candidates(lib, has_children, emb, model, dim_bytes,
                       after=None, limit=None):
    stale = [emb.chunk_id.is_(None), emb.model != model]
    if dim_bytes is not None:
        stale.append(func.length(emb.embedding) != dim_bytes)
    q = (select(LibraryChunk.id, LibraryChunk.content)
         .join(LibraryDocument, LibraryDocument.id == LibraryChunk.document_id)
         .outerjoin(emb, emb.chunk_id == LibraryChunk.id)
         .where(LibraryDocument.library_id == lib.id, ~has_children, or_(*stale))
         .order_by(LibraryChunk.id))
    if after is not None:
        q = q.where(LibraryChunk.id > after)
    if limit is not None:
        q = q.limit(limit)
    return q


async def _backfill_vectors(lib, has_children, batch_size, cfg, model, dry_run) -> dict:
    from app.services.library_retrieval import embeddings
    emb = aliased(LibraryChunkEmbedding)

    if dry_run:
        async with SessionLocal() as s:
            total = (await s.execute(select(func.count()).select_from(
                _vector_candidates(lib, has_children, emb, model, None).subquery()))).scalar_one()
        logger.info("[dry-run] 库 %s(%s) 向量待回填 %d 条", lib.id, lib.name, total)
        return {'pending_vectors': total}

    done = failed = 0
    last: uuid.UUID | None = None
    dim_bytes: int | None = None
    while True:
        async with SessionLocal() as s:
            rows = (await s.execute(_vector_candidates(
                lib, has_children, emb, model, dim_bytes, after=last, limit=batch_size))).all()
        if not rows:
            break
        last = rows[-1][0]
        try:
            vectors = await embeddings([embed_text(r[1]) for r in rows], cfg)
            items = [(r[0], model, pack_vector(v)) for r, v in zip(rows, vectors) if v]
            async with SessionLocal() as ws:
                await upsert_embeddings(ws, items)
                await ws.commit()
            done += len(items)
            if items and dim_bytes is None:
                dim_bytes = len(items[0][2])
        except Exception as e:  # noqa: BLE001 - 单批失败跳过，断点续跑
            failed += len(rows)
            logger.warning("库 %s 向量回填批次失败（chunk %s 起 %d 条，已跳过）: %s",
                           lib.id, rows[0][0], len(rows), e)
    logger.info("库 %s(%s) 向量回填完成：%d 条，失败 %d 条", lib.id, lib.name, done, failed)
    return {'backfilled_vectors': done, 'failed_vectors': failed}


async def _backfill_tokens(lib, has_children, dry_run) -> dict:
    """词项回填：本地分词（无 API），标题取文档名，正文含检索增强。"""
    tk = aliased(LibraryChunkToken)

    def token_query(after=None, limit=None):
        q = (select(LibraryChunk.id, LibraryChunk.content,
                    LibraryChunk.retrieval_enhancements, LibraryChunk.important_keywords,
                    LibraryDocument.name)
             .join(LibraryDocument, LibraryDocument.id == LibraryChunk.document_id)
             .outerjoin(tk, tk.chunk_id == LibraryChunk.id)
             .where(LibraryDocument.library_id == lib.id, ~has_children, tk.chunk_id.is_(None))
             .order_by(LibraryChunk.id))
        if after is not None:
            q = q.where(LibraryChunk.id > after)
        if limit is not None:
            q = q.limit(limit)
        return q

    if dry_run:
        async with SessionLocal() as s:
            total = (await s.execute(select(func.count()).select_from(
                token_query().subquery()))).scalar_one()
        logger.info("[dry-run] 库 %s(%s) 词项待回填 %d 条", lib.id, lib.name, total)
        return {'pending_tokens': total}

    from app.services.knowledge_engines.chunk_enhancer import retrieval_text
    done = failed = 0
    last: uuid.UUID | None = None
    while True:
        async with SessionLocal() as s:
            rows = (await s.execute(token_query(after=last, limit=_TOKEN_BATCH))).all()
        if not rows:
            break
        last = rows[-1][0]
        try:
            items = await asyncio.to_thread(
                lambda: [(r[0], token_dict(retrieval_text(r[1], r[2] or {}), r[4], r[3] or []))
                         for r in rows])
            async with SessionLocal() as ws:
                await upsert_tokens(ws, items)
                await ws.commit()
            done += len(items)
        except Exception as e:  # noqa: BLE001 - 单批失败跳过，断点续跑
            failed += len(rows)
            logger.warning("库 %s 词项回填批次失败（chunk %s 起 %d 条，已跳过）: %s",
                           lib.id, rows[0][0], len(rows), e)
    logger.info("库 %s(%s) 词项回填完成：%d 条，失败 %d 条", lib.id, lib.name, done, failed)
    return {'backfilled_tokens': done, 'failed_tokens': failed}
