"""共享 Redis 异步客户端（懒加载单例）。

供签名防重放（nonce 去重）与接口频控使用；不可用时调用方自行降级处理。
"""
from __future__ import annotations

import redis.asyncio as aioredis

from kb_common.config import get_settings

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
