"""知识源登记（注册表）路由单测。

覆盖：编码自动生成/显式传入/唯一冲突、更新人记录、
内置「本地上传」渠道护栏（禁止手动创建/变更类型/删除）。
DB 层用 mock session（参照 test_business_ingest.py 风格）。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.routes import knowledge_center as kc
from app.schemas import KnowledgeSourceCreate, KnowledgeSourceUpdate
from kb_common.crypto import encrypt_secret
from kb_common.models import BusinessCredential, KnowledgeSource


def _user(username="alice"):
    return MagicMock(username=username)


def _session(get_result=None, commit_error=None):
    """async 方法用 AsyncMock，add 等同步方法保持 Mock 以便捕获入参。"""
    session = MagicMock()
    session.get = AsyncMock(return_value=get_result)
    session.commit = AsyncMock(side_effect=commit_error) if commit_error else AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


def _make_source(**overrides) -> KnowledgeSource:
    src = KnowledgeSource(name="测试业务系统", source_type="business_system",
                          external_id="bs-test", enabled=True, code="BS001", priority=99)
    for k, v in overrides.items():
        setattr(src, k, v)
    return src


def _added_source(session) -> KnowledgeSource:
    return session.add.call_args[0][0]


# ===== 创建 =====

async def test_create_auto_generates_code_and_records_updated_by():
    payload = KnowledgeSourceCreate(name="ERP", source_type="business_system",
                                    external_id="bs-erp")
    session = _session()
    source = await kc.create_knowledge_source(payload, u=_user(), s=session)
    added = _added_source(session)
    assert added.code.startswith("KD")
    assert added.updated_by == "alice"
    assert source is added


async def test_create_keeps_explicit_code():
    payload = KnowledgeSourceCreate(name="ERP", source_type="business_system",
                                    external_id="bs-erp", code="ERP-001")
    session = _session()
    await kc.create_knowledge_source(payload, u=_user(), s=session)
    assert _added_source(session).code == "ERP-001"


async def test_create_duplicate_code_raises_409():
    payload = KnowledgeSourceCreate(name="ERP", source_type="business_system",
                                    external_id="bs-erp", code="ERP-001")
    session = _session(commit_error=IntegrityError("stmt", {}, Exception("dup")))
    with pytest.raises(HTTPException) as exc:
        await kc.create_knowledge_source(payload, u=_user(), s=session)
    assert exc.value.status_code == 409


async def test_create_local_upload_rejected():
    payload = KnowledgeSourceCreate(name="本地上传", source_type="local_upload",
                                    external_id="local_upload")
    session = _session()
    with pytest.raises(HTTPException) as exc:
        await kc.create_knowledge_source(payload, u=_user(), s=session)
    assert exc.value.status_code == 422
    session.add.assert_not_called()


# ===== 更新 =====

async def test_update_records_updated_by_and_priority():
    source = _make_source()
    session = _session(get_result=source)
    await kc.update_knowledge_source(
        1, KnowledgeSourceUpdate(priority=1), u=_user("bob"), s=session)
    assert source.priority == 1
    assert source.updated_by == "bob"


async def test_update_empty_code_keeps_original():
    source = _make_source(code="ERP-001")
    session = _session(get_result=source)
    await kc.update_knowledge_source(
        1, KnowledgeSourceUpdate(code=""), u=_user(), s=session)
    assert source.code == "ERP-001"


@pytest.mark.parametrize("origin,target", [
    ("local_upload", "business_system"),
    ("business_system", "local_upload"),
])
async def test_update_local_upload_type_change_forbidden(origin, target):
    source = _make_source(source_type=origin, external_id="x")
    session = _session(get_result=source)
    with pytest.raises(HTTPException) as exc:
        await kc.update_knowledge_source(
            1, KnowledgeSourceUpdate(source_type=target), u=_user(), s=session)
    assert exc.value.status_code == 422


# ===== 删除 =====

async def test_delete_local_upload_forbidden():
    source = _make_source(source_type="local_upload", external_id="local_upload")
    session = _session(get_result=source)
    with pytest.raises(HTTPException) as exc:
        await kc.delete_knowledge_source(1, u=_user(), s=session)
    assert exc.value.status_code == 409
    session.delete.assert_not_awaited()


async def test_delete_normal_source_ok():
    source = _make_source()
    session = _session(get_result=source)
    result = await kc.delete_knowledge_source(1, u=_user(), s=session)
    assert result == {"ok": True}
    session.delete.assert_awaited_once_with(source)


# ===== SecretKey 按需查看（管理员 reveal）=====

def _make_credential(**overrides) -> BusinessCredential:
    cred = BusinessCredential(
        source_id=1, access_key_id="bsk-" + "a" * 32,
        secret_cipher=encrypt_secret("sk-plain-text"),
        library_ids=[3], status="active",
    )
    for k, v in overrides.items():
        setattr(cred, k, v)
    return cred


def _cred_session(cred, source=None):
    session = _session(get_result=source or _make_source())
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = lambda: cred
    session.execute = AsyncMock(return_value=exec_result)
    return session


async def test_reveal_secret_decrypts():
    out = await kc.reveal_credential_secret(1, u=_user(), s=_cred_session(_make_credential()))
    assert out == {"secret_key": "sk-plain-text"}


async def test_reveal_revoked_rejected():
    with pytest.raises(HTTPException) as exc:
        await kc.reveal_credential_secret(
            1, u=_user(), s=_cred_session(_make_credential(status="revoked")))
    assert exc.value.status_code == 409


async def test_reveal_missing_credential_404():
    with pytest.raises(HTTPException) as exc:
        await kc.reveal_credential_secret(1, u=_user(), s=_cred_session(None))
    assert exc.value.status_code == 404
