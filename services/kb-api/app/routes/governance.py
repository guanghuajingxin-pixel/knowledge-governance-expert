"""知识治理路由：治理标准（本地可管理 + 版本 + 审核流转）。

从「钉钉多维表只读代理」升级为本地可管理：
- 主表存当前对外展示版本的字段快照
- 版本表存所有历史版本（草稿/审核中/已发布/已驳回），支持回滚
- 提交审核时通过钉钉动作卡片通知审批人，审批人在页面完成通过/驳回

状态流转：
  新建 → draft → 提交审核 → reviewing → 通过 → published（主表快照更新）
                              → 驳回 → rejected（可再次编辑生成新版本）
  已发布 → 编辑 → 新建 draft 版本（主表不变，列表仍显示已发布版本）
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func

from app.deps import require_role
from kb_common.clients import dingtalk_client
from kb_common.database import short_session
from kb_common.models import GovernanceStandard, GovernanceStandardVersion, Setting

router = APIRouter(prefix="/api/v1/governance", tags=["governance"])


# ===================== Schemas =====================
class StandardIn(BaseModel):
    doc_type: str = ""
    code: str = ""
    version: str = ""
    effective_date: str = ""
    link: str = ""
    maintainer: str = ""


class SubmitReviewIn(BaseModel):
    reviewer_userid: str  # 钉钉审批人 userid
    reviewer_name: str = ""


class ReviewIn(BaseModel):
    comment: str = ""


# ===================== 工具函数 =====================
def _std_to_dict(s: GovernanceStandard) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "doc_type": s.doc_type,
        "code": s.code,
        "version": s.version,
        "status": s.latest_status,
        "effective_date": s.effective_date,
        "link": s.link,
        "maintainer": s.maintainer,
        "published_version_id": str(s.published_version_id) if s.published_version_id else None,
        "latest_version_id": str(s.latest_version_id) if s.latest_version_id else None,
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
    }


def _ver_to_dict(v: GovernanceStandardVersion) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "standard_id": str(v.standard_id),
        "version_no": v.version_no,
        "doc_type": v.doc_type,
        "code": v.code,
        "version": v.version,
        "status": v.status,
        "effective_date": v.effective_date,
        "link": v.link,
        "maintainer": v.maintainer,
        "created_by": v.created_by,
        "review_comment": v.review_comment,
        "reviewed_by": v.reviewed_by,
        "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else "",
        "created_at": v.created_at.isoformat() if v.created_at else "",
    }


async def _get_frontend_base_url() -> str:
    """前端 base URL（审批卡片按钮跳转用），优先 settings 表，回退 localhost。"""
    async with short_session() as s:
        row = (await s.execute(
            select(Setting).where(Setting.key == "frontend_base_url")
        )).scalar_one_or_none()
    if row and row.value:
        return row.value.rstrip("/")
    return "http://localhost:5173"


# ===================== 列表 / 新建 / 编辑 / 删除 =====================
@router.get("/standards")
async def list_standards(u=Depends(require_role("super_admin", "admin", "editor", "viewer"))):
    """治理标准列表：读本地数据库（主表快照）。"""
    async with short_session() as s:
        rows = (await s.execute(
            select(GovernanceStandard).order_by(GovernanceStandard.created_at.desc())
        )).scalars().all()
        items = [_std_to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.post("/standards")
async def create_standard(payload: StandardIn, u=Depends(require_role("super_admin", "admin", "editor"))):
    """新建标准：创建主表 + 第一个 draft 版本。"""
    async with short_session() as s:
        std = GovernanceStandard(
            doc_type=payload.doc_type, code=payload.code, version=payload.version,
            effective_date=payload.effective_date, link=payload.link,
            maintainer=payload.maintainer, latest_status="draft",
        )
        s.add(std)
        await s.flush()
        ver = GovernanceStandardVersion(
            standard_id=std.id, version_no=1,
            doc_type=payload.doc_type, code=payload.code, version=payload.version,
            effective_date=payload.effective_date, link=payload.link,
            maintainer=payload.maintainer, status="draft", created_by=u.username,
        )
        s.add(ver)
        await s.flush()
        std.latest_version_id = ver.id
        await s.commit()
        await s.refresh(std)
        return _std_to_dict(std)


@router.put("/standards/{std_id}")
async def update_standard(std_id: str, payload: StandardIn,
                          u=Depends(require_role("super_admin", "admin", "editor"))):
    """编辑标准：创建新版本（draft）。主表已发布版本不变。"""
    async with short_session() as s:
        std = await s.get(GovernanceStandard, std_id)
        if not std:
            raise HTTPException(404, "标准不存在")
        # 最新版本正在审核中时不允许编辑
        if std.latest_version_id:
            latest = await s.get(GovernanceStandardVersion, std.latest_version_id)
            if latest and latest.status == "reviewing":
                raise HTTPException(400, "该标准正在审核中，无法编辑")
        # 版本号 = 当前最大版本号 + 1
        max_no = (await s.execute(
            select(func.max(GovernanceStandardVersion.version_no))
            .where(GovernanceStandardVersion.standard_id == std.id)
        )).scalar() or 0
        ver = GovernanceStandardVersion(
            standard_id=std.id, version_no=max_no + 1,
            doc_type=payload.doc_type, code=payload.code, version=payload.version,
            effective_date=payload.effective_date, link=payload.link,
            maintainer=payload.maintainer, status="draft", created_by=u.username,
        )
        s.add(ver)
        await s.flush()
        std.latest_version_id = ver.id
        std.latest_status = "draft"
        # 尚无已发布版本时，主表快照跟随最新草稿
        if not std.published_version_id:
            std.doc_type = payload.doc_type
            std.code = payload.code
            std.version = payload.version
            std.effective_date = payload.effective_date
            std.link = payload.link
            std.maintainer = payload.maintainer
        await s.commit()
        await s.refresh(std)
        return _std_to_dict(std)


@router.delete("/standards/{std_id}")
async def delete_standard(std_id: str, u=Depends(require_role("super_admin", "admin"))):
    """删除标准（级联删除所有版本）。"""
    async with short_session() as s:
        std = await s.get(GovernanceStandard, std_id)
        if not std:
            raise HTTPException(404, "标准不存在")
        await s.delete(std)
        await s.commit()
    return {"ok": True}


# ===================== 版本 / 回滚 =====================
@router.get("/standards/{std_id}/versions")
async def list_versions(std_id: str, u=Depends(require_role("super_admin", "admin", "editor", "viewer"))):
    """历史版本列表（按版本号倒序）。"""
    async with short_session() as s:
        std = await s.get(GovernanceStandard, std_id)
        if not std:
            raise HTTPException(404, "标准不存在")
        rows = (await s.execute(
            select(GovernanceStandardVersion)
            .where(GovernanceStandardVersion.standard_id == std_id)
            .order_by(GovernanceStandardVersion.version_no.desc())
        )).scalars().all()
        items = [_ver_to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.post("/standards/{std_id}/versions/{ver_id}/rollback")
async def rollback_version(std_id: str, ver_id: str,
                           u=Depends(require_role("super_admin", "admin", "editor"))):
    """回滚到指定历史版本：以该版本内容创建一个新的 draft 版本。"""
    async with short_session() as s:
        std = await s.get(GovernanceStandard, std_id)
        if not std:
            raise HTTPException(404, "标准不存在")
        src = await s.get(GovernanceStandardVersion, ver_id)
        if not src or str(src.standard_id) != std_id:
            raise HTTPException(404, "目标版本不存在")
        max_no = (await s.execute(
            select(func.max(GovernanceStandardVersion.version_no))
            .where(GovernanceStandardVersion.standard_id == std.id)
        )).scalar() or 0
        new_ver = GovernanceStandardVersion(
            standard_id=std.id, version_no=max_no + 1,
            doc_type=src.doc_type, code=src.code, version=src.version,
            effective_date=src.effective_date, link=src.link,
            maintainer=src.maintainer, status="draft", created_by=u.username,
            review_comment=f"回滚自 V{src.version_no}",
        )
        s.add(new_ver)
        await s.flush()
        std.latest_version_id = new_ver.id
        std.latest_status = "draft"
        if not std.published_version_id:
            std.doc_type, std.code, std.version = src.doc_type, src.code, src.version
            std.effective_date, std.link, std.maintainer = src.effective_date, src.link, src.maintainer
        await s.commit()
        await s.refresh(std)
        return _std_to_dict(std)


# ===================== 审核流转 =====================
@router.post("/standards/{std_id}/submit-review")
async def submit_review(std_id: str, payload: SubmitReviewIn,
                        u=Depends(require_role("super_admin", "admin", "editor"))):
    """提交审核：最新版本 draft → reviewing，并向审批人发送钉钉动作卡片。"""
    async with short_session() as s:
        std = await s.get(GovernanceStandard, std_id)
        if not std or not std.latest_version_id:
            raise HTTPException(404, "标准或版本不存在")
        ver = await s.get(GovernanceStandardVersion, std.latest_version_id)
        if not ver:
            raise HTTPException(404, "最新版本不存在")
        if ver.status not in ("draft", "rejected"):
            raise HTTPException(400, f"当前版本状态为 {ver.status}，无法提交审核")
        ver.status = "reviewing"
        std.latest_status = "reviewing"
        await s.commit()

    # 发送钉钉动作卡片（失败不影响状态流转，仅提示）
    msg_error = None
    try:
        await dingtalk_client.sync_runtime_config()
        base_url = await _get_frontend_base_url()
        approve_url = f"{base_url}/govern?approve={std_id}&action=approve"
        reject_url = f"{base_url}/govern?approve={std_id}&action=reject"
        title = f"知识治理标准待审核：{ver.doc_type or '未命名'}"
        text = (
            f"**{ver.doc_type}**\n\n"
            f"- 类型编号：{ver.code}\n"
            f"- 版本：{ver.version}\n"
            f"- 维护人：{ver.maintainer}\n"
            f"- 提交人：{u.username}\n"
            f"- 生效日期：{ver.effective_date}\n\n"
            f"请点击下方按钮进行审批。"
        )
        buttons = [
            {"title": "通过", "actionURL": approve_url},
            {"title": "驳回", "actionURL": reject_url},
        ]
        await dingtalk_client.send_action_card(
            user_ids=[payload.reviewer_userid], title=title, text=text, buttons=buttons,
        )
    except Exception as e:  # noqa: BLE001
        msg_error = str(e)

    return {"ok": True, "message_error": msg_error}


@router.post("/standards/{std_id}/approve")
async def approve_standard(std_id: str, payload: ReviewIn,
                           u=Depends(require_role("super_admin", "admin"))):
    """审核通过：版本 reviewing → published，主表快照更新。"""
    async with short_session() as s:
        std = await s.get(GovernanceStandard, std_id)
        if not std or not std.latest_version_id:
            raise HTTPException(404, "标准或版本不存在")
        ver = await s.get(GovernanceStandardVersion, std.latest_version_id)
        if not ver or ver.status != "reviewing":
            raise HTTPException(400, "当前版本不在审核中，无法通过")
        ver.status = "published"
        ver.review_comment = payload.comment
        ver.reviewed_by = u.username
        ver.reviewed_at = datetime.now()
        # 主表快照更新为已发布版本
        std.published_version_id = ver.id
        std.latest_status = "published"
        std.doc_type = ver.doc_type
        std.code = ver.code
        std.version = ver.version
        std.effective_date = ver.effective_date
        std.link = ver.link
        std.maintainer = ver.maintainer
        await s.commit()
        await s.refresh(std)
        return _std_to_dict(std)


@router.post("/standards/{std_id}/reject")
async def reject_standard(std_id: str, payload: ReviewIn,
                          u=Depends(require_role("super_admin", "admin"))):
    """审核驳回：版本 reviewing → rejected（可再次编辑生成新版本）。"""
    async with short_session() as s:
        std = await s.get(GovernanceStandard, std_id)
        if not std or not std.latest_version_id:
            raise HTTPException(404, "标准或版本不存在")
        ver = await s.get(GovernanceStandardVersion, std.latest_version_id)
        if not ver or ver.status != "reviewing":
            raise HTTPException(400, "当前版本不在审核中，无法驳回")
        ver.status = "rejected"
        ver.review_comment = payload.comment
        ver.reviewed_by = u.username
        ver.reviewed_at = datetime.now()
        std.latest_status = "rejected"
        await s.commit()
        await s.refresh(std)
        return _std_to_dict(std)


# ===================== 钉钉通讯录搜索（选择审批人） =====================
@router.get("/dingtalk/users/search")
async def search_dingtalk_users(q: str, u=Depends(require_role("super_admin", "admin", "editor"))):
    """按姓名搜索钉钉通讯录，用于选择审批人。"""
    if not q.strip():
        return {"items": []}
    await dingtalk_client.sync_runtime_config()
    try:
        items = await dingtalk_client.search_users_by_name(q.strip())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))
    return {"items": items}


# ===================== 从钉钉多维表导入（初始化） =====================
@router.post("/standards/import-dingtalk")
async def import_from_dingtalk(u=Depends(require_role("super_admin", "admin"))):
    """从钉钉多维表《杰克知识管理规范》导入到本地（仅导入本地不存在的编号）。"""
    await dingtalk_client.sync_runtime_config()
    records = await dingtalk_client.list_aitable_records(
        dingtalk_client.STANDARDS_BASE_ID, dingtalk_client.STANDARDS_SHEET_ID
    )
    _F_DOC_TYPE, _F_CODE = "文档类型", "类型编号"
    _F_LINK, _F_MAINTAINER = "规范链接", "维护人"
    _F_DATE, _F_VERSION, _F_STATUS = "生效日期", "版本号", "文档状态"

    def _as_text(val):
        if isinstance(val, dict):
            return str(val.get("name") or val.get("text") or val.get("link") or "")
        return "" if val is None else str(val)

    def _as_date(val):
        if isinstance(val, (int, float)):
            try:
                return datetime.fromtimestamp(val / 1000).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                return ""
        return str(val or "")[:10]

    user_ids = []
    for rec in records:
        for m in rec.get("fields", {}).get(_F_MAINTAINER) or []:
            uid = m.get("userId") or m.get("unionId") if isinstance(m, dict) else m
            if uid:
                user_ids.append(str(uid))
    name_map = await dingtalk_client.get_user_name_map(user_ids) if user_ids else {}

    imported = 0
    async with short_session() as s:
        existing_codes = {
            r[0] for r in (await s.execute(select(GovernanceStandard.code))).all()
        }
        for rec in records:
            f = rec.get("fields", {})
            code = _as_text(f.get(_F_CODE))
            if not code or code in existing_codes:
                continue
            maintainers = []
            for m in f.get(_F_MAINTAINER) or []:
                if isinstance(m, dict):
                    name = m.get("name") or m.get("nickName") or name_map.get(
                        str(m.get("userId") or m.get("unionId") or ""))
                    maintainers.append(str(name or ""))
            maintainer = "、".join(dict.fromkeys(m for m in maintainers if m)) or "—"
            status_text = _as_text(f.get(_F_STATUS))
            ver_status = "published" if status_text == "已发布" else "draft"
            std = GovernanceStandard(
                doc_type=_as_text(f.get(_F_DOC_TYPE)), code=code,
                version=_as_text(f.get(_F_VERSION)),
                effective_date=_as_date(f.get(_F_DATE)),
                link=_as_text(f.get(_F_LINK)), maintainer=maintainer,
                latest_status=ver_status,
            )
            s.add(std)
            await s.flush()
            ver = GovernanceStandardVersion(
                standard_id=std.id, version_no=1,
                doc_type=std.doc_type, code=std.code, version=std.version,
                effective_date=std.effective_date, link=std.link,
                maintainer=std.maintainer, status=ver_status, created_by=u.username,
            )
            s.add(ver)
            await s.flush()
            std.latest_version_id = ver.id
            if ver_status == "published":
                std.published_version_id = ver.id
            imported += 1
        await s.commit()
    return {"ok": True, "imported": imported}
