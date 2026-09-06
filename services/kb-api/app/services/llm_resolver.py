"""智能问答 LLM 配置解析：从 llm_profiles 多供应商配置中解析当前应使用的模型。

优先级：
1. 请求指定 profile_id + model（校验该模型在该供应商下已生效）
2. 仅指定 model 名 → 匹配任意供应商下已生效的同名模型
3. 全局默认模型（is_default=true 且 enabled）
4. 旧版 settings 表单模型配置（llm_base_url/llm_api_key/llm_model）兜底
"""
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.models import LLMProfile, Setting
from kb_common.config import get_settings


def _parse_models(raw: str) -> list[dict]:
    try:
        return [m for m in json.loads(raw or "[]") if isinstance(m, dict) and m.get("name")]
    except Exception:
        return []


async def resolve_llm_config(s: AsyncSession, profile_id: str = "", model: str = "") -> dict:
    """返回 {base_url, api_key, model}。"""
    rows = (await s.execute(select(LLMProfile))).scalars().all()

    enabled_by_name: dict[str, tuple] = {}
    default_entry: tuple | None = None
    for p in rows:
        for m in _parse_models(p.models):
            if m.get("enabled"):
                enabled_by_name.setdefault(m["name"], (p, m))
                if m.get("is_default") and default_entry is None:
                    default_entry = (p, m)

    pid = (profile_id or "").strip()
    mname = (model or "").strip()
    if mname.startswith(("（", "(")):
        mname = ""

    chosen: tuple | None = None
    if mname:
        if pid:
            for p in rows:
                if str(p.id) == pid:
                    for m in _parse_models(p.models):
                        if m.get("name") == mname and m.get("enabled"):
                            chosen = (p, m)
        if chosen is None:
            chosen = enabled_by_name.get(mname)
    if chosen is None:
        chosen = default_entry

    if chosen is not None:
        p, m = chosen
        return {"base_url": p.base_url, "api_key": p.api_key, "model": m["name"]}

    # 旧版 settings 兜底
    async def _eff(key: str) -> str:
        row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        return (row.value if row else None) or getattr(get_settings(), key)

    return {
        "base_url": await _eff("llm_base_url"),
        "api_key": await _eff("llm_api_key"),
        "model": mname or await _eff("llm_model"),
    }
