"""业务系统推送凭证（AK/SK + HMAC 签名）验证逻辑单测。

覆盖：签名正/误、时间戳窗口、nonce 防重放、AK 无效/吊销、源停用、频控降级。
DB 层用 mock session（查询面小且简单），Redis 用真实 dev 实例（nonce 一次性）。
"""
import hashlib
import hmac
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.services.business_auth import verify_business_signature
from kb_common.crypto import encrypt_secret
from kb_common.models import BusinessCredential, KnowledgeSource


def _make_credential(**overrides) -> BusinessCredential:
    cred = BusinessCredential(
        source_id=1,
        access_key_id="bsk-" + "a" * 32,
        secret_cipher=encrypt_secret("test-secret"),
        library_ids=[3],
        status="active",
    )
    for k, v in overrides.items():
        setattr(cred, k, v)
    return cred


def _make_source(**overrides) -> KnowledgeSource:
    src = KnowledgeSource(name="测试业务系统", source_type="business_system",
                          external_id="bs-test", enabled=True)
    for k, v in overrides.items():
        setattr(src, k, v)
    return src


def _make_request(path: str, body: bytes = b"", method: "str" = "POST",
                  headers: dict | None = None) -> Request:
    scope = {
        "type": "http", "method": method, "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "query_string": b"",
        "url": {"path": path, "query": b""},
    }
    req = Request(scope)
    req._body = body  # noqa: SLF001 — 测试内注入原始字节
    return req


def _sign(secret: str, method: str, path: str, ts: str, nonce: str, body: bytes) -> str:
    payload = f"{method}\n{path}\n{ts}\n{nonce}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _headers(ak: str, secret: str, body: bytes, ts: int | None = None,
             nonce: str | None = None, path: str = "/api/v1/ingest/3/documents",
             method: str = "POST") -> dict:
    ts = str(ts if ts is not None else int(time.time()))
    nonce = nonce or hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:16]
    return {
        "X-AK-Id": ak,
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Signature": _sign(secret, method, path, ts, nonce, body),
    }


def _session(cred, source):
    session = AsyncMock()
    exec_result = Mock()
    exec_result.scalar_one_or_none = lambda: cred
    session.execute = AsyncMock(return_value=exec_result)
    session.get = AsyncMock(side_effect=lambda model, pk: source if model is KnowledgeSource else None)
    session.commit = AsyncMock()
    return session


BODY = b"--boundary\r\nContent-Disposition: form-data; name=\"file\"\r\n\r\nhello\r\n--boundary--\r\n"


async def test_valid_signature_passes():
    cred = _make_credential()
    src = _make_source()
    req = _make_request("/api/v1/ingest/3/documents", BODY, headers=_headers(cred.access_key_id, "test-secret", BODY))
    got = await verify_business_signature(req, _session(cred, src))
    assert got is cred


async def test_wrong_signature_rejected():
    cred = _make_credential()
    src = _make_source()
    headers = _headers(cred.access_key_id, "wrong-secret", BODY)
    req = _make_request("/api/v1/ingest/3/documents", BODY, headers=headers)
    with pytest.raises(HTTPException) as err:
        await verify_business_signature(req, _session(cred, src))
    assert err.value.status_code == 401


async def test_expired_timestamp_rejected():
    cred = _make_credential()
    src = _make_source()
    headers = _headers(cred.access_key_id, "test-secret", BODY, ts=int(time.time()) - 600)
    req = _make_request("/api/v1/ingest/3/documents", BODY, headers=headers)
    with pytest.raises(HTTPException) as err:
        await verify_business_signature(req, _session(cred, src))
    assert err.value.status_code == 401


async def test_nonce_replay_rejected():
    cred = _make_credential()
    src = _make_source()
    headers = _headers(cred.access_key_id, "test-secret", BODY)
    req = _make_request("/api/v1/ingest/3/documents", BODY, headers=headers)
    await verify_business_signature(req, _session(cred, src))
    with pytest.raises(HTTPException) as err:
        await verify_business_signature(req, _session(cred, src))
    assert err.value.status_code == 401


async def test_revoked_credential_rejected():
    cred = _make_credential(status="revoked")
    src = _make_source()
    req = _make_request("/api/v1/ingest/3/documents", BODY, headers=_headers(cred.access_key_id, "test-secret", BODY))
    with pytest.raises(HTTPException) as err:
        await verify_business_signature(req, _session(cred, src))
    assert err.value.status_code == 401


async def test_disabled_source_rejected():
    cred = _make_credential()
    src = _make_source(enabled=False)
    req = _make_request("/api/v1/ingest/3/documents", BODY, headers=_headers(cred.access_key_id, "test-secret", BODY))
    with pytest.raises(HTTPException) as err:
        await verify_business_signature(req, _session(cred, src))
    assert err.value.status_code == 403


async def test_missing_headers_rejected():
    req = _make_request("/api/v1/ingest/3/documents", BODY)
    with pytest.raises(HTTPException) as err:
        await verify_business_signature(req, _session(None, _make_source()))
    assert err.value.status_code == 401


async def test_body_tamper_rejected():
    """签名后篡改正文 → 摘要不匹配 → 401。"""
    cred = _make_credential()
    src = _make_source()
    headers = _headers(cred.access_key_id, "test-secret", BODY)
    req = _make_request("/api/v1/ingest/3/documents", BODY + b"tampered", headers=headers)
    with pytest.raises(HTTPException) as err:
        await verify_business_signature(req, _session(cred, src))
    assert err.value.status_code == 401


async def test_last_used_at_throttled_write():
    """last_used_at 1 分钟内已更新则不重复写库。"""
    cred = _make_credential(
        last_used_at=datetime.now(timezone.utc).replace(tzinfo=None))
    src = _make_source()
    session = _session(cred, src)
    req = _make_request("/api/v1/ingest/3/documents", BODY, headers=_headers(cred.access_key_id, "test-secret", BODY))
    await verify_business_signature(req, session)
    session.commit.assert_not_awaited()
