"""检索返回脱敏策略控制台 API。

- masking-policies：策略 CRUD（条件→识别→动作→执行节点→兜底）
- masking-exemptions：豁免 CRUD（人+范围+实体类型+有效期，到期自动失效）
- masking-logs：脱敏审计日志（日志自身脱敏，只含规则标签与数量）
- masking-global：全局策略（总开关/默认执行节点/失败策略/用户提示语）
- masking/sandbox：预览沙箱（模拟查询+模拟角色→真实检索→原始 vs 脱敏对比）
全部仅 super_admin/admin 可操作（数据安全要求）。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session
from kb_common.models import MaskingPolicy, MaskingExemption, MaskingLog, User, KnowledgeLibrary, KnowledgeBase
from app.deps import require_role
from app.services import masking as masking_svc

router = APIRouter(prefix="/api/v1", tags=["masking"])

ADMIN_ONLY = [Depends(require_role("super_admin", "admin"))]
SCOPES = ("global", "library", "kb")
SCENES = ("search", "chat")
NODE_ACTIONS = ("partial", "generalize", "replace", "hash", "truncate", "reject")
ENTITY_TYPES = ("phone", "id_card", "bank_card", "email", "custom")
FAILURE_STRATEGIES = ("block", "non_sensitive", "deny")


def _validate_policy(payload: "PolicyIn") -> None:
    if not payload.name.strip():
        raise HTTPException(422, "策略名称不能为空")
    if payload.scope_type not in SCOPES:
        raise HTTPException(422, f"不支持的作用域：{payload.scope_type}")
    if payload.scope_type != "global" and not payload.scope_id:
        raise HTTPException(422, "该作用域需要指定具体对象")
    if payload.scope_type == "global" and payload.scope_id:
        raise HTTPException(422, "全局策略无需指定作用域对象")
    if payload.failure_strategy not in FAILURE_STRATEGIES:
        raise HTTPException(422, f"不支持的失败策略：{payload.failure_strategy}")
    for r in payload.user_roles:
        if r not in ("super_admin", "admin", "editor", "viewer"):
            raise HTTPException(422, f"不支持的角色：{r}")
    for sc in payload.scenes:
        if sc not in SCENES:
            raise HTTPException(422, f"不支持的场景：{sc}")
    for r in payload.regex_rules:
        import re
        try:
            re.compile(r.get("pattern") or "")
        except re.error as e:
            raise HTTPException(422, f"非法正则表达式：{e}") from e
    for r in payload.context_rules:
        if not (r.get("keyword") or "").strip():
            raise HTTPException(422, "上下文规则关键词不能为空")
    for et, act in payload.actions.items():
        if et not in ENTITY_TYPES or act not in NODE_ACTIONS:
            raise HTTPException(422, f"非法动作配置：{et} -> {act}")


class PolicyIn(BaseModel):
    name: str = Field(max_length=100)
    description: str = ""
    scope_type: str = "global"
    scope_id: str = ""
    priority: int = 100
    user_roles: list[str] = Field(default_factory=list)
    scenes: list[str] = Field(default_factory=list)
    regex_rules: list[dict] = Field(default_factory=list)
    dict_types: list[str] = Field(default_factory=list)
    context_rules: list[dict] = Field(default_factory=list)
    actions: dict[str, str] = Field(default_factory=dict)
    pre_llm_enabled: bool = True
    post_output_enabled: bool = True
    failure_strategy: str = "non_sensitive"
    enabled: bool = True


class PolicyOut(PolicyIn):
    id: int
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/masking-policies", response_model=list[PolicyOut], dependencies=ADMIN_ONLY)
async def list_policies(s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(MaskingPolicy).order_by(MaskingPolicy.priority, MaskingPolicy.id))).scalars().all()
    return rows


@router.post("/masking-policies", response_model=PolicyOut, dependencies=ADMIN_ONLY)
async def create_policy(payload: PolicyIn, u=Depends(require_role("super_admin", "admin")),
                        s: AsyncSession = Depends(get_session)):
    _validate_policy(payload)
    dup = (await s.execute(select(MaskingPolicy).where(MaskingPolicy.name == payload.name.strip()))).scalars().first()
    if dup:
        raise HTTPException(409, "同名策略已存在")
    data = payload.model_dump()
    data["name"] = payload.name.strip()
    p = MaskingPolicy(**data, created_by=u.username)
    s.add(p)
    await s.commit()
    await s.refresh(p)
    return p


@router.put("/masking-policies/{pid}", response_model=PolicyOut, dependencies=ADMIN_ONLY)
async def update_policy(pid: int, payload: PolicyIn, s: AsyncSession = Depends(get_session)):
    p = await s.get(MaskingPolicy, pid)
    if p is None:
        raise HTTPException(404, "策略不存在")
    _validate_policy(payload)
    dup = (await s.execute(select(MaskingPolicy).where(
        MaskingPolicy.name == payload.name.strip(), MaskingPolicy.id != pid))).scalars().first()
    if dup:
        raise HTTPException(409, "同名策略已存在")
    for k, v in payload.model_dump().items():
        setattr(p, k, v)
    p.name = payload.name.strip()
    await s.commit()
    await s.refresh(p)
    return p


@router.delete("/masking-policies/{pid}", dependencies=ADMIN_ONLY)
async def delete_policy(pid: int, s: AsyncSession = Depends(get_session)):
    p = await s.get(MaskingPolicy, pid)
    if p is None:
        raise HTTPException(404, "策略不存在")
    await s.delete(p)
    await s.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# 豁免
# ---------------------------------------------------------------------------

class ExemptionIn(BaseModel):
    user_id: str
    scope_type: str = "global"
    scope_id: str = ""
    entity_types: list[str] = Field(default_factory=list)
    reason: str = ""
    expires_at: datetime | None = None


class ExemptionOut(ExemptionIn):
    id: int
    granted_by: str
    created_at: datetime
    username: str = ""

    class Config:
        from_attributes = True


@router.get("/masking-exemptions", response_model=list[ExemptionOut], dependencies=ADMIN_ONLY)
async def list_exemptions(s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(MaskingExemption).order_by(MaskingExemption.id.desc()))).scalars().all()
    out = []
    for e in rows:
        uname = ""
        if e.user_id:
            u = await s.get(User, e.user_id)
            uname = u.username if u else ""
        item = ExemptionOut(
            id=e.id, user_id=str(e.user_id), scope_type=e.scope_type, scope_id=e.scope_id,
            entity_types=e.entity_types or [], reason=e.reason, expires_at=e.expires_at,
            granted_by=e.granted_by, created_at=e.created_at, username=uname)
        out.append(item)
    return out


@router.post("/masking-exemptions", response_model=ExemptionOut, dependencies=ADMIN_ONLY)
async def create_exemption(payload: ExemptionIn, u=Depends(require_role("super_admin", "admin")),
                           s: AsyncSession = Depends(get_session)):
    import uuid as _uuid
    if payload.scope_type not in SCOPES:
        raise HTTPException(422, f"不支持的作用域：{payload.scope_type}")
    if payload.scope_type != "global" and not payload.scope_id:
        raise HTTPException(422, "该作用域需要指定具体对象")
    for et in payload.entity_types:
        if et not in ENTITY_TYPES:
            raise HTTPException(422, f"不支持的实体类型：{et}")
    try:
        uid = _uuid.UUID(payload.user_id)
    except ValueError as e:
        raise HTTPException(422, "无效的用户 ID") from e
    user = await s.get(User, uid)
    if user is None:
        raise HTTPException(404, "用户不存在")
    e = MaskingExemption(
        user_id=uid, scope_type=payload.scope_type, scope_id=payload.scope_id,
        entity_types=payload.entity_types, reason=(payload.reason or "").strip(),
        granted_by=u.username, expires_at=payload.expires_at)
    s.add(e)
    await s.commit()
    await s.refresh(e)
    return ExemptionOut(id=e.id, user_id=str(e.user_id), scope_type=e.scope_type, scope_id=e.scope_id,
                        entity_types=e.entity_types or [], reason=e.reason, expires_at=e.expires_at,
                        granted_by=e.granted_by, created_at=e.created_at, username=user.username)


@router.delete("/masking-exemptions/{eid}", dependencies=ADMIN_ONLY)
async def delete_exemption(eid: int, s: AsyncSession = Depends(get_session)):
    e = await s.get(MaskingExemption, eid)
    if e is None:
        raise HTTPException(404, "豁免不存在")
    await s.delete(e)
    await s.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# 审计日志 / 全局配置
# ---------------------------------------------------------------------------

@router.get("/masking-logs", dependencies=ADMIN_ONLY)
async def list_logs(
    scene: str | None = Query(None),
    node: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    s: AsyncSession = Depends(get_session),
):
    q = select(MaskingLog)
    if scene in SCENES:
        q = q.where(MaskingLog.scene == scene)
    if node in ("pre_llm", "post_output"):
        q = q.where(MaskingLog.node == node)
    total = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await s.execute(
        q.order_by(MaskingLog.id.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"total": total, "items": [
        {"id": r.id, "username": r.username, "scene": r.scene, "node": r.node,
         "query": r.query, "policy_ids": r.policy_ids or [], "rule_hits": r.rule_hits or [],
         "masked_count": r.masked_count, "blocked": r.blocked, "exempted": r.exempted,
         "created_at": r.created_at} for r in rows]}


class GlobalConfigIn(BaseModel):
    enabled: bool | None = None
    pre_llm: bool | None = None
    post_output: bool | None = None
    failure_strategy: str | None = None
    hint: str | None = Field(default=None, max_length=100)


@router.get("/masking-global", dependencies=ADMIN_ONLY)
async def get_global(s: AsyncSession = Depends(get_session)):
    return await masking_svc.get_global_config(s)


@router.put("/masking-global", dependencies=ADMIN_ONLY)
async def put_global(payload: GlobalConfigIn, s: AsyncSession = Depends(get_session)):
    if payload.failure_strategy and payload.failure_strategy not in FAILURE_STRATEGIES:
        raise HTTPException(422, f"不支持的失败策略：{payload.failure_strategy}")
    await masking_svc.save_global_config(s, payload.model_dump(exclude_none=True))
    return await masking_svc.get_global_config(s)


# ---------------------------------------------------------------------------
# 预览沙箱：模拟查询+模拟角色 → 真实检索 → 原始 vs 脱敏对比
# ---------------------------------------------------------------------------

class SandboxIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    kb_ids: list[str] = Field(default_factory=list, max_length=12)
    library_ids: list[int] = Field(default_factory=list, max_length=12)
    mock_role: str = "viewer"
    scene: str = "search"
    top_k: int = Field(default=6, ge=1, le=15)


@router.post("/masking/sandbox", dependencies=ADMIN_ONLY)
async def sandbox(payload: SandboxIn, s: AsyncSession = Depends(get_session)):
    from kb_common.clients import dify_client, ragflow_client

    if payload.mock_role not in ("super_admin", "admin", "editor", "viewer"):
        raise HTTPException(422, f"不支持的角色：{payload.mock_role}")
    if payload.scene not in SCENES:
        raise HTTPException(422, f"不支持的场景：{payload.scene}")

    gcfg = await masking_svc.get_global_config(s)
    ctx = await masking_svc.load_mask_context(
        s, scene=payload.scene, user_role=payload.mock_role, user_id=None,
        scope_ids={f"kb:{k}" for k in payload.kb_ids} | {f"library:{i}" for i in payload.library_ids},
        node="pre_llm")
    base = {"global_enabled": gcfg.get("enabled", True),
            "pre_llm_enabled": gcfg.get("pre_llm", True),
            "policies_applied": [p["name"] for p in (ctx.policies if ctx else [])]}
    if ctx is None:
        return {**base, "masking_active": False, "raw": [], "masked": [], "detail": [],
                "note": "当前全局配置/作用域下无生效策略，返回内容未脱敏"}

    # 真实检索：本地 ES + 知识库镜像（dify/ragflow），fail-soft
    raw: list[dict] = []
    kb_ids = [k for k in payload.kb_ids if k]
    if kb_ids:
        from kb_common.models import Document
        from uuid import UUID as _UUID
        try:
            from kb_common.rag import searcher
            import asyncio as _asyncio
            r = await _asyncio.wait_for(searcher.hybrid(kb_ids, payload.query, payload.top_k, rerank=True), 60)
            ids = []
            for h in r:
                try:
                    ids.append(_UUID(str(h.get("document_id"))))
                except ValueError:
                    continue
            docs = (await s.execute(select(Document).where(
                Document.id.in_(ids), Document.kb_id.in_([_UUID(k) for k in kb_ids]),
                Document.is_deleted.is_(False)))).scalars().all()
            allowed = {str(d.id): d for d in docs}
            for h in r:
                doc = allowed.get(str(h.get("document_id")))
                if not doc:
                    continue
                raw.append({"content": h.get("text", "") or "", "document_title": doc.original_filename,
                            "score": h.get("score"), "source": "local"})
        except Exception as e:  # noqa: BLE001
            base["local_error"] = f"本地检索失败：{e.__class__.__name__}"
    lib_ids = payload.library_ids
    if lib_ids:
        libs = (await s.execute(select(KnowledgeLibrary).where(KnowledgeLibrary.id.in_(lib_ids)))).scalars().all()
        ds = [l.dataset_id for l in libs if l.platform == "dify"]
        rf = [l.dataset_id for l in libs if l.platform == "ragflow"]
        if ds:
            try:
                for h in await dify_client.retrieve(ds, payload.query, top_k=payload.top_k):
                    raw.append({"content": h.get("content") or "", "document_title": h.get("document_title") or "",
                                "score": h.get("score"), "source": "dify"})
            except Exception as e:  # noqa: BLE001
                base["dify_error"] = f"Dify 检索失败：{e.__class__.__name__}"
        if rf:
            try:
                for h in await ragflow_client.retrieve(rf, payload.query, top_k=payload.top_k):
                    raw.append({"content": h.get("content") or "", "document_title": h.get("document_title") or "",
                                "score": h.get("score"), "source": "ragflow"})
            except Exception as e:  # noqa: BLE001
                base["ragflow_error"] = f"RAGFlow 检索失败：{e.__class__.__name__}"

    kept, detail, summary = masking_svc.mask_hits(
        [dict(h) for h in raw], ctx, text_fields=("content",))
    masked_count = sum(h.count for h in summary)
    if masked_count:
        for h in kept:
            if h.get("document_title"):
                h["document_title"] = masking_svc.mask_title(h["document_title"], ctx)
    return {**base, "masking_active": True,
            "raw": raw, "masked": kept, "detail": detail,
            "summary": [{"rule": h.rule, "entity_type": h.entity_type, "count": h.count} for h in summary],
            "masked_count": masked_count,
            "exempted_types": sorted(ctx.exempt_types)}
