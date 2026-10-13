import asyncio
import time
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException
from jose import jwt, jwk

from kb_common import oidc
from kb_common.models import User, UserIdentity
from app.deps import get_current_user, get_principal
from app.routes import auth


class OidcTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = SimpleNamespace(auth_provider='keycloak', oidc_issuer='https://sso.test/realms/jack',
            oidc_jwks_url='', oidc_audience='kb-api', oidc_portal_client_id='jack-portal', oidc_web_client_id='knowledge-web',
            dev_auth_token='', dev_auth_user='admin')
        self.settings = patch.object(oidc, 'get_settings', return_value=self.cfg)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.pem = self.private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        public = self.private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.key = jwk.construct(public, algorithm='RS256').to_dict()
        self.key.update(kid='test-key', alg='RS256', use='sig')
        self.url = self.cfg.oidc_issuer + '/protocol/openid-connect/certs'
        oidc._keys[self.url] = (time.monotonic(), [self.key])
        self.addCleanup(oidc._keys.clear)
        self.claims = dict(iss=self.cfg.oidc_issuer, aud='kb-api', azp='jack-portal', sub=str(uuid4()),
            typ='Bearer', iat=int(time.time()), exp=int(time.time()) + 120, preferred_username='test',
            resource_access={'kb-api': {'roles': ['viewer']}})

    def token(self, **changes):
        return jwt.encode({**self.claims, **changes}, self.pem, algorithm='RS256', headers={'kid': 'test-key'})

    async def test_both_clients_validate_and_map_exact_audience_role(self):
        for client in ('jack-portal', 'knowledge-web'):
            claims = await oidc.verify_access_token(self.token(azp=client))
            self.assertEqual(oidc.role_from_claims(claims), 'viewer')

    async def test_rejects_wrong_issuer_audience_client_expiration_and_id_token(self):
        for changes in ({'iss': 'https://attacker/realms/jack'}, {'aud': 'other'}, {'azp': 'other'}, {'exp': 1}, {'typ': 'ID'}):
            with self.subTest(changes=changes), self.assertRaises(HTTPException) as error:
                await oidc.verify_access_token(self.token(**changes))
            self.assertEqual(error.exception.status_code, 401)

    async def test_local_token_cannot_bypass_sso(self):
        local = jwt.encode(self.claims, 'local-secret', algorithm='HS256')
        with self.assertRaises(HTTPException):
            await oidc.verify_access_token(local)

    async def test_machine_client_is_only_accepted_with_explicit_binding(self):
        token = self.token(azp='partner-search')
        claims = await oidc.verify_access_token(token, allowed_clients=('partner-search',))
        self.assertEqual(claims['azp'], 'partner-search')
        for allowed in (None, (), ('other-client',)):
            with self.assertRaises(HTTPException):
                await oidc.verify_access_token(token, allowed_clients=allowed)

    async def test_missing_expiration_rejected(self):
        claims = {**self.claims}
        del claims['exp']
        token = jwt.encode(claims, self.pem, algorithm='RS256', headers={'kid': 'test-key'})
        with self.assertRaises(HTTPException):
            await oidc.verify_access_token(token)

    async def test_realm_or_other_client_admin_does_not_grant_application_access(self):
        for resources in (None, 'invalid', {}, {'other': {'roles': ['super_admin']}}, {'kb-api': {'roles': 'super_admin'}}):
            with self.assertRaises(HTTPException) as error:
                oidc.role_from_claims({'realm_access': {'roles': ['super_admin']}, 'resource_access': resources})
            self.assertEqual(error.exception.status_code, 403)

    async def test_password_login_cannot_bypass_sso(self):
        session = SimpleNamespace(execute=AsyncMock(), get=AsyncMock())
        with self.assertRaises(HTTPException) as error:
            await auth.login(auth.LoginIn(username='test', password='test'), session)
        self.assertEqual(error.exception.status_code, 409)
        session.execute.assert_not_called()

    async def test_legacy_api_key_cannot_bypass_central_user_disable(self):
        with self.assertRaises(HTTPException):
            await get_principal(None, 'kb_test')

    async def test_no_credential_returns_401(self):
        with self.assertRaises(HTTPException) as error:
            await get_current_user(None)
        self.assertEqual(error.exception.status_code, 401)

    async def test_same_name_never_links_existing_account(self):
        result = lambda value: SimpleNamespace(scalar_one_or_none=lambda: value)
        session = SimpleNamespace(execute=AsyncMock(side_effect=[result(None), result(uuid4()), result(None)]), add=unittest.mock.Mock())
        @asynccontextmanager
        async def fake_session():
            yield session
        with patch.object(oidc, 'short_session', fake_session), self.assertRaises(HTTPException) as error:
            await oidc.resolve_oidc_user(self.claims)
        self.assertEqual(error.exception.status_code, 409)
        session.add.assert_not_called()

    async def test_explicit_binding_retains_user_id_and_uses_token_role(self):
        user_id = uuid4()
        user = User(id=user_id, username='existing', role='super_admin', is_active=True)
        result = SimpleNamespace(scalar_one_or_none=lambda: UserIdentity(user_id=user_id))
        session = SimpleNamespace(execute=AsyncMock(return_value=result), get=AsyncMock(return_value=user),
            commit=AsyncMock(), refresh=AsyncMock(), expunge=unittest.mock.Mock())
        @asynccontextmanager
        async def fake_session():
            yield session
        with patch.object(oidc, 'short_session', fake_session):
            resolved = await oidc.resolve_oidc_user(self.claims)
        self.assertEqual(resolved.id, user_id)
        self.assertEqual(resolved.role, 'viewer')
        self.assertEqual(resolved.username, 'existing')

    async def test_disabled_binding_stays_disabled(self):
        user = User(id=uuid4(), username='test', is_active=False)
        result = SimpleNamespace(scalar_one_or_none=lambda: UserIdentity(user_id=user.id))
        session = SimpleNamespace(execute=AsyncMock(return_value=result), get=AsyncMock(return_value=user))
        @asynccontextmanager
        async def fake_session():
            yield session
        with patch.object(oidc, 'short_session', fake_session), self.assertRaises(HTTPException):
            await oidc.resolve_oidc_user(self.claims)

    async def test_parallel_first_login_reuses_exact_identity(self):
        user = User(id=uuid4(), username='test', role='viewer', is_active=True)
        identity = UserIdentity(user_id=user.id)
        result = lambda value: SimpleNamespace(scalar_one_or_none=lambda: value)
        session = SimpleNamespace(execute=AsyncMock(side_effect=[result(None), result(user.id), result(identity)]),
            get=AsyncMock(return_value=user), commit=AsyncMock(), refresh=AsyncMock(), expunge=unittest.mock.Mock())
        @asynccontextmanager
        async def fake_session():
            yield session
        with patch.object(oidc, 'short_session', fake_session):
            resolved = await oidc.resolve_oidc_user(self.claims)
        self.assertEqual(resolved.id, user.id)

    async def test_unknown_signing_key_rejected_without_unbounded_fetch(self):
        token = jwt.encode(self.claims, self.pem, algorithm='RS256', headers={'kid': 'unknown'})
        with patch.object(oidc.httpx, 'AsyncClient') as client, self.assertRaises(HTTPException):
            await oidc.verify_access_token(token)
        client.assert_not_called()

    async def test_invalid_signature_rejected(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private = other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        token = jwt.encode(self.claims, private, algorithm='RS256', headers={'kid': 'test-key'})
        with self.assertRaises(HTTPException):
            await oidc.verify_access_token(token)

    def dev_session(self, first_lookup):
        session = SimpleNamespace(execute=AsyncMock(side_effect=[first_lookup]),
            commit=AsyncMock(), refresh=AsyncMock(), expunge=unittest.mock.Mock(), add=unittest.mock.Mock())

        @asynccontextmanager
        async def fake_session():
            yield session
        return session, fake_session

    async def test_dev_login_endpoint_gate_and_issue(self):
        from kb_common.security import create_jwt
        user = User(id=uuid4(), username='admin', role='super_admin', is_active=True)
        session = SimpleNamespace(execute=AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
        # 未配置 DEV_AUTH_TOKEN：端点不存在
        with patch.object(auth, 'get_settings', return_value=SimpleNamespace(dev_auth_token='')):
            with self.assertRaises(HTTPException) as error:
                await auth.dev_login(auth.DevLoginIn(token='x'), s=session)
            self.assertEqual(error.exception.status_code, 404)
        # 配置后：令牌不正确拒绝
        cfg = SimpleNamespace(dev_auth_token='dev-token-x')
        with patch.object(auth, 'get_settings', return_value=cfg):
            with self.assertRaises(HTTPException) as error:
                await auth.dev_login(auth.DevLoginIn(token='wrong'), s=session)
            self.assertEqual(error.exception.status_code, 401)
            # 令牌正确：换发与 /auth/login 同构的标准 JWT
            with patch.object(auth, 'dev_user', AsyncMock(return_value=user)):
                result = await auth.dev_login(auth.DevLoginIn(token='dev-token-x'), s=session)
        self.assertTrue(result['access_token'])
        self.assertEqual(result['user']['username'], 'admin')
        self.assertEqual(jwt.get_unverified_claims(result['access_token'])['sub'], str(user.id))

    async def test_local_jwt_accepted_only_with_dev_switch(self):
        from kb_common.security import create_jwt
        user = User(id=uuid4(), username='localdev', role='super_admin', is_active=True)
        token = create_jwt(str(user.id), 'super_admin')

        def session_yielding(found):
            @asynccontextmanager
            async def fake_session():
                yield found
            return fake_session

        # 开关开启：接受 /auth/dev-login 换发的本地 JWT
        self.cfg.dev_auth_token = 'dev-token-x'
        with patch.object(oidc, 'short_session', session_yielding(SimpleNamespace(get=AsyncMock(return_value=user)))):
            resolved = await oidc.authenticate(token)
        self.assertEqual(resolved.username, 'localdev')
        # 开关关闭：同一 JWT 必须走统一登录校验并被拒绝
        self.cfg.dev_auth_token = ''
        with self.assertRaises(HTTPException) as error:
            await oidc.authenticate(token)
        self.assertEqual(error.exception.status_code, 401)
        # 停用用户即使开关开启也拒绝
        self.cfg.dev_auth_token = 'dev-token-x'
        disabled = User(id=user.id, username='localdev', is_active=False)
        with patch.object(oidc, 'short_session', session_yielding(SimpleNamespace(get=AsyncMock(return_value=disabled)))), \
                self.assertRaises(HTTPException) as error:
            await oidc.authenticate(token)
        self.assertEqual(error.exception.status_code, 401)

    async def test_dev_user_reuses_or_creates_super_admin(self):
        self.cfg.dev_auth_user = 'localdev'
        existing = User(id=uuid4(), username='localdev', role='viewer', is_active=True)
        found = SimpleNamespace(scalar_one_or_none=lambda: existing)
        _, fake_session = self.dev_session(found)
        with patch.object(oidc, 'short_session', fake_session):
            resolved = await oidc.dev_user()
        self.assertEqual(resolved.username, 'localdev')
        # 缺失时自动建档 super_admin
        missing = SimpleNamespace(scalar_one_or_none=lambda: None)
        session, fake_session = self.dev_session(missing)
        with patch.object(oidc, 'short_session', fake_session):
            resolved = await oidc.dev_user()
        self.assertEqual(resolved.username, 'localdev')
        self.assertEqual(resolved.role, 'super_admin')
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    async def test_dev_user_rejects_disabled_user(self):
        disabled = SimpleNamespace(scalar_one_or_none=lambda: User(id=uuid4(), username='admin', is_active=False))
        _, fake_session = self.dev_session(disabled)
        with patch.object(oidc, 'short_session', fake_session), self.assertRaises(HTTPException) as error:
            await oidc.dev_user()
        self.assertEqual(error.exception.status_code, 403)
