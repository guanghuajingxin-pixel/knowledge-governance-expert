from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from kb_common.database import get_session
from kb_common.models import Setting
from app.deps import require_role
from kb_common.config import get_settings

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# 可配置项白名单（is_secret=true 的只回显 key，不回显 value）
KEYS = {
    "llm_base_url": ("LLM 服务地址", False),
    "llm_api_key": ("LLM API Key", True),
    "llm_model": ("LLM 模型名", False),
    "mineru_api_key": ("MinerU API Key", True),
}


@router.get("")
async def get_settings_api(u=Depends(require_role("super_admin", "admin")),
                           s: AsyncSession = Depends(get_session)):
    out = {}
    for k, (label, secret) in KEYS.items():
        row = (await s.execute(select(Setting).where(Setting.key == k))).scalar_one_or_none()
        val = row.value if row else getattr(get_settings(), k, "")
        out[k] = {"label": label, "value": "" if (secret and val) else val,
                  "is_set": bool(val), "is_secret": secret}
    return out


class SettingIn(BaseModel):
    key: str
    value: str


@router.put("")
async def set_settings_api(body: SettingIn, u=Depends(require_role("super_admin", "admin")),
                          s: AsyncSession = Depends(get_session)):
    if body.key not in KEYS:
        raise HTTPException(400, "不支持的配置项")
    secret = KEYS[body.key][1]
    row = (await s.execute(select(Setting).where(Setting.key == body.key))).scalar_one_or_none()
    if row:
        row.value = body.value
    else:
        s.add(Setting(key=body.key, value=body.value, is_secret=secret))
    await s.commit()
    return {"ok": True}
