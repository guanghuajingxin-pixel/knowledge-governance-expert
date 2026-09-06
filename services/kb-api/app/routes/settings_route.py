import asyncio
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from kb_common.database import get_session
from kb_common.models import Setting, DifyProfile, LLMProfile
from app.deps import require_role, get_principal
from kb_common.config import get_settings
from kb_common.clients import llm_client

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# 可配置项白名单（is_secret=true 的只回显 key，不回显 value）
KEYS = {
    "llm_base_url": ("LLM 服务地址", False),
    "llm_api_key": ("LLM API Key", True),
    "llm_model": ("LLM 模型名", False),
    "llm_provider": ("LLM 供应商 (deepseek/zhipu/custom)", False),
    "mineru_api_key": ("MinerU API Key", True),
    "dify_base_url": ("Dify 服务地址", False),
    "dify_api_key": ("Dify API Key", True),
    "dify_dataset_ids": ("Dify 默认数据集 ID（逗号分隔）", False),
    "dingtalk_app_key": ("钉钉 AppKey", False),
    "dingtalk_app_secret": ("钉钉 AppSecret", True),
    "dingtalk_operator_union_id": ("钉钉操作人 UnionId", False),
}


def _mask_secret(val: str) -> str:
    """将密钥掩码为 sk-****3456 形式，保留首尾用于辨识。"""
    if not val:
        return ""
    if len(val) <= 8:
        return "****"
    return val[:3] + "****" + val[-4:]


@router.get("")
async def get_settings_api(u=Depends(require_role("super_admin", "admin")),
                           s: AsyncSession = Depends(get_session)):
    out = {}
    for k, (label, secret) in KEYS.items():
        row = (await s.execute(select(Setting).where(Setting.key == k))).scalar_one_or_none()
        val = row.value if row else getattr(get_settings(), k, "")
        out[k] = {"label": label, "value": _mask_secret(val) if (secret and val) else val,
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
    # 密钥字段提交掩码值（含 ****）时视为未修改，保留原值
    if secret and "****" in body.value:
        return {"ok": True, "masked": True}
    row = (await s.execute(select(Setting).where(Setting.key == body.key))).scalar_one_or_none()
    if row:
        row.value = body.value
    else:
        s.add(Setting(key=body.key, value=body.value, is_secret=secret))
    await s.commit()
    return {"ok": True}


class TestLLMIn(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@router.post("/test-llm")
async def test_llm_api(body: TestLLMIn, u=Depends(require_role("super_admin", "admin")),
                       s: AsyncSession = Depends(get_session)):
    """LLM 连通性测试：用弹窗中填写的参数发一次最小请求。

    api_key 留空时回退到已配置的密钥（密钥不回显，测试无需重复输入）。
    """
    base_url = (body.base_url or getattr(get_settings(), "llm_base_url", "")).strip()
    model = (body.model or getattr(get_settings(), "llm_model", "")).strip()
    api_key = body.api_key.strip()
    if not api_key:
        row = (await s.execute(select(Setting).where(Setting.key == "llm_api_key"))).scalar_one_or_none()
        api_key = (row.value if row else "") or getattr(get_settings(), "llm_api_key", "")
    if not base_url:
        return {"ok": False, "message": "请先填写服务地址"}
    if not model:
        return {"ok": False, "message": "请先填写模型名"}
    if not api_key:
        return {"ok": False, "message": "请先填写 API Key"}

    t0 = time.perf_counter()
    try:
        reply = await asyncio.wait_for(
            llm_client.chat([{"role": "user", "content": "Hi, 请只回复两个字：pong"}],
                            model=model, base_url=base_url, api_key=api_key),
            timeout=20)
    except asyncio.TimeoutError:
        return {"ok": False, "message": "连接超时（20s），请检查服务地址与网络"}
    except Exception as e:
        return {"ok": False, "message": _friendly_llm_error(e)}
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return {"ok": True, "latency_ms": latency_ms, "model": model,
            "reply": (reply or "").strip()[:80]}


def _friendly_llm_error(e: Exception) -> str:
    """把 openai SDK 异常映射为可操作的中文提示。"""
    name = type(e).__name__
    status = getattr(e, "status_code", None)
    if name == "AuthenticationError" or status == 401:
        return "API Key 无效或已过期，请检查后重试"
    if name == "PermissionDeniedError" or status == 403:
        return "API Key 无此模型的访问权限"
    if name == "NotFoundError" or status == 404:
        return "服务地址或模型名不存在，请检查拼写（注意 /v1 后缀）"
    if name == "RateLimitError" or status == 429:
        return "请求触发限流（429），Key 可用但请稍后重试"
    if name == "BadRequestError" or status == 400:
        return f"请求被拒绝（400）：{e}"
    if name == "InternalServerError" or (isinstance(status, int) and 500 <= status < 600):
        return f"服务端错误（{status}），请检查服务地址是否正确"
    if name in ("APIConnectionError", "APITimeoutError", "ConnectError", "TimeoutError"):
        return "无法连接到服务地址（网络不通/超时/DNS 解析失败），请检查地址与网络"
    return f"连接失败：{e}"


class TestDingtalkIn(BaseModel):
    app_key: str = ""
    app_secret: str = ""
    operator_union_id: str = ""


async def _effective_setting(s: AsyncSession, key: str) -> str:
    row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return (row.value if row else "") or getattr(get_settings(), key, "")


@router.post("/test-dingtalk")
async def test_dingtalk_api(body: TestDingtalkIn, u=Depends(require_role("super_admin", "admin")),
                            s: AsyncSession = Depends(get_session)):
    """钉钉连通性测试：两步验证。

    1) 用 AppKey/AppSecret 换 accessToken（验证应用凭证）
    2) 用操作人 UnionId 拉取可见知识库列表（验证 unionId 与知识库读权限）
    Secret 留空时回退已配置值（不回显，测试无需重复输入）。
    """
    from kb_common.clients import dingtalk_client

    app_key = (body.app_key or await _effective_setting(s, "dingtalk_app_key")).strip()
    app_secret = (body.app_secret or await _effective_setting(s, "dingtalk_app_secret")).strip()
    union_id = (body.operator_union_id or await _effective_setting(s, "dingtalk_operator_union_id")).strip()
    if not app_key or not app_secret:
        return {"ok": False, "message": "请先填写 AppKey 与 AppSecret"}
    if not union_id:
        return {"ok": False, "message": "请先填写操作人 UnionId"}

    # 用测试参数临时覆盖运行时配置（含缓存 token 的凭证指纹校验），结束后恢复
    st = get_settings()
    backup = (st.dingtalk_app_key, st.dingtalk_app_secret, st.dingtalk_operator_union_id)
    st.dingtalk_app_key, st.dingtalk_app_secret, st.dingtalk_operator_union_id = app_key, app_secret, union_id
    t0 = time.perf_counter()
    try:
        await dingtalk_client._get_access_token()
        workspaces = await dingtalk_client.list_workspaces()
    except httpx.HTTPStatusError as e:
        return {"ok": False, "message": _friendly_dingtalk_error(e)}
    except RuntimeError as e:
        return {"ok": False, "message": str(e)}
    except Exception as e:
        return {"ok": False, "message": f"连接失败：{e}"}
    finally:
        st.dingtalk_app_key, st.dingtalk_app_secret, st.dingtalk_operator_union_id = backup
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return {"ok": True, "latency_ms": latency_ms, "workspace_count": len(workspaces),
            "message": f"验证通过，操作人可见 {len(workspaces)} 个知识库"}


def _friendly_dingtalk_error(e: httpx.HTTPStatusError) -> str:
    """把钉钉 API HTTP 错误映射为可操作的中文提示。"""
    status = e.response.status_code
    detail = ""
    try:
        data = e.response.json()
        detail = data.get("message") or data.get("errmsg") or ""
    except Exception:
        pass
    if status in (401, 403):
        return f"鉴权失败（{status}）：请检查 AppKey/AppSecret 与应用权限。{detail}"
    if "unionId" in detail or "operator" in detail.lower():
        return f"操作人 UnionId 无效或无知识库读权限：{detail}"
    if status == 400:
        return f"请求被拒绝（400）：{detail or '请检查 AppKey/AppSecret 是否正确'}"
    if status >= 500:
        return f"钉钉服务端错误（{status}），请稍后重试"
    return f"连接失败（{status}）：{detail or e}"


# ============ Dify 多配置（多条只能生效一条） ============

class TestDifyIn(BaseModel):
    base_url: str = ""
    api_key: str = ""
    profile_id: str = ""   # 编辑态 Key 为掩码时，回退该 profile 已存 Key


@router.post("/test-dify")
async def test_dify_api(body: TestDifyIn, u=Depends(require_role("super_admin", "admin")),
                        s: AsyncSession = Depends(get_session)):
    """Dify 连通性测试：用给定端点+Key 调 /datasets，验证地址与 Key 有效性。"""
    base_url = body.base_url.strip().rstrip("/")
    api_key = body.api_key.strip()
    if (not api_key or "****" in api_key) and body.profile_id:
        try:
            pid = uuid.UUID(body.profile_id)
            row = (await s.execute(select(DifyProfile).where(DifyProfile.id == pid))).scalar_one_or_none()
            if row and row.api_key:
                api_key = row.api_key
        except ValueError:
            pass
    if not api_key:
        api_key = await _effective_setting(s, "dify_api_key")
    if not base_url:
        return {"ok": False, "message": "请先填写服务地址"}
    if not api_key:
        return {"ok": False, "message": "请先填写 API Key"}

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{base_url}/datasets",
                            headers={"Authorization": f"Bearer {api_key}"},
                            params={"page": 1, "limit": 1})
    except Exception:
        return {"ok": False, "message": "无法连接到服务地址（网络不通/超时/DNS 失败），请检查地址"}
    if r.status_code == 401:
        return {"ok": False, "message": "API Key 无效或已过期，请检查后重试"}
    if r.status_code == 403:
        return {"ok": False, "message": "API Key 无访问知识库权限"}
    if r.status_code == 404:
        return {"ok": False, "message": "端点不存在，请检查地址（需含端口与 /v1，如 http://127.0.0.1:8088/v1）"}
    if r.status_code >= 500:
        return {"ok": False, "message": f"Dify 服务端错误（{r.status_code}），请检查服务状态"}
    if r.status_code != 200:
        return {"ok": False, "message": f"连接失败（{r.status_code}）：{r.text[:120]}"}
    total = (r.json() or {}).get("total")
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return {"ok": True, "latency_ms": latency_ms,
            "message": f"连接成功，可见 {total if total is not None else '?'} 个数据集"}


class TestMinerUIn(BaseModel):
    api_key: str = ""


# 非对话类模型关键词：智能问答只展示推理模型，embedding/rerank/语音图像等不出现
_LLM_MODEL_EXCLUDE = (
    "embedding", "-emb", "rerank", "whisper", "tts", "stt", "asr",
    "dall-e", "moderation", "image", "audio", "speech", "clip", "bge-",
    "text-embedding", "instruct-embedding", "sdxl", "stable-diffusion",
)


@router.get("/llm-models")
async def list_llm_models(base_url: str = "", api_key: str = "",
                          u=Depends(require_role("super_admin", "admin")),
                          s: AsyncSession = Depends(get_session)):
    """拉取模型供应商可用模型列表（OpenAI 兼容 /models），仅返回推理类模型。"""
    base_url = base_url.strip().rstrip("/")
    api_key = api_key.strip()
    if not api_key:
        api_key = await _effective_setting(s, "llm_api_key")
    if not base_url or not api_key:
        return {"ok": False, "models": [], "message": "请先填写服务地址与 API Key"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
    except Exception:
        return {"ok": False, "models": [], "message": "无法连接到服务地址"}
    if r.status_code in (401, 403):
        return {"ok": False, "models": [], "message": "API Key 无效或已过期"}
    if r.status_code != 200:
        return {"ok": False, "models": [], "message": f"获取模型列表失败（{r.status_code}）"}
    try:
        data = r.json()
        ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
    except Exception:
        return {"ok": False, "models": [], "message": "响应格式异常"}
    models = sorted(i for i in ids if not any(x in i.lower() for x in _LLM_MODEL_EXCLUDE))
    return {"ok": True, "models": models}


@router.post("/test-mineru")
async def test_mineru_api(body: TestMinerUIn, u=Depends(require_role("super_admin", "admin")),
                          s: AsyncSession = Depends(get_session)):
    """MinerU 连通性测试：用 Key 申请一个上传批次（不传文件、即弃），验证 Key 有效性。"""
    api_key = (body.api_key or await _effective_setting(s, "mineru_api_key")).strip()
    if not api_key:
        return {"ok": False, "message": "请先填写 API Key"}
    base = get_settings().mineru_api_url.rstrip("/")
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{base}/file-urls/batch",
                             headers={"Authorization": f"Bearer {api_key}"},
                             json={"enable_formula": False, "enable_table": False,
                                   "language": "ch", "files": [{"name": "connectivity-test.txt"}]})
    except Exception:
        return {"ok": False, "message": "无法连接到 MinerU 服务（网络不通/超时），请检查网络"}
    if r.status_code in (401, 403):
        return {"ok": False, "message": "API Key 无效或已过期，请检查后重试"}
    try:
        payload = r.json()
    except Exception:
        return {"ok": False, "message": f"响应异常（{r.status_code}）：{r.text[:120]}"}
    if r.status_code != 200 or payload.get("code") not in (0, "0", None):
        return {"ok": False, "message": f"连接失败（{r.status_code}）：{payload.get('msg') or r.text[:120]}"}
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return {"ok": True, "latency_ms": latency_ms, "message": "Key 有效，云解析服务可用"}


def _mask_api_key(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 8:
        return "****"
    return val[:3] + "****" + val[-4:]


def _safe_uuid(val: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        raise HTTPException(400, "无效的配置 ID")


def _profile_to_dict(p: DifyProfile, mask: bool = True) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "base_url": p.base_url,
        "api_key": _mask_api_key(p.api_key) if mask else p.api_key,
        "dataset_ids": p.dataset_ids,
        "enabled": p.enabled,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


class DifyProfileIn(BaseModel):
    name: str
    base_url: str = ""
    api_key: str = ""
    dataset_ids: str = ""


@router.get("/dify-profiles")
async def list_dify_profiles(u=Depends(require_role("super_admin", "admin")),
                              s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(DifyProfile).order_by(DifyProfile.created_at))).scalars().all()
    return [_profile_to_dict(r) for r in rows]


@router.post("/dify-profiles")
async def create_dify_profile(body: DifyProfileIn,
                               u=Depends(require_role("super_admin", "admin")),
                               s: AsyncSession = Depends(get_session)):
    if not body.name.strip():
        raise HTTPException(400, "配置名称不能为空")
    profile = DifyProfile(
        name=body.name.strip(),
        base_url=body.base_url.strip(),
        api_key=body.api_key.strip(),
        dataset_ids=body.dataset_ids.strip(),
        enabled=False,
    )
    s.add(profile)
    await s.commit()
    await s.refresh(profile)
    return _profile_to_dict(profile)


@router.put("/dify-profiles/{profile_id}")
async def update_dify_profile(profile_id: str, body: DifyProfileIn,
                               u=Depends(require_role("super_admin", "admin")),
                               s: AsyncSession = Depends(get_session)):
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(400, "无效的配置 ID")
    row = (await s.execute(select(DifyProfile).where(DifyProfile.id == pid))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "配置不存在")
    row.name = body.name.strip()
    row.base_url = body.base_url.strip()
    # 密钥含 **** 视为未修改
    if body.api_key and "****" not in body.api_key:
        row.api_key = body.api_key.strip()
    row.dataset_ids = body.dataset_ids.strip()
    await s.commit()
    await s.refresh(row)
    return _profile_to_dict(row)


@router.delete("/dify-profiles/{profile_id}")
async def delete_dify_profile(profile_id: str,
                               u=Depends(require_role("super_admin", "admin")),
                               s: AsyncSession = Depends(get_session)):
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(400, "无效的配置 ID")
    row = (await s.execute(select(DifyProfile).where(DifyProfile.id == pid))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "配置不存在")
    was_enabled = row.enabled
    await s.delete(row)
    await s.commit()
    # 若删除的是启用项，自动启用第一条
    if was_enabled:
        first = (await s.execute(select(DifyProfile).order_by(DifyProfile.created_at).limit(1))).scalar_one_or_none()
        if first:
            first.enabled = True
            await s.commit()
    return {"ok": True}


@router.put("/dify-profiles/{profile_id}/enable")
async def enable_dify_profile(profile_id: str,
                               u=Depends(require_role("super_admin", "admin")),
                               s: AsyncSession = Depends(get_session)):
    """启用指定配置，同时禁用其他所有配置（只能生效一条）。"""
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(400, "无效的配置 ID")
    row = (await s.execute(select(DifyProfile).where(DifyProfile.id == pid))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "配置不存在")
    # 先禁用全部，再启用目标
    await s.execute(update(DifyProfile).values(enabled=False))
    row.enabled = True
    await s.commit()
    # 同步写入 settings 表，使 dify_client 能立即读取
    from kb_common.models import Setting as SettingModel
    for k, v in [("dify_base_url", row.base_url), ("dify_api_key", row.api_key),
                 ("dify_dataset_ids", row.dataset_ids)]:
        existing = (await s.execute(select(SettingModel).where(SettingModel.key == k))).scalar_one_or_none()
        if existing:
            existing.value = v
        else:
            s.add(SettingModel(key=k, value=v, is_secret=(k == "dify_api_key")))
    await s.commit()
    return {"ok": True}


# ==================== LLM 供应商配置（多供应商 × 多模型） ====================
import json as _json

# 非对话类模型关键词：智能问答只展示推理模型
_LLM_MODEL_EXCLUDE_KW = (
    "embedding", "-emb", "rerank", "whisper", "tts", "stt", "asr",
    "dall-e", "moderation", "image", "audio", "speech", "clip", "bge-",
    "text-embedding", "instruct-embedding", "sdxl", "stable-diffusion",
)


def _parse_models(raw: str) -> list[dict]:
    try:
        data = _json.loads(raw or "[]")
        return [m for m in data if isinstance(m, dict) and m.get("name")]
    except Exception:
        return []


def _dump_models(models: list[dict]) -> str:
    clean = []
    for m in models:
        name = str(m.get("name", "")).strip()
        if not name:
            continue
        clean.append({
            "name": name,
            "enabled": bool(m.get("enabled")),
            "is_default": bool(m.get("is_default")),
        })
    return _json.dumps(clean, ensure_ascii=False)


def _llm_to_dict(p: LLMProfile, mask: bool = True) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "provider": p.provider,
        "base_url": p.base_url,
        "api_key": _mask_api_key(p.api_key) if mask else p.api_key,
        "has_key": bool(p.api_key),
        "models": _parse_models(p.models),
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


async def _fetch_remote_models(base_url: str, api_key: str) -> list[str]:
    """调供应商 /models 拉取推理类模型 ID 列表。失败抛 HTTPException。"""
    base_url = base_url.strip().rstrip("/")
    if not base_url or not api_key:
        raise HTTPException(400, "请先填写服务地址与 API Key")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
    except Exception:
        raise HTTPException(502, "无法连接到服务地址")
    if r.status_code in (401, 403):
        raise HTTPException(400, "API Key 无效或已过期")
    if r.status_code != 200:
        raise HTTPException(502, f"获取模型列表失败（{r.status_code}）")
    try:
        ids = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
    except Exception:
        raise HTTPException(502, "响应格式异常")
    return sorted(i for i in ids if not any(x in i.lower() for x in _LLM_MODEL_EXCLUDE_KW))


class LLMProfileIn(BaseModel):
    name: str
    provider: str = "custom"
    base_url: str = ""
    api_key: str = ""          # 留空且已配置 → 保留原 Key
    models: list[dict] = []


@router.get("/llm-profiles")
async def list_llm_profiles(u=Depends(require_role("super_admin", "admin")),
                            s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(LLMProfile).order_by(LLMProfile.created_at))).scalars().all()
    return [_llm_to_dict(r) for r in rows]


@router.post("/llm-profiles")
async def create_llm_profile(body: LLMProfileIn,
                             u=Depends(require_role("super_admin", "admin")),
                             s: AsyncSession = Depends(get_session)):
    if not body.name.strip():
        raise HTTPException(400, "配置名称不能为空")
    has_default = any(m.get("is_default") for m in body.models)
    profile = LLMProfile(
        name=body.name.strip(),
        provider=body.provider.strip() or "custom",
        base_url=body.base_url.strip().rstrip("/"),
        api_key=body.api_key.strip(),
        models=_dump_models(body.models),
    )
    s.add(profile)
    await s.flush()
    if has_default:
        await _clear_other_defaults(s, str(profile.id))
    await s.commit()
    return {"ok": True, "id": str(profile.id)}


@router.put("/llm-profiles/{profile_id}")
async def update_llm_profile(profile_id: str, body: LLMProfileIn,
                             u=Depends(require_role("super_admin", "admin")),
                             s: AsyncSession = Depends(get_session)):
    pid = _safe_uuid(profile_id)
    row = (await s.execute(select(LLMProfile).where(LLMProfile.id == pid))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "配置不存在")
    row.name = body.name.strip() or row.name
    row.provider = body.provider.strip() or "custom"
    row.base_url = body.base_url.strip().rstrip("/")
    # Key 含掩码或留空 → 保留原值
    new_key = body.api_key.strip()
    if new_key and "****" not in new_key:
        row.api_key = new_key
    if body.models:
        # 停用 → 强制取消默认；本配置内只允许一个默认
        default_seen = False
        for m in body.models:
            if not m.get("enabled"):
                m["is_default"] = False
            if m.get("is_default"):
                if default_seen:
                    m["is_default"] = False
                default_seen = True
        row.models = _dump_models(body.models)
        if default_seen:
            await _clear_other_defaults(s, profile_id)
    await s.commit()
    return {"ok": True}


@router.delete("/llm-profiles/{profile_id}")
async def delete_llm_profile(profile_id: str,
                             u=Depends(require_role("super_admin", "admin")),
                             s: AsyncSession = Depends(get_session)):
    pid = _safe_uuid(profile_id)
    row = (await s.execute(select(LLMProfile).where(LLMProfile.id == pid))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "配置不存在")
    await s.delete(row)
    await s.commit()
    return {"ok": True}


@router.post("/llm-profiles/{profile_id}/refresh-models")
async def refresh_llm_profile_models(profile_id: str,
                                     u=Depends(require_role("super_admin", "admin")),
                                     s: AsyncSession = Depends(get_session)):
    """拉取供应商可用推理模型，与已勾选状态合并（保留 enabled/is_default）。"""
    pid = _safe_uuid(profile_id)
    row = (await s.execute(select(LLMProfile).where(LLMProfile.id == pid))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "配置不存在")
    if not row.api_key:
        raise HTTPException(400, "请先保存 API Key")
    remote = await _fetch_remote_models(row.base_url, row.api_key)
    existing = {m["name"]: m for m in _parse_models(row.models)}
    merged: list[dict] = []
    for name in remote:
        old = existing.get(name, {})
        merged.append({
            "name": name,
            "enabled": bool(old.get("enabled", False)),
            "is_default": bool(old.get("is_default", False)),
        })
    # 远程已下线但本地曾配置的模型保留在末尾，避免静默丢失
    for name, old in existing.items():
        if name not in set(remote):
            merged.append({"name": name, "enabled": bool(old.get("enabled")),
                           "is_default": bool(old.get("is_default"))})
    row.models = _dump_models(merged)
    await s.commit()
    return {"ok": True, "models": merged}


async def _clear_other_defaults(s: AsyncSession, keep_profile_id: str) -> None:
    """全局默认互斥：清除其它供应商配置中模型的 is_default 标记。"""
    keep_pid = _safe_uuid(keep_profile_id)
    rows = (await s.execute(select(LLMProfile).where(LLMProfile.id != keep_pid))).scalars().all()
    for r in rows:
        models = _parse_models(r.models)
        changed = False
        for m in models:
            if m.get("is_default"):
                m["is_default"] = False
                changed = True
        if changed:
            r.models = _dump_models(models)


@router.get("/llm-enabled-models")
async def list_enabled_llm_models(u=Depends(get_principal),
                                  s: AsyncSession = Depends(get_session)):
    """智能问答模型下拉：所有 enabled=true 的模型；is_default 为新会话默认。"""
    rows = (await s.execute(select(LLMProfile).order_by(LLMProfile.created_at))).scalars().all()
    out: list[dict] = []
    for p in rows:
        for m in _parse_models(p.models):
            if m.get("enabled"):
                out.append({
                    "profile_id": str(p.id),
                    "profile_name": p.name,
                    "provider": p.provider,
                    "model": m["name"],
                    "is_default": bool(m.get("is_default")),
                })
    return {"models": out}
