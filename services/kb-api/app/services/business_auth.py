"""业务系统推送接口的 AK/SK + HMAC 请求签名验证。

签名规范（与前端「接入说明」一致）：
- 请求头：X-AK-Id、X-Timestamp（Unix 秒）、X-Nonce（16-64 位随机 hex）、X-Signature（hex 小写）
- 签名串："{METHOD}\\n{PATH}\\n{timestamp}\\n{nonce}\\n{sha256_hex(raw_body)}"
  METHOD 大写；PATH 为 URL path（含 query 时为 "path?raw_query"）；空 body 取空串的 sha256
- 签名：HMAC-SHA256(SecretKey, 签名串) 的 hex
- 防重放：时间窗 ±300s + nonce 一次性（Redis SETNX，TTL 覆盖时间窗）
- 频控：Redis 分钟级计数，默认 60 次/分钟
SecretKey 本身永不在线上传输，抓包也无法获得。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.crypto import decrypt_secret
from kb_common.database import get_session
from kb_common.models import BusinessCredential, KnowledgeSource
from kb_common.redis_client import get_redis

logger = logging.getLogger(__name__)

_TIMESTAMP_WINDOW = 300  # 秒
_NONCE_TTL = 600
_RATE_LIMIT = 60  # 次/分钟
_NONCE_RE = re.compile(r"^[0-9a-fA-F]{16,64}$")


def _signature_payload(method: str, path_with_query: str, timestamp: str, nonce: str,
                       body: bytes) -> str:
    body_hash = hashlib.sha256(body or b"").hexdigest()
    return f"{method.upper()}\n{path_with_query}\n{timestamp}\n{nonce}\n{body_hash}"


async def verify_business_signature(
    request: Request,
    s: AsyncSession = Depends(get_session),
) -> BusinessCredential:
    """FastAPI 依赖：验证业务系统推送请求签名，返回凭证（供端点做库授权校验）。

    必须以 Depends 挂在端点上（而非函数体内手工调用）：依赖阶段先读 raw body
    并缓存（request.body()），随后 FastAPI 才解析 File/Form（走缓存的 stream）；
    反过来则 multipart 解析消费 stream 后 body() 会抛 "Stream consumed"。
    """
    ak = (request.headers.get("X-AK-Id") or "").strip()
    timestamp = (request.headers.get("X-Timestamp") or "").strip()
    nonce = (request.headers.get("X-Nonce") or "").strip()
    signature = (request.headers.get("X-Signature") or "").strip().lower()
    if not ak or not timestamp or not nonce or not signature:
        raise HTTPException(401, "缺少签名认证头（X-AK-Id / X-Timestamp / X-Nonce / X-Signature）")

    # 时间窗校验（先于查库，拒绝廉价重放）
    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(401, "X-Timestamp 必须为 Unix 秒") from None
    if abs(time.time() - ts) > _TIMESTAMP_WINDOW:
        raise HTTPException(401, "请求时间戳超出允许窗口（±5 分钟），请校准时钟后重试")
    if not _NONCE_RE.fullmatch(nonce):
        raise HTTPException(401, "X-Nonce 须为 16-64 位随机 hex")

    # 凭证查询
    cred = (await s.execute(select(BusinessCredential).where(
        BusinessCredential.access_key_id == ak))).scalar_one_or_none()
    if cred is None or cred.status != "active":
        raise HTTPException(401, "无效的 AccessKeyId 或凭证已失效")
    source = await s.get(KnowledgeSource, cred.source_id)
    if source is None or not source.enabled:
        raise HTTPException(403, "所属业务系统已停用，推送被拒绝")

    # 验签（常数时间比较）；正文优先读中间件预缓存的原始字节
    # （multipart 场景 FastAPI 先消费 stream，直接 request.body() 会抛 Stream consumed）
    body = request.scope.get("_cached_body")
    if body is None:
        body = await request.body()
    path_with_query = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    expected = hmac.new(
        decrypt_secret(cred.secret_cipher).encode("utf-8"),
        _signature_payload(request.method, path_with_query, timestamp, nonce, body).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "签名校验失败")

    # 防重放：nonce 一次性占用
    try:
        redis = get_redis()
        if not await redis.set(f"bsign:{ak}:{nonce}", "1", nx=True, ex=_NONCE_TTL):
            raise HTTPException(401, "重复的请求 nonce（疑似重放）")
        # 频控：分钟窗口计数
        minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        count = await redis.incr(f"bsrq:{ak}:{minute}")
        if count == 1:
            await redis.expire(f"bsrq:{ak}:{minute}", 60)
        if count > _RATE_LIMIT:
            raise HTTPException(429, "请求过于频繁，请稍后重试")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — Redis 不可用时降级为只做签名+时间窗
        logger.warning("business signature redis unavailable, degrade to signature-only: %r", exc)

    # last_used_at 节流写入（1 分钟内不重复写库）
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if cred.last_used_at is None or (now - cred.last_used_at).total_seconds() > 60:
        cred.last_used_at = now
        await s.commit()
    return cred
