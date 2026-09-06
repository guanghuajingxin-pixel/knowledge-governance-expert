"""钉钉开放平台客户端：企业知识库（Wiki）、通讯录、AI 表格（多维表）。

服务运营看板 / 知识中心 / 治理标准三个模块：

1. 知识库（Wiki）
   - accessToken：POST https://api.dingtalk.com/v1.0/oauth2/accessToken
   - 知识库列表：GET  https://api.dingtalk.com/v2.0/wiki/workspaces
   - 节点列表：  GET  https://api.dingtalk.com/v2.0/wiki/nodes
   - 企业存储总量：GET https://api.dingtalk.com/v1.0/storage/orgs/{corpId}
     （需「企业存储企业读权限 Storage.Org.Read」，与钉钉后台存储口径一致）
   - get_all_knowledge_files() 深度并发遍历所有团队知识库，返回文件平铺列表。

2. 通讯录
   - userid → 姓名：POST https://oapi.dingtalk.com/topapi/v2/user/get（带缓存）。

3. AI 表格（多维表，notable）
   - 列出记录：POST https://api.dingtalk.com/v1.0/notable/bases/{baseId}/sheets/{sheetId}/records/list
     （需「AI 表格应用读权限」）。

配置读取顺序：显式注入 / DB settings 表（sync_runtime_config）> .env（get_settings）。
操作人需具备目标知识库读权限，operatorId 为该用户的 unionId。
"""
import asyncio
import logging
import random
import time
from typing import Any

import httpx
from kb_common.config import get_settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.dingtalk.com"
OAPI_BASE = "https://oapi.dingtalk.com"

# 并发与限流：钉钉标准版有调用频次限制，过高并发会触发 403/overlimit。
# 全量遍历信号量（限制同时在飞的 wiki/nodes 请求数）
_WALK_CONCURRENCY = 3
# 单次请求失败（限流/超时）时的退避重试
_MAX_RETRY = 5
_RETRY_BASE_DELAY = 1.0
# 全局请求节流：wiki/nodes 限流严格（实测串行 2 QPS 稳定、3 并发即批量 403），
# 所有 wiki 请求之间至少间隔该秒数（令牌桶的最小发包间隔）。
_RL_MIN_INTERVAL = 0.4
_rl_lock = asyncio.Lock()
_rl_next_at = 0.0


async def _throttle() -> None:
    """全局最小请求间隔节流（跨所有协程），保证 wiki 类接口 QPS 不超限。"""
    global _rl_next_at
    async with _rl_lock:
        now = time.monotonic()
        wait = _rl_next_at - now
        if wait > 0:
            await asyncio.sleep(wait)
        _rl_next_at = time.monotonic() + _RL_MIN_INTERVAL

# =====《杰克知识管理规范》AI 多维表坐标 =====
# baseId / sheetId 来自该多维表 URL；如需更换规范表，可通过 .env 的
# DINGTALK_STANDARDS_BASE_ID / DINGTALK_STANDARDS_SHEET_ID 覆盖，或改此处常量。
STANDARDS_BASE_ID = ""
STANDARDS_SHEET_ID = ""

# 运行时注入的配置（来自 DB settings 表，优先级高于 .env）
_injected: dict[str, str] = {}
_token_cache: dict[str, Any] = {"token": "", "expire_at": 0.0}
_corp_id_cache: dict[str, Any] = {"corp_id": "", "expire_at": 0.0}
_name_cache: dict[str, str] = {}
# 最近一次全量遍历的请求统计（requests=成功的节点请求数，failed_folders=重试耗尽仍失败的目录数）
_walk_info: dict[str, int] = {"requests": 0, "failed_folders": 0}


# ===================== 配置 =====================
def configure(app_key: str = "", app_secret: str = "", operator_union_id: str = "") -> None:
    """注入钉钉配置（来自 DB settings 表，覆盖 .env）。空值不覆盖。"""
    if app_key:
        _injected["dingtalk_app_key"] = app_key
    if app_secret:
        _injected["dingtalk_app_secret"] = app_secret
    if operator_union_id:
        _injected["dingtalk_operator_union_id"] = operator_union_id


async def sync_runtime_config() -> None:
    """从 DB settings 表读取钉钉配置并即时生效（供知识中心/治理标准调用）。"""
    global STANDARDS_BASE_ID, STANDARDS_SHEET_ID
    from sqlalchemy import select
    from kb_common.database import SessionLocal
    from kb_common.models import Setting

    keys = ["dingtalk_app_key", "dingtalk_app_secret", "dingtalk_operator_union_id"]
    vals: dict[str, str] = {}
    async with SessionLocal() as s:
        for k in keys:
            row = (await s.execute(select(Setting).where(Setting.key == k))).scalar_one_or_none()
            vals[k] = row.value if row and row.value else ""
    configure(vals["dingtalk_app_key"], vals["dingtalk_app_secret"], vals["dingtalk_operator_union_id"])

    import os
    STANDARDS_BASE_ID = os.getenv("DINGTALK_STANDARDS_BASE_ID", STANDARDS_BASE_ID)
    STANDARDS_SHEET_ID = os.getenv("DINGTALK_STANDARDS_SHEET_ID", STANDARDS_SHEET_ID)


def _cfg(key: str) -> str:
    return _injected.get(key) or getattr(get_settings(), key, "") or ""


def _app_key() -> str:
    return _cfg("dingtalk_app_key")


def _app_secret() -> str:
    return _cfg("dingtalk_app_secret")


def _operator_id() -> str:
    return _cfg("dingtalk_operator_union_id")


def is_configured() -> bool:
    return bool(_app_key() and _app_secret() and _operator_id())


# ===================== accessToken =====================
async def _get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expire_at"] > now + 300:
        return _token_cache["token"]
    key, secret = _app_key(), _app_secret()
    if not key or not secret:
        raise RuntimeError("钉钉 AppKey/AppSecret 未配置")
    url = f"{API_BASE}/v1.0/oauth2/accessToken"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, json={"appKey": key, "appSecret": secret})
        resp.raise_for_status()
        data = resp.json()
    token = data.get("accessToken") or data.get("access_token")
    if not token:
        raise RuntimeError(f"获取钉钉 accessToken 失败：{data}")
    _token_cache["token"] = token
    _token_cache["expire_at"] = now + data.get("expireIn", 7200)
    return token


def _headers(token: str) -> dict[str, str]:
    return {"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"}


async def _request_with_retry(method: str, url: str, *, client: httpx.AsyncClient,
                              **kwargs) -> httpx.Response:
    """带限流退避重试的 HTTP 请求。

    对限流（403/429）、服务端错误（5xx）、超时做指数退避重试；
    对明确的权限不足（permissionDenied/no.priviledge，body 可辨）不重试。
    """
    last_exc: Exception | None = None
    resp: httpx.Response | None = None
    for attempt in range(_MAX_RETRY):
        try:
            resp = await client.request(method, url, **kwargs)
            # 限流 / 服务端错误 → 退避重试
            if resp.status_code in (403, 429) or resp.status_code >= 500:
                body_low = (resp.text or "").lower()
                # 明确权限不足不重试（body 含 permissionDenied / requiredScopes / 尚未开通 等）
                perm_markers = ("permissiondenied", "requiredscopes", "no.priviledge",
                                "尚未开通", "accessdenieddetail")
                if resp.status_code == 403 and any(m in body_low for m in perm_markers):
                    resp.raise_for_status()
                delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning("钉钉请求被限流/错误 %s，%.1fs 后重试(%d/%d): %s",
                               resp.status_code, delay, attempt + 1, _MAX_RETRY, url)
                await asyncio.sleep(delay)
                continue
            return resp
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e
            delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc
    # 重试用尽，返回最后一次响应交由上层处理
    return resp  # type: ignore[return-value]


# ===================== 知识库 =====================
async def list_workspaces() -> list[dict[str, Any]]:
    """获取操作人可见的知识库列表，自动分页。"""
    operator = _operator_id()
    if not operator:
        raise RuntimeError("钉钉操作人 UnionId 未配置")
    token = await _get_access_token()
    url = f"{API_BASE}/v2.0/wiki/workspaces"
    params = {"operatorId": operator, "maxResults": 30}
    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            await _throttle()
            resp = await _request_with_retry("GET", url, client=client, params=params, headers=_headers(token))
            resp.raise_for_status()
            data = resp.json()
            out.extend(data.get("workspaces") or [])
            nxt = data.get("nextToken")
            if not nxt:
                break
            params["nextToken"] = nxt
    return out


async def list_nodes(parent_node_id: str) -> list[dict[str, Any]]:
    """获取某父节点下的直接子节点，自动分页。"""
    operator = _operator_id()
    token = await _get_access_token()
    url = f"{API_BASE}/v2.0/wiki/nodes"
    params = {"parentNodeId": parent_node_id, "operatorId": operator, "maxResults": 50}
    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            await _throttle()
            resp = await _request_with_retry("GET", url, client=client,
                                             params=params, headers=_headers(token))
            resp.raise_for_status()
            data = resp.json()
            out.extend(data.get("nodes") or [])
            nxt = data.get("nextToken")
            if not nxt:
                break
            params["nextToken"] = nxt
    return out


async def _walk_workspace_files(workspace: dict, sem: asyncio.Semaphore) -> list[dict]:
    """并发深度遍历一个知识库，返回文件平铺列表（含目录路径、创建人等）。"""
    ws_name = workspace.get("name", "")
    ws_id = workspace.get("workspaceId")
    root_id = workspace.get("rootNodeId")
    files: list[dict] = []
    if not root_id:
        return files

    async def walk(node_id: str, dir_path: str) -> None:
        async with sem:
            try:
                nodes = await list_nodes(node_id)
                _walk_info["requests"] += 1
            except Exception as e:
                _walk_info["failed_folders"] += 1
                logger.warning("钉钉获取节点失败 %s/%s: %s（该目录下文件将缺失）", ws_name, node_id, e)
                nodes = []
        child_folders = []
        for n in nodes:
            name = n.get("name", "")
            if n.get("type") == "FOLDER":
                if n.get("hasChildren"):
                    child_folders.append((n.get("nodeId"), f"{dir_path}/{name}"))
            else:
                files.append({
                    "node_id": n.get("nodeId"),
                    "workspace_id": n.get("workspaceId") or ws_id,
                    "workspace_name": ws_name,
                    "name": name,
                    "directory_path": dir_path or "/",
                    "category": n.get("category"),
                    "extension": n.get("extension"),
                    "size": int(n.get("size") or 0),
                    "url": n.get("url"),
                    "creator_id": n.get("creatorId") or "",
                    "created_at": n.get("createTime"),
                    "modified_at": n.get("modifiedTime"),
                })
        if child_folders:
            await asyncio.gather(*[walk(fid, fpath) for fid, fpath in child_folders])

    await walk(root_id, "")
    return files


async def get_all_knowledge_files() -> list[dict]:
    """并发遍历全部团队知识库，返回所有文件的平铺列表。"""
    workspaces = await list_workspaces()
    teams = [w for w in workspaces if w.get("type") != "PERSONAL"]
    _walk_info["requests"] = 0
    _walk_info["failed_folders"] = 0
    sem = asyncio.Semaphore(_WALK_CONCURRENCY)
    results = await asyncio.gather(
        *[_walk_workspace_files(w, sem) for w in teams],
        return_exceptions=True,
    )
    out: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning("遍历知识库失败: %s", r)
        else:
            out.extend(r)
    logger.info("钉钉知识库遍历完成：%d 个库、%d 个文件、节点请求 %d 次、失败目录 %d 个",
                len(teams), len(out), _walk_info["requests"], _walk_info["failed_folders"])
    return out


def get_last_walk_info() -> dict[str, int]:
    """最近一次全量遍历的请求统计（供运营看板判断数据是否完整）。"""
    return dict(_walk_info)


# ===================== 企业存储 / 运营统计 =====================
async def get_corp_id() -> str:
    now = time.time()
    if _corp_id_cache["corp_id"] and _corp_id_cache["expire_at"] > now:
        return _corp_id_cache["corp_id"]
    wss = await list_workspaces()
    corp_id = next((w.get("corpId") for w in wss if w.get("corpId")), "")
    if not corp_id:
        raise RuntimeError("未能从知识库列表中获取企业 corpId")
    _corp_id_cache["corp_id"] = corp_id
    _corp_id_cache["expire_at"] = now + 3600
    return corp_id


async def _get_org_storage_used_api() -> int:
    """企业存储 API 直连（需应用开通 Storage.Org.Read），权限不足抛 RuntimeError。"""
    corp_id = await get_corp_id()
    token = await _get_access_token()
    url = f"{API_BASE}/v1.0/storage/orgs/{corp_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await _request_with_retry(
                "GET", url, client=client,
                params={"unionId": _operator_id()}, headers=_headers(token))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                raise RuntimeError(
                    "缺少「企业存储企业读权限(Storage.Org.Read)」，请在钉钉开放平台为应用开通该权限后重试"
                ) from e
            raise
        data = resp.json()
    used = 0
    for p in (data.get("org") or {}).get("partitions") or []:
        used += int((p.get("quota") or {}).get("used") or 0)
    return used


# ===== 钉钉官方 CLI（dws）兜底：用户 OAuth 授权线，不依赖应用权限 =====
_CLI_QUOTA_TTL = 600
_cli_quota_cache: dict[str, Any] = {"used": 0, "apps": 0, "expire_at": 0.0}


def _dws_bin() -> str:
    """钉钉 CLI 路径：优先环境变量 DWS_BIN，否则项目根 tools/dws/dws。"""
    import os
    from pathlib import Path
    custom = os.getenv("DWS_BIN")
    if custom:
        return custom
    # dingtalk_client.py → clients → kb_common → kb-common → services → 项目根
    return str(Path(__file__).resolve().parents[4] / "tools" / "dws" / "dws")


async def get_org_storage_used_via_cli() -> int:
    """通过钉钉官方 CLI（dws drive quota apps）读取企业存储用量汇总（字节）。

    走 dws auth login 扫码的用户 OAuth 授权，与企业的 appKey/AppSecret 权限线
    相互独立，可在应用未开通 Storage.Org.Read 时获取与钉钉后台一致的总量
    （钉盘/在线文档/会议/AI 听记等全应用用量之和）。结果缓存 10 分钟。
    CLI 未安装/未扫码/调用失败时抛 RuntimeError。
    """
    import json as _json
    from pathlib import Path
    now = time.time()
    if _cli_quota_cache["expire_at"] > now:
        return _cli_quota_cache["used"]
    dws = _dws_bin()
    if not Path(dws).is_file():
        raise RuntimeError(f"钉钉 CLI 不存在：{dws}（先完成 dws auth login 扫码授权）")
    total = 0
    app_count = 0
    cursor: str | None = None
    for _ in range(20):  # 分页保护，最多 20 页
        args = [dws, "drive", "quota", "apps", "-f", "json", "--limit", "50"]
        if cursor:
            args += ["--cursor", cursor]
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("dws drive quota apps 调用超时")
        if proc.returncode != 0:
            raise RuntimeError(
                f"dws 调用失败(exit={proc.returncode})：{(err or b'').decode(errors='ignore')[:200]}")
        try:
            data = _json.loads(out.decode() or "{}")
        except _json.JSONDecodeError as e:
            raise RuntimeError(f"dws 返回非 JSON：{out.decode(errors='ignore')[:200]}") from e
        for app in data.get("apps") or []:
            total += int(app.get("used") or 0)
            app_count += 1
        cursor = data.get("nextToken")
        if not cursor:
            break
    _cli_quota_cache["used"] = total
    _cli_quota_cache["apps"] = app_count
    _cli_quota_cache["expire_at"] = now + _CLI_QUOTA_TTL
    logger.info("钉钉 CLI 企业存储用量：%d 字节（%d 个应用）", total, app_count)
    return total


async def get_org_storage_used() -> int:
    """企业存储已用容量（字节），与钉钉知识后台口径一致。

    优先企业存储 API（需 Storage.Org.Read 权限）；权限不足或调用失败时
    自动降级为钉钉 CLI（用户扫码授权，dws drive quota apps 汇总）。
    """
    try:
        return await _get_org_storage_used_api()
    except RuntimeError as api_err:
        try:
            return await get_org_storage_used_via_cli()
        except Exception as cli_err:
            raise RuntimeError(f"{api_err}；CLI 兜底也失败：{cli_err}") from cli_err


async def get_node_stats_via_cli(node_id: str) -> dict[str, int]:
    """通过钉钉 CLI（dws drive stats）读取单个节点的阅读/访问/编辑/评论统计。

    返回 {read_count, visit_count, edit_count, comment_count}；调用失败抛 RuntimeError。
    """
    import json as _json
    dws = _dws_bin()
    proc = await asyncio.create_subprocess_exec(
        dws, "drive", "stats", "--node", str(node_id), "-f", "json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("dws drive stats 调用超时")
    if proc.returncode != 0:
        raise RuntimeError((err or b"").decode(errors="ignore")[:200] or f"dws exit={proc.returncode}")
    try:
        data = _json.loads(out.decode() or "{}")
    except _json.JSONDecodeError as e:
        raise RuntimeError("dws 返回非 JSON") from e
    if data.get("success") is False or data.get("error"):
        raise RuntimeError(str(data.get("error") or data.get("message") or data)[:200])
    return {
        "read_count": int(data.get("readCount") or 0),
        "visit_count": int(data.get("visitCount") or 0),
        "edit_count": int(data.get("editCount") or 0),
        "comment_count": int(data.get("commentCount") or 0),
    }


async def get_all_workspaces_stats() -> list[dict]:
    """按知识库聚合统计（文件数 / 总大小 / 文件明细），供运营看板使用。"""
    files = await get_all_knowledge_files()
    stats: dict[str, dict] = {}
    for f in files:
        wid = f.get("workspace_id")
        bucket = stats.setdefault(wid, {
            "workspace_id": wid,
            "name": f.get("workspace_name", "未命名"),
            "file_count": 0,
            "folder_count": 0,
            "total_size": 0,
            "files": [],
        })
        bucket["file_count"] += 1
        bucket["total_size"] += f.get("size", 0)
        bucket["files"].append({
            "name": f.get("name", ""),
            "size": f.get("size", 0),
            "node_id": f.get("node_id"),
            "url": f.get("url"),
            "category": f.get("category"),
            "extension": f.get("extension"),
            "modified_time": f.get("modified_at"),
        })
    return list(stats.values())


# ===================== 通讯录 =====================
async def _fetch_user_name(userid: str, token: str) -> str:
    url = f"{OAPI_BASE}/topapi/v2/user/get?access_token={token}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json={"userid": userid})
        data = resp.json()
    if data.get("errcode") == 0:
        return (data.get("result") or {}).get("name") or ""
    return ""


async def get_user_name_map(user_ids: list[str]) -> dict[str, str]:
    """批量解析 userid → 姓名（带缓存，并发拉取缺失项）。"""
    missing = [u for u in dict.fromkeys(user_ids) if u and u not in _name_cache]
    if missing:
        token = await _get_access_token()
        sem = asyncio.Semaphore(_WALK_CONCURRENCY)

        async def _one(uid: str) -> None:
            async with sem:
                try:
                    _name_cache[uid] = await _fetch_user_name(uid, token) or uid
                except Exception:
                    _name_cache[uid] = uid

        await asyncio.gather(*[_one(u) for u in missing])
    return {u: _name_cache.get(u, u) for u in user_ids if u}


# ===================== AI 表格（多维表） =====================
async def list_aitable_records(base_id: str, sheet_id: str) -> list[dict]:
    """读取 AI 表格（多维表）指定数据表的全部记录，自动分页。

    返回 [{id, fields: {字段名: 值, ...}}, ...]。需「AI 表格应用读权限」。
    """
    if not base_id or not sheet_id:
        raise RuntimeError("规范表 baseId/sheetId 未配置（STANDARDS_BASE_ID / STANDARDS_SHEET_ID）")
    operator = _operator_id()
    token = await _get_access_token()
    url = f"{API_BASE}/v1.0/notable/bases/{base_id}/sheets/{sheet_id}/records/list"
    params = {"operatorId": operator}
    body: dict[str, Any] = {"maxResults": 100}
    records: list[dict] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            resp = await _request_with_retry("POST", url, client=client,
                                             params=params, json=body, headers=_headers(token))
            resp.raise_for_status()
            data = resp.json()
            records.extend(data.get("records") or [])
            if not data.get("hasMore"):
                break
            body["nextToken"] = data.get("nextToken")
    return records
