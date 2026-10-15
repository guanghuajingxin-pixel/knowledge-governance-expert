"""Wiki 自动生成服务（卡帕提 LLM Wiki 模式）。

原料解析完成 → 入队（合并同库 PENDING run）→ 后台任务按库串行消化：
  ① 规划：原料摘录 + 现有页面目录 → 页面计划 JSON（update 优先，防页面膨胀）
  ② 逐页生成：markdown 页面，含 [[wikilink]] 互链与 ^[来源:文档名] 溯源标记
  ③ 概览页重建：按页面目录确定性生成索引（不经 LLM）

同库同时只有一个 RUNNING run；批次快照（每批上限 5 篇）后新到的原料并入下一批。
人工修正（edited_by_human）的页面自动生成跳过，可手动重新生成。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import SessionLocal
from kb_common.models import KnowledgeLibrary, LibraryDocument, WikiGenerationRun, WikiPage

logger = logging.getLogger(__name__)

# 每批消化原料上限（控 LLM 上下文与成本）；超出部分拆后续批
BATCH_SIZE = 5
# 单篇原料摘录上限与单批总预算（字符）
DOC_EXCERPT_CHARS = 6000
BATCH_TOTAL_CHARS = 24000
# 单次 run 生成/更新的页面上限
MAX_PAGES_PER_RUN = 10
_LLM_TIMEOUT = 120.0

OVERVIEW_TITLE = "知识概览"
PAGE_TYPES = {"topic": "主题", "entity": "实体", "comparison": "对比", "overview": "概览", "qa": "问答"}

# 同库串行锁：库 id → asyncio.Lock（进程内；kb-api 单进程模型）
_locks: dict[int, asyncio.Lock] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _library_lock(library_id: int) -> asyncio.Lock:
    return _locks.setdefault(library_id, asyncio.Lock())


def wiki_auto_generate(lib) -> bool:
    """库级自动生成开关（engine_config.wiki.auto_generate，默认开）。"""
    return bool(((lib.engine_config or {}) .get("wiki") or {}).get("auto_generate", True))


# ---------------------------------------------------------------- LLM 基础设施

async def resolve_llm(s: AsyncSession) -> dict:
    """LLM 配置：llm_profiles 默认模型优先，settings/env 兜底（与智能问答同口径）。"""
    from app.services.llm_resolver import resolve_llm_config
    return await resolve_llm_config(s)


async def _chat(llm: dict, system: str, user: str) -> str:
    client = AsyncOpenAI(base_url=llm["base_url"], api_key=llm.get("api_key") or "empty",
                         timeout=_LLM_TIMEOUT, max_retries=1)
    resp = await client.chat.completions.create(
        model=llm["model"], temperature=0.2,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return (resp.choices[0].message.content or "").strip()


def _parse_json(raw: str):
    """宽容解析 LLM 返回的 JSON（剥离 ``` 围栏；dict/list 均可）。"""
    value = (raw or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    return json.loads(value)


# ---------------------------------------------------------------- 原料读取

def _read_parsed_markdown_sync(doc) -> str:
    from kb_common.clients import minio_client
    from app.routes.managed_library import _parsed_markdown_key
    response = None
    try:
        response = minio_client.minio.get_object(minio_client.RAW, _parsed_markdown_key(doc))
        return response.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    finally:
        if response is not None:
            response.close()
            response.release_conn()


async def _load_excerpts(doc_ids: list[str]) -> list[tuple[LibraryDocument, str]]:
    """读取原料解析产物摘录（每篇截断 + 批内总预算）。"""
    docs: list[LibraryDocument] = []
    async with SessionLocal() as s:
        rows = (await s.execute(select(LibraryDocument).where(
            LibraryDocument.id.in_([UUID(d) for d in doc_ids])))).scalars().all()
        docs = list(rows)
    excerpts: list[tuple[LibraryDocument, str]] = []
    total = 0
    for doc in docs:
        if total >= BATCH_TOTAL_CHARS:
            break
        text = await asyncio.to_thread(_read_parsed_markdown_sync, doc)
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text).strip()  # 图片标记对 LLM 无意义
        if not text:
            continue
        budget = min(DOC_EXCERPT_CHARS, BATCH_TOTAL_CHARS - total)
        if budget <= 0:
            break
        excerpts.append((doc, text[:budget]))
        total += len(excerpts[-1][1])
    return excerpts


# ---------------------------------------------------------------- 入队与派发

async def enqueue_generation(library_id: int, document_ids: list[str],
                             triggered_by: str = "auto") -> UUID | None:
    """入队：同库已有 PENDING 的 ingest run 则合并（钉钉批量同步只产生少量批）。"""
    document_ids = [d for d in dict.fromkeys(str(d) for d in document_ids if d)]
    if not document_ids:
        return None
    async with SessionLocal() as s:
        run = (await s.execute(select(WikiGenerationRun).where(
            WikiGenerationRun.library_id == library_id,
            WikiGenerationRun.kind == "ingest",
            WikiGenerationRun.status == "PENDING",
        ).with_for_update(skip_locked=True))).scalar_one_or_none()
        if run is None:
            run = WikiGenerationRun(library_id=library_id, kind="ingest",
                                    document_ids=[], triggered_by=triggered_by)
            s.add(run)
        run.document_ids = list(dict.fromkeys([*(run.document_ids or []), *document_ids]))
        await s.commit()
        run_id = run.id
    _spawn(run_id)
    return run_id


async def auto_trigger_for_document(doc) -> None:
    """解析完成钩子（_apply_chunks 末尾调用）：wiki 库且自动生成开启时入队。

    独立会话即时提交 run 行，避免依赖调用方事务的提交时序。
    """
    async with SessionLocal() as s:
        lib = await s.get(KnowledgeLibrary, doc.library_id)
        if lib is None or lib.library_type != "wiki" or not wiki_auto_generate(lib):
            return
    await enqueue_generation(doc.library_id, [str(doc.id)], triggered_by="auto")


def _spawn(run_id: UUID) -> None:
    async def _worker():
        async with SessionLocal() as s:
            run = await s.get(WikiGenerationRun, run_id)
            if run is None or run.status != "PENDING":
                return
            library_id, kind = run.library_id, run.kind
        async with _library_lock(library_id):
            try:
                if kind == "lint":
                    await _run_lint(run_id)
                else:
                    await _run_ingest(run_id)
            except Exception as e:  # noqa: BLE001 — 后台任务兜底，任何异常都要落 run 状态
                logger.exception("wiki run %s crashed", run_id)
                try:
                    await _fail_run(run_id, f"任务异常中断：{e}")
                except Exception:
                    pass

    asyncio.create_task(_worker())


# ---------------------------------------------------------------- 生成主流程

_PLAN_SYSTEM = "你是严谨的知识库 Wiki 维护者，负责把原料文档提炼为互相链接的结构化知识页面。只输出合法 JSON。"

_PLAN_PROMPT = """## 现有 Wiki 页面目录
{catalog}

## 待消化原料（解析产物摘录）
{excerpts}

请规划这批原料带来的页面更新，只输出 JSON 对象：
{{"pages": [{{"action": "create|update", "title": "页面标题", "page_type": "topic|entity|comparison", "reason": "一句话依据"}}]}}

规则：
- 优先 action=update 复用现有页面，避免页面数量膨胀；仅为主题/实体/对比三类
- entity=具体的人/组织/产品/系统，topic=知识主题，comparison=对比分析
- 标注【人工修正】的现有页面必须跳过，不得列入计划
- 新建页面总数不超过 5 个；与原料无关的现有页面不要顺带更新
- 没有值得沉淀的内容时输出 {{"pages": []}}"""


_PAGE_SYSTEM = "你是严谨的知识库 Wiki 页面撰写者。基于给定原料撰写页面，不编造原料中没有的信息。只输出合法 JSON。"

_PAGE_PROMPT = """请撰写 Wiki 页面「{title}」（类型：{type_label}）。

## 全库页面标题（正文中用 [[标题]] 双向链接引用，至少 2 个）
{titles}

{existing}
## 依据原料（解析产物摘录）
{excerpts}

只输出 JSON 对象：
{{"summary": "一行摘要（120 字内）", "content": "完整 markdown 页面", "source_docs": ["引用的原料文档名"]}}

content 要求：
- 以「## 小节标题」组织，开头一段总述，然后分小节展开
- 正文中用 [[其它页面标题]] 建立互链（目标必须在上面的标题清单中）
- 每个事实性段落末尾加 ^[来源:文档名] 溯源标记
- 更新已有页面时保留仍然正确的内容，合并新信息；新原料与已有内容矛盾时，用「> ⚠️ 矛盾提示：…」显式标注"""


async def _run_ingest(run_id: UUID) -> None:
    # 1) 快照批次并置 RUNNING；超出部分拆后续批
    overflow_ids: list[str] = []
    async with SessionLocal() as s:
        run = await s.get(WikiGenerationRun, run_id, with_for_update=True)
        if run is None or run.status != "PENDING":
            return
        lib = await s.get(KnowledgeLibrary, run.library_id)
        if lib is None or lib.library_type != "wiki":
            run.status, run.error, run.finished_at = "FAILED", "目标库不存在或不是 Wiki 库", _utcnow()
            await s.commit()
            return
        all_ids = list(run.document_ids or [])
        run.document_ids = all_ids[:BATCH_SIZE]
        overflow_ids = all_ids[BATCH_SIZE:]
        run.status, run.started_at = "RUNNING", _utcnow()
        if overflow_ids:
            s.add(WikiGenerationRun(library_id=run.library_id, kind="ingest",
                                    document_ids=overflow_ids, triggered_by=run.triggered_by))
        await s.commit()
        library_id, batch_ids, triggered_by = run.library_id, list(run.document_ids), run.triggered_by

    # 2) LLM 配置
    async with SessionLocal() as s:
        llm = await resolve_llm(s)
    if not llm.get("base_url") or not llm.get("model"):
        await _fail_run(run_id, "未配置可用的 LLM，请先在「模型配置」中启用大模型后重试")
        return

    # 3) 原料摘录
    excerpts = await _load_excerpts(batch_ids)
    if not excerpts:
        await _finish_run(run_id, 0, 0, "原料均无解析产物，无可消化内容")
        return
    excerpts_text = "\n\n".join(f"### {doc.name}\n{text}" for doc, text in excerpts)
    source_names = {doc.name for doc, _ in excerpts}

    # 4) 现有页面目录
    async with SessionLocal() as s:
        pages = (await s.execute(select(WikiPage).where(
            WikiPage.library_id == library_id,
            WikiPage.page_type != "overview",
        ).order_by(WikiPage.updated_at.desc()))).scalars().all()
    catalog = "\n".join(
        f"- {p.title}（{PAGE_TYPES.get(p.page_type, p.page_type)}）{'【人工修正】' if p.edited_by_human else ''}：{p.summary[:60]}"
        for p in pages) or "（暂无页面）"
    all_titles = [p.title for p in pages]

    # 5) 规划
    try:
        plan_raw = await _chat(llm, _PLAN_SYSTEM, _PLAN_PROMPT.format(
            catalog=catalog, excerpts=excerpts_text[:BATCH_TOTAL_CHARS * 2]))
        plan = _parse_json(plan_raw)
        planned = [p for p in (plan.get("pages") or []) if isinstance(p, dict)]
    except Exception as e:  # noqa: BLE001
        await _fail_run(run_id, f"页面规划失败：{e}")
        return

    # 规范化：去重、过滤人工修正页与 overview、限量
    protected = {p.title for p in pages if p.edited_by_human}
    seen: set[str] = set()
    normalized: list[dict] = []
    for item in planned:
        title = str(item.get("title") or "").strip()
        action = str(item.get("action") or "").strip()
        page_type = str(item.get("page_type") or "topic").strip()
        if not title or len(title) > 200 or title in seen:
            continue
        if title in protected or title == OVERVIEW_TITLE:
            continue
        if action not in ("create", "update"):
            continue
        if page_type not in ("topic", "entity", "comparison"):
            page_type = "topic"
        seen.add(title)
        normalized.append({"action": action, "title": title, "page_type": page_type})
    normalized = normalized[:MAX_PAGES_PER_RUN]

    created = updated = failures = 0
    errors: list[str] = []
    for item in normalized:
        try:
            ok = await _generate_page(library_id, llm, item["title"], item["page_type"],
                                      excerpts, excerpts_text, all_titles, source_names)
            if ok == "created":
                created += 1
            elif ok == "updated":
                updated += 1
        except Exception as e:  # noqa: BLE001 — 单页失败不阻断其余页
            failures += 1
            errors.append(f"{item['title']}：{e}")
            logger.warning("wiki page generation failed (%s): %s", item["title"], e)

    # 6) 概览页重建
    try:
        await rebuild_overview(library_id)
        updated += 1
    except Exception as e:  # noqa: BLE001
        errors.append(f"概览页重建失败：{e}")

    # 7) 收尾：全部计划页面失败 → run FAILED；部分失败保留 COMPLETED + error 明细
    if normalized and failures == len(normalized):
        await _fail_run(run_id, "；".join(errors)[:2000])
        return
    message = "；".join(errors)[:2000] if errors else ""
    await _finish_run(run_id, created, updated, message, triggered_by=triggered_by)


async def _generate_page(library_id: int, llm: dict, title: str, page_type: str,
                         excerpts: list, excerpts_text: str, all_titles: list,
                         source_names: set) -> str:
    """生成单个页面并写库；返回 created | updated。update 模式带现有内容供合并修订。"""
    async with SessionLocal() as s:
        existing = await s.execute(select(WikiPage).where(
            WikiPage.library_id == library_id, WikiPage.title == title))
        page = existing.scalar_one_or_none()
        existing_block = ""
        if page is not None:
            if page.edited_by_human:
                return "skipped"
            existing_block = f"## 现有页面内容（更新合并，保留仍正确的内容）\n{page.content[:8000]}\n\n"

    titles_block = "\n".join(f"- {t}" for t in all_titles if t != title) or "（暂无其它页面）"
    raw = await _chat(llm, _PAGE_SYSTEM, _PAGE_PROMPT.format(
        title=title, type_label=PAGE_TYPES[page_type], titles=titles_block,
        existing=existing_block, excerpts=excerpts_text[:BATCH_TOTAL_CHARS * 2]))
    data = _parse_json(raw)
    content = str(data.get("content") or "").strip()
    summary = str(data.get("summary") or "").strip()[:500]
    if not content:
        raise ValueError("模型未返回页面内容")
    # 溯源：LLM 声称引用的文档 ∩ 本批真实原料名，防止幻觉引用
    cited = {str(n).strip() for n in (data.get("source_docs") or []) if str(n).strip()}
    refs = [{"document_id": str(doc.id), "document_name": doc.name}
            for doc, _ in excerpts if doc.name in cited] or \
           [{"document_id": str(doc.id), "document_name": doc.name} for doc, _ in excerpts]
    # wikilink 只保留指向真实存在或本批新建的标题
    async with SessionLocal() as s:
        page = (await s.execute(select(WikiPage).where(
            WikiPage.library_id == library_id, WikiPage.title == title))).scalar_one_or_none()
        if page is None:
            s.add(WikiPage(library_id=library_id, title=title, page_type=page_type,
                           content=content, summary=summary, source_refs=refs,
                           status="STABLE", generated_model=llm.get("model", "")))
            result = "created"
        else:
            page.page_type = page_type
            page.content, page.summary, page.source_refs = content, summary, refs
            page.status, page.message = "STABLE", ""
            page.version += 1
            page.generated_model = llm.get("model", "")
            result = "updated"
        await s.commit()
    return result


async def rebuild_overview(library_id: int) -> None:
    """概览页：按页面目录确定性重建（分类索引 + 一行摘要），不经 LLM。"""
    async with SessionLocal() as s:
        lib = await s.get(KnowledgeLibrary, library_id)
        if lib is None:
            return
        pages = (await s.execute(select(WikiPage).where(
            WikiPage.library_id == library_id,
            WikiPage.page_type != "overview",
        ).order_by(WikiPage.title))).scalars().all()
        sections: list[str] = [f"# {lib.name} · 知识概览",
                               f"> LLM 依据库内原料维护的知识索引，共 {len(pages)} 个页面。最后更新：{_utcnow():%Y-%m-%d %H:%M}"]
        for type_key in ("topic", "entity", "comparison", "qa"):
            group = [p for p in pages if p.page_type == type_key]
            if not group:
                continue
            sections.append(f"\n## {PAGE_TYPES[type_key]}页\n")
            sections.extend(f"- [[{p.title}]] — {p.summary or '（暂无摘要）'}" for p in group)
        content = "\n".join(sections)
        page = (await s.execute(select(WikiPage).where(
            WikiPage.library_id == library_id,
            WikiPage.title == OVERVIEW_TITLE))).scalar_one_or_none()
        if page is None:
            s.add(WikiPage(library_id=library_id, title=OVERVIEW_TITLE, page_type="overview",
                           content=content, summary=f"知识索引（{len(pages)} 个页面）",
                           source_refs=[], status="STABLE"))
        else:
            page.content = content
            page.summary = f"知识索引（{len(pages)} 个页面）"
            page.version += 1
        await s.commit()


# ---------------------------------------------------------------- Lint 健康检查

_LINT_SYSTEM = "你是知识库 Wiki 的健康检查员，只基于给定页面内容做判断，只输出合法 JSON。"

_LINT_PROMPT = """以下是 Wiki 库全部页面（内容已截断）：

{pages}

请做健康检查，只输出 JSON 对象：
{{
  "contradictions": [{{"page_a": "标题", "page_b": "标题", "description": "矛盾点"}}],
  "orphans": [{{"title": "标题", "reason": "无入链/无出链的原因"}}],
  "missing_topics": [{{"suggested_title": "建议新建的页面标题", "reason": "多处提及但无独立页面"}}],
  "stale_pages": [{{"title": "标题", "reason": "内容疑似过期/单薄的原因"}}]
}}
没有问题的分类输出空数组；page_a/page_b/title 必须取自上面的真实页面标题。"""


async def enqueue_lint(library_id: int, triggered_by: str = "lint") -> UUID | None:
    async with SessionLocal() as s:
        run = WikiGenerationRun(library_id=library_id, kind="lint",
                                document_ids=[], triggered_by=triggered_by)
        s.add(run)
        await s.commit()
        run_id = run.id
    _spawn(run_id)
    return run_id


async def _run_lint(run_id: UUID) -> None:
    async with SessionLocal() as s:
        run = await s.get(WikiGenerationRun, run_id, with_for_update=True)
        if run is None or run.status != "PENDING":
            return
        run.status, run.started_at = "RUNNING", _utcnow()
        await s.commit()
        library_id = run.library_id
    try:
        async with SessionLocal() as s:
            llm = await resolve_llm(s)
        if not llm.get("base_url") or not llm.get("model"):
            await _fail_run(run_id, "未配置可用的 LLM，请先在「模型配置」中启用大模型后重试")
            return
        async with SessionLocal() as s:
            pages = (await s.execute(select(WikiPage).where(
                WikiPage.library_id == library_id,
                WikiPage.page_type != "overview",
            ).order_by(WikiPage.title))).scalars().all()
        if not pages:
            await _finish_lint(run_id, {"note": "库内暂无页面，无可检查内容"})
            return
        blocks, total = [], 0
        for p in pages:
            block = f"### {p.title}（{PAGE_TYPES.get(p.page_type, p.page_type)}）\n{p.content[:2000]}"
            if total + len(block) > 60000:
                blocks.append(f"### {p.title}（内容超限略）")
                continue
            blocks.append(block)
            total += len(block)
        raw = await _chat(llm, _LINT_SYSTEM, _LINT_PROMPT.format(pages="\n\n".join(blocks)))
        report = _parse_json(raw)
        if not isinstance(report, dict):
            raise ValueError("模型未返回 JSON 对象")
        for key in ("contradictions", "orphans", "missing_topics", "stale_pages"):
            if not isinstance(report.get(key), list):
                report[key] = []
        await _finish_lint(run_id, report)
    except Exception as e:  # noqa: BLE001
        await _fail_run(run_id, f"健康检查失败：{e}")


async def _finish_lint(run_id: UUID, report: dict) -> None:
    async with SessionLocal() as s:
        run = await s.get(WikiGenerationRun, run_id)
        if run is not None:
            run.status, run.report, run.finished_at = "COMPLETED", report, _utcnow()
            await s.commit()


# ---------------------------------------------------------------- 单页重新生成 / 状态收尾

async def regenerate_page(page_id: UUID) -> WikiPage:
    """单页重新生成（路由同步调用）：按该页溯源原料重写，忽略人工保护并清除标记。"""
    async with SessionLocal() as s:
        page = await s.get(WikiPage, page_id)
        if page is None:
            raise ValueError("页面不存在")
        library_id = page.library_id
        source_refs = list(page.source_refs or [])
        title, page_type = page.title, page.page_type
    if page_type in ("overview", "qa"):
        raise ValueError("概览页随每次生成自动重建；问答沉淀页不支持重新生成")
    doc_ids = [ref.get("document_id") for ref in source_refs if ref.get("document_id")]
    if not doc_ids:
        raise ValueError("该页面无溯源原料，无法重新生成（可人工编辑或删除）")
    async with SessionLocal() as s:
        llm = await resolve_llm(s)
    if not llm.get("base_url") or not llm.get("model"):
        raise ValueError("未配置可用的 LLM，请先在「模型配置」中启用大模型")
    excerpts = await _load_excerpts(doc_ids)
    if not excerpts:
        raise ValueError("溯源原料已无解析产物，请先重新解析原料文档")
    excerpts_text = "\n\n".join(f"### {doc.name}\n{text}" for doc, text in excerpts)
    async with SessionLocal() as s:
        titles = [t for (t,) in (await s.execute(
            select(WikiPage.title).where(WikiPage.library_id == library_id,
                                         WikiPage.title != title)))]
    await _generate_page(library_id, llm, title, page_type, excerpts, excerpts_text,
                         titles, {doc.name for doc, _ in excerpts})
    async with SessionLocal() as s:
        page = await s.get(WikiPage, page_id)
        if page is not None:
            page.edited_by_human = False
            await s.commit()
    await rebuild_overview(library_id)
    async with SessionLocal() as s:
        return await s.get(WikiPage, page_id)


async def _fail_run(run_id: UUID, error: str) -> None:
    async with SessionLocal() as s:
        run = await s.get(WikiGenerationRun, run_id)
        if run is not None and run.status != "COMPLETED":
            run.status, run.error, run.finished_at = "FAILED", error[:2000], _utcnow()
            await s.commit()


async def _finish_run(run_id: UUID, created: int, updated: int, message: str = "",
                      triggered_by: str = "auto") -> None:
    async with SessionLocal() as s:
        run = await s.get(WikiGenerationRun, run_id)
        if run is not None:
            run.status = "COMPLETED"
            run.pages_created, run.pages_updated = created, updated
            run.error = message[:2000]
            run.finished_at = _utcnow()
            await s.commit()
    logger.info("wiki ingest run %s done: +%d ~%d (%s)", run_id, created, updated, triggered_by)


async def recover_interrupted_runs() -> None:
    """启动恢复：遗留 RUNNING 的 run 置 FAILED（可重试）。"""
    async with SessionLocal() as s:
        runs = (await s.execute(select(WikiGenerationRun).where(
            WikiGenerationRun.status == "RUNNING"))).scalars().all()
        for run in runs:
            run.status, run.error = "FAILED", "服务重启中断，可重试"
            run.finished_at = _utcnow()
        if runs:
            await s.commit()
            logger.info("wiki: %d interrupted run(s) marked FAILED on startup", len(runs))
