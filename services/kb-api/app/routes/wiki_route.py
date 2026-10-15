"""Wiki 知识库路由（卡帕提 LLM WIKI 模式）。

库 CRUD（创建/设置含自动生成开关）、页面列表/详情/人工编辑/删除/单页重新生成、
手动补生成与失败重试、Lint 健康检查、问答沉淀归档。
原料文档的导入/解析复用文档库管理（document-libraries 路由，已对 wiki 库开放）。
"""
import uuid as uuid_mod
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, require_role
from app.services.wiki import generator
from kb_common.database import get_session
from kb_common.models import KnowledgeLibrary, LibraryDocument, User, WikiGenerationRun, WikiPage

router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"])

_WRITE = Depends(require_role("super_admin", "admin", "editor"))
_ADMIN = Depends(require_role("super_admin", "admin"))


async def _library(s: AsyncSession, library_id: int) -> KnowledgeLibrary:
    lib = await s.get(KnowledgeLibrary, library_id)
    if lib is None or lib.library_type != "wiki":
        raise HTTPException(404, "Wiki 库不存在")
    return lib


async def _page(s: AsyncSession, library_id: int, page_id) -> WikiPage:
    page = await s.get(WikiPage, page_id)
    if page is None or page.library_id != library_id:
        raise HTTPException(404, "页面不存在")
    return page


def _page_out(p: WikiPage, *, with_content: bool = False) -> dict:
    data = {"id": str(p.id), "title": p.title, "page_type": p.page_type,
            "summary": p.summary, "source_refs": p.source_refs or [],
            "status": p.status, "message": p.message, "version": p.version,
            "edited_by_human": p.edited_by_human, "generated_model": p.generated_model,
            "created_at": p.created_at, "updated_at": p.updated_at}
    if with_content:
        data["content"] = p.content
    return data


def _run_out(r: WikiGenerationRun) -> dict:
    return {"id": str(r.id), "kind": r.kind, "document_ids": r.document_ids or [],
            "status": r.status, "pages_created": r.pages_created, "pages_updated": r.pages_updated,
            "report": r.report or {}, "error": r.error, "triggered_by": r.triggered_by,
            "started_at": r.started_at, "finished_at": r.finished_at, "created_at": r.created_at}


def _lib_out(lib: KnowledgeLibrary, page_count: int, doc_count: int,
             last_run: WikiGenerationRun | None) -> dict:
    return {"id": lib.id, "name": lib.name, "description": lib.description,
            "enabled": lib.enabled, "creator": lib.creator,
            "auto_generate": generator.wiki_auto_generate(lib),
            "page_count": page_count, "document_count": doc_count,
            "last_run": _run_out(last_run) if last_run else None,
            "created_at": lib.created_at, "updated_at": lib.updated_at}


async def _lib_stats(s: AsyncSession, library_id: int) -> tuple[int, int, WikiGenerationRun | None]:
    page_count = (await s.execute(select(func.count()).select_from(WikiPage).where(
        WikiPage.library_id == library_id))).scalar_one()
    doc_count = (await s.execute(select(func.count()).select_from(LibraryDocument).where(
        LibraryDocument.library_id == library_id))).scalar_one()
    last_run = (await s.execute(select(WikiGenerationRun).where(
        WikiGenerationRun.library_id == library_id)
        .order_by(WikiGenerationRun.created_at.desc()).limit(1))).scalar_one_or_none()
    return page_count, doc_count, last_run


# ---------------------------------------------------------------- 库 CRUD

class WikiLibraryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    auto_generate: bool = True

    @field_validator("name")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("知识库名称不能为空")
        return value.strip()


@router.post("/libraries", dependencies=[_WRITE])
async def create_wiki_library(body: WikiLibraryIn, user: User = Depends(get_current_user),
                              s: AsyncSession = Depends(get_session)):
    lib = KnowledgeLibrary(name=body.name, description=body.description, platform="mineru",
                           dataset_id=uuid_mod.uuid4().hex, library_type="wiki", enabled=True,
                           creator=user.username,
                           engine_config={"wiki": {"auto_generate": body.auto_generate}})
    s.add(lib)
    await s.commit()
    await s.refresh(lib)
    return _lib_out(lib, 0, 0, None)


@router.get("/libraries")
async def list_wiki_libraries(u: User = Depends(get_current_user),
                              s: AsyncSession = Depends(get_session)):
    libs = (await s.execute(select(KnowledgeLibrary).where(
        KnowledgeLibrary.library_type == "wiki").order_by(KnowledgeLibrary.id.desc()))).scalars().all()
    ids = [lib.id for lib in libs]
    page_counts: dict[int, int] = {}
    doc_counts: dict[int, int] = {}
    last_runs: dict[int, WikiGenerationRun] = {}
    if ids:
        for lib_id, count in (await s.execute(select(WikiPage.library_id, func.count())
                .where(WikiPage.library_id.in_(ids)).group_by(WikiPage.library_id))).all():
            page_counts[lib_id] = count
        for lib_id, count in (await s.execute(select(LibraryDocument.library_id, func.count())
                .where(LibraryDocument.library_id.in_(ids)).group_by(LibraryDocument.library_id))).all():
            doc_counts[lib_id] = count
        runs = (await s.execute(select(WikiGenerationRun).where(
            WikiGenerationRun.library_id.in_(ids)).order_by(WikiGenerationRun.created_at.desc()))).scalars().all()
        for run in runs:
            last_runs.setdefault(run.library_id, run)
    return [_lib_out(lib, page_counts.get(lib.id, 0), doc_counts.get(lib.id, 0),
                     last_runs.get(lib.id)) for lib in libs]


@router.get("/libraries/{library_id}")
async def get_wiki_library(library_id: int, u: User = Depends(get_current_user),
                           s: AsyncSession = Depends(get_session)):
    lib = await _library(s, library_id)
    page_count, doc_count, last_run = await _lib_stats(s, library_id)
    return _lib_out(lib, page_count, doc_count, last_run)


class WikiLibraryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    auto_generate: bool | None = None


@router.put("/libraries/{library_id}", dependencies=[_WRITE])
async def update_wiki_library(library_id: int, body: WikiLibraryUpdate,
                              s: AsyncSession = Depends(get_session)):
    lib = await _library(s, library_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        if not (data["name"] or "").strip():
            raise HTTPException(422, "知识库名称不能为空")
        lib.name = data["name"].strip()
    if "description" in data:
        lib.description = data["description"]
    if "auto_generate" in data:
        config = dict(lib.engine_config or {})
        wiki_cfg = dict(config.get("wiki") or {})
        wiki_cfg["auto_generate"] = bool(data["auto_generate"])
        config["wiki"] = wiki_cfg
        lib.engine_config = config
    await s.commit()
    await s.refresh(lib)
    page_count, doc_count, last_run = await _lib_stats(s, library_id)
    return _lib_out(lib, page_count, doc_count, last_run)


@router.delete("/libraries/{library_id}", dependencies=[_ADMIN])
async def delete_wiki_library(library_id: int, s: AsyncSession = Depends(get_session)):
    """删除 Wiki 库：需先停用；页面与原料文档随库级联删除（前端二次确认展示数量）。"""
    lib = await _library(s, library_id)
    if lib.enabled:
        raise HTTPException(409, "请先停用知识库，再删除")
    await s.delete(lib)  # wiki_pages / library_documents / runs 均随 FK 级联
    await s.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 页面

@router.get("/libraries/{library_id}/pages")
async def list_pages(library_id: int, u: User = Depends(get_current_user),
                     s: AsyncSession = Depends(get_session)):
    await _library(s, library_id)
    pages = (await s.execute(select(WikiPage).where(WikiPage.library_id == library_id)
        .order_by(WikiPage.updated_at.desc()))).scalars().all()
    return [_page_out(p) for p in pages]


@router.get("/libraries/{library_id}/pages/{page_id}")
async def get_page(library_id: int, page_id: uuid_mod.UUID, u: User = Depends(get_current_user),
                   s: AsyncSession = Depends(get_session)):
    page = await _page(s, library_id, page_id)
    return _page_out(page, with_content=True)


class WikiPageEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200000)
    summary: str | None = Field(default=None, max_length=500)


@router.put("/libraries/{library_id}/pages/{page_id}", dependencies=[_WRITE])
async def edit_page(library_id: int, page_id: uuid_mod.UUID, body: WikiPageEdit,
                    s: AsyncSession = Depends(get_session)):
    """人工编辑：置人工修正标记，后续自动生成跳过该页（可单页重新生成清除标记）。"""
    page = await _page(s, library_id, page_id)
    if page.page_type == "overview":
        raise HTTPException(409, "概览页随每次生成自动重建，不支持人工编辑")
    if "title" in body.model_fields_set and body.title:
        title = body.title.strip()
        if title != page.title:
            conflict = (await s.execute(select(WikiPage).where(
                WikiPage.library_id == library_id, WikiPage.title == title))).scalar_one_or_none()
            if conflict is not None:
                raise HTTPException(409, f"页面标题「{title}」已存在")
            page.title = title
    page.content = body.content
    if body.summary is not None and body.summary.strip():
        page.summary = body.summary.strip()
    elif not page.summary:
        page.summary = body.content.lstrip("# \n")[:120]
    page.edited_by_human = True
    page.version += 1
    await s.commit()
    await s.refresh(page)
    await generator.rebuild_overview(library_id)
    await s.refresh(page)
    return _page_out(page, with_content=True)


@router.delete("/libraries/{library_id}/pages/{page_id}", dependencies=[_WRITE])
async def delete_page(library_id: int, page_id: uuid_mod.UUID, s: AsyncSession = Depends(get_session)):
    page = await _page(s, library_id, page_id)
    await s.delete(page)
    await s.commit()
    await generator.rebuild_overview(library_id)
    return {"ok": True}


@router.post("/libraries/{library_id}/pages/{page_id}/regenerate", dependencies=[_WRITE])
async def regenerate_page(library_id: int, page_id: uuid_mod.UUID,
                          s: AsyncSession = Depends(get_session)):
    """单页重新生成：忽略人工保护并清除标记（同步调用，前端 loading 等待）。"""
    await _page(s, library_id, page_id)
    try:
        page = await generator.regenerate_page(page_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if page is None:
        raise HTTPException(500, "重新生成失败")
    return _page_out(page, with_content=True)


# ---------------------------------------------------------------- 生成 / 记录 / Lint

class GenerateIn(BaseModel):
    # 空 = 全部已完成且未被任何页面消化的原料（初始补跑/失败补跑用）
    document_ids: list[str] = Field(default_factory=list, max_length=100)


@router.post("/libraries/{library_id}/generate", dependencies=[_WRITE])
async def generate(library_id: int, body: GenerateIn, user: User = Depends(get_current_user),
                   s: AsyncSession = Depends(get_session)):
    await _library(s, library_id)
    if body.document_ids:
        rows = (await s.execute(select(LibraryDocument).where(
            LibraryDocument.id.in_([uuid_mod.UUID(d) for d in body.document_ids])))).scalars().all()
        by_id = {str(d.id): d for d in rows}
        bad = [d.name for d in by_id.values()
               if d.library_id != library_id or d.status != "COMPLETED"]
        if bad:
            raise HTTPException(422, "以下文档不在本库或未完成解析：" + "、".join(bad[:5]))
        ids = list(body.document_ids)
    else:
        referenced: set[str] = set()
        pages = (await s.execute(select(WikiPage.source_refs).where(
            WikiPage.library_id == library_id))).all()
        for (refs,) in pages:
            referenced.update(str(r.get("document_id")) for r in (refs or []) if r.get("document_id"))
        docs = (await s.execute(select(LibraryDocument).where(
            LibraryDocument.library_id == library_id,
            LibraryDocument.status == "COMPLETED"))).scalars().all()
        ids = [str(d.id) for d in docs if str(d.id) not in referenced]
    if not ids:
        raise HTTPException(422, "没有可消化的原料（需已完成解析且未被页面消化）")
    run_id = await generator.enqueue_generation(library_id, ids, triggered_by=user.username)
    return {"run_id": str(run_id), "document_count": len(ids)}


@router.get("/libraries/{library_id}/runs")
async def list_runs(library_id: int, u: User = Depends(get_current_user),
                    s: AsyncSession = Depends(get_session)):
    await _library(s, library_id)
    runs = (await s.execute(select(WikiGenerationRun).where(
        WikiGenerationRun.library_id == library_id)
        .order_by(WikiGenerationRun.created_at.desc()).limit(50))).scalars().all()
    return [_run_out(r) for r in runs]


@router.post("/libraries/{library_id}/runs/{run_id}/retry", dependencies=[_WRITE])
async def retry_run(library_id: int, run_id: uuid_mod.UUID, user: User = Depends(get_current_user),
                    s: AsyncSession = Depends(get_session)):
    await _library(s, library_id)
    run = await s.get(WikiGenerationRun, run_id)
    if run is None or run.library_id != library_id:
        raise HTTPException(404, "生成记录不存在")
    if run.status == "RUNNING":
        raise HTTPException(409, "任务执行中，无需重试")
    if run.kind == "lint":
        new_id = await generator.enqueue_lint(library_id, triggered_by=user.username)
    else:
        if run.status != "FAILED":
            raise HTTPException(409, "仅失败的生成记录可重试")
        new_id = await generator.enqueue_generation(
            library_id, list(run.document_ids or []), triggered_by=user.username)
    return {"run_id": str(new_id)}


@router.post("/libraries/{library_id}/lint", dependencies=[_WRITE])
async def trigger_lint(library_id: int, user: User = Depends(get_current_user),
                       s: AsyncSession = Depends(get_session)):
    await _library(s, library_id)
    run_id = await generator.enqueue_lint(library_id, triggered_by=user.username)
    return {"run_id": str(run_id)}


@router.get("/libraries/{library_id}/lint/latest")
async def lint_latest(library_id: int, u: User = Depends(get_current_user),
                      s: AsyncSession = Depends(get_session)):
    await _library(s, library_id)
    run = (await s.execute(select(WikiGenerationRun).where(
        WikiGenerationRun.library_id == library_id,
        WikiGenerationRun.kind == "lint")
        .order_by(WikiGenerationRun.created_at.desc()).limit(1))).scalar_one_or_none()
    return _run_out(run) if run else None


# ---------------------------------------------------------------- 问答沉淀

class QaArchiveIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100000)
    question: str = Field("", max_length=2000)

    @field_validator("title")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("页面标题不能为空")
        return value.strip()


@router.post("/libraries/{library_id}/pages/qa-archive", dependencies=[_WRITE])
async def qa_archive(library_id: int, body: QaArchiveIn, user: User = Depends(get_current_user),
                     s: AsyncSession = Depends(get_session)):
    """问答沉淀：chat 回答直接归档为 qa 页（不经 LLM，保留原文），立即参与检索。"""
    await _library(s, library_id)
    conflict = (await s.execute(select(WikiPage).where(
        WikiPage.library_id == library_id, WikiPage.title == body.title))).scalar_one_or_none()
    if conflict is not None:
        raise HTTPException(409, f"页面标题「{body.title}」已存在，请修改标题")
    page = WikiPage(library_id=library_id, title=body.title, page_type="qa",
                    content=body.content, summary=body.question.strip()[:500],
                    source_refs=[{"question": body.question.strip()}] if body.question.strip() else [],
                    status="STABLE", generated_model="")
    s.add(page)
    await s.commit()
    await s.refresh(page)
    await generator.rebuild_overview(library_id)
    return _page_out(page, with_content=True)
