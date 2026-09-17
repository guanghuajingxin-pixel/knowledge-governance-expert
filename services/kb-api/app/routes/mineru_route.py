"""MinerU 解析引擎测试台 · 同源透传代理。

浏览器直连 MinerU（如 http://127.0.0.1:8010）会被 CORS 拦截——MinerU 服务不返回
Access-Control-Allow-Origin 头，官方 WebUI 可用是因为它与 API 同源部署。本路由在
kb-api 上提供同源转发，前端（/process/engine 自定义解析页签）通过
X-Mineru-Base 头指定目标 MinerU 服务地址，方法 / 查询串 / 请求体原样透传。

仅面向管理员的测试台能力，需 JWT（require_role super_admin/admin）。
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.deps import require_role

router = APIRouter(prefix="/api/v1/mineru", tags=["mineru"])

DEFAULT_BASE = "http://127.0.0.1:8010"
# 上传大文件 / 解析结果下载给足余量；建任务本身是异步的、秒级返回
FORWARD_TIMEOUT = httpx.Timeout(300.0, connect=10.0)

# 不透传的请求头（hop-by-hop / 会干扰转发的头）
HOP_HEADERS = {"host", "content-length", "connection", "authorization", "x-mineru-base", "accept-encoding"}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request, _u=Depends(require_role("super_admin", "admin"))) -> Response:
    base = (request.headers.get("x-mineru-base") or DEFAULT_BASE).strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise HTTPException(400, f"MinerU 服务地址无效：{base}（需以 http:// 或 https:// 开头）")

    url = f"{base}/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    fwd_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS
    }
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=FORWARD_TIMEOUT, follow_redirects=False) as client:
            resp = await client.request(request.method, url, headers=fwd_headers, content=body)
    except httpx.ConnectError as e:
        raise HTTPException(502, f"无法连接 MinerU 服务（{base}）：{e.__class__.__name__}，请确认服务已启动") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"请求 MinerU 服务失败：{e.__class__.__name__}: {e}") from e

    resp_headers = {
        k: v for k, v in resp.headers.items()
        if k.lower() not in ("content-length", "transfer-encoding", "connection", "content-encoding")
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type"),
    )
