"""Read-only, bounded DWS enterprise search. No shell, writes or implicit identity sharing."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from kb_common.config import get_settings

from .evidence import safe_url

_SEM = asyncio.Semaphore(3)
MAX_OUTPUT = 4 * 1024 * 1024


class DWSError(RuntimeError):
    pass


async def run_dws(args: list[str], profile: str = "") -> dict:
    binary = os.getenv("DWS_BIN") or get_settings().dws_bin or shutil.which("dws")
    if not binary:
        raise DWSError("DWS 未安装，请配置 DWS_BIN")
    command = [binary, *args, "--format", "json"]
    if profile:
        command += ["--profile", profile]
    async with _SEM:
        proc = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        async def read_output():
            chunks, size = [], 0
            while chunk := await proc.stdout.read(65536):
                size += len(chunk)
                if size > MAX_OUTPUT:
                    raise DWSError("DWS 响应超过读取上限")
                chunks.append(chunk)
            await proc.wait()
            return b"".join(chunks)
        try:
            raw = await asyncio.wait_for(read_output(), timeout=35)
        finally:
            # Also reap on disconnect/cancellation and output overflow.
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise DWSError("DWS 返回格式异常") from exc
        if not isinstance(data, dict) or proc.returncode or data.get("success") is False or data.get("error") or data.get("errorCode"):
            raise DWSError("DWS 认证、权限或服务异常，请检查当前账号")
        return data


async def profile_for(user_id: str, role: str) -> str:
    # A web login is not a DingTalk identity. Only an explicit mapping allows staff access.
    try:
        mapping = json.loads(os.getenv("QA_DWS_USER_PROFILES", get_settings().qa_dws_user_profiles))
    except ValueError as exc:
        raise DWSError("QA_DWS_USER_PROFILES 配置格式异常") from exc
    selected = mapping.get(user_id) if isinstance(mapping, dict) else None
    if selected and isinstance(selected, str):
        return selected
    if role != "super_admin":
        raise DWSError("当前用户尚未绑定钉钉检索身份")
    data = await run_dws(["profile", "list"])
    current = data.get("currentProfile")
    matches = [p for p in data.get("profiles", [])
               if p.get("profile") == current and p.get("isOrgCurrent") is True]
    if len(matches) != 1:
        raise DWSError("DWS 未明确当前组织账号，请配置用户身份映射")
    return matches[0]["profile"]


def parse_search(data: dict, top_k: int) -> list[dict]:
    # This contract was verified against dws aisearch enterprise, not guessed recursively.
    rows = data.get("result")
    if not isinstance(rows, list):
        raise DWSError("DWS 缺少检索结果数组，不能视为零命中")
    results = []
    for row in rows:
        if not isinstance(row, dict) or row.get("sourceType") != "document":
            continue
        meta = row.get("meta") or {}
        node = row.get("nodeId") or meta.get("nodeId")
        content = row.get("snippet") or ""
        if not node or not isinstance(content, str) or not content.strip():
            continue
        encoded = "¥ENCoDETaBlE¥" in content
        content = re.sub(r"¥ENCoDETaBlE¥:\([^)]*\)", "【表格编码不可读，此处不能作为事实依据】", content)
        results.append({
            "document_id": node, "node_id": node,
            "document_title": row.get("title") or "钉钉文档",
            "content": content, "source": "dws", "score": 0,
            "url": safe_url(row.get("url") or ""),
            "extension": meta.get("doc_type") or "", "partial": True,
            "encoded_tables": encoded,
        })
        if len(results) >= top_k:
            break
    return results


async def search(query: str, *, profile: str, top_k: int = 6, time_range: str = "") -> list[dict]:
    if not query.strip() or not profile:
        return []
    args = ["aisearch", "enterprise", "--queries", query[:500], "--types", "document"]
    if time_range:
        args += ["--time-range", time_range]
    return parse_search(await run_dws(args, profile), top_k)


async def fetch_online(hit: dict, profile: str) -> dict:
    """Only adoc supports doc +fetch. Search excerpts of office files remain explicitly partial."""
    if hit.get("extension") != "adoc":
        return hit
    data = await run_dws(["doc", "+fetch", "--node", hit["node_id"]], profile)
    # Verified doc.fetch contract: content holds the raw document result.
    payload = data.get("content")
    if data.get("status") != "success" or not isinstance(payload, dict) or payload.get("success") is not True:
        raise DWSError("钉钉在线文档未返回有效正文")
    if payload.get("nodeId") != hit["node_id"]:
        raise DWSError("钉钉返回的文档身份与请求不一致")
    content = payload.get("markdown")
    if not isinstance(content, str) or not content.strip():
        raise DWSError("钉钉在线文档正文为空")
    return {**hit, "content": content, "partial": data.get("complete") is not True}
