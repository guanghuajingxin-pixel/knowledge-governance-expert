import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.deps import get_current_user
from app.routes import portal_accounts as routes
from app.services import portal_accounts as service
from app.services.keycloak_admin import KeycloakAdmin

PASSWORD = 'Abcdef123456'


def kc_response(status, payload=None):
    return httpx.Response(status, json=payload if payload is not None else {},
                          request=httpx.Request('GET', 'http://kc'))


class KeycloakAdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_error_message_overrides(self):
        client = AsyncMock()
        admin = KeycloakAdmin(client, 'http://kc/admin/realms/jack')
        client.request.return_value = kc_response(409)
        with self.assertRaises(HTTPException) as error:
            await admin.call('POST', 'users', conflict='用户名已存在，请更换后重试')
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn('用户名已存在', error.exception.detail)
        client.request.return_value = kc_response(404)
        with self.assertRaises(HTTPException) as error:
            await admin.call('GET', 'users/x', not_found='账号不存在')
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(error.exception.detail, '账号不存在')

    async def test_defaults_and_password_policy_passthrough(self):
        client = AsyncMock()
        admin = KeycloakAdmin(client, 'http://kc/admin/realms/jack')
        client.request.return_value = kc_response(404)
        with self.assertRaises(HTTPException) as error:
            await admin.call('GET', 'clients/x')
        self.assertIn('平台应用或检索角色不存在', error.exception.detail)
        client.request.return_value = kc_response(400, {'error_description': 'Password policy not met'})
        with self.assertRaises(HTTPException) as error:
            await admin.call('PUT', 'users/x/reset-password', json={})
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, 'Password policy not met')


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.remote = AsyncMock()

        @asynccontextmanager
        async def session():
            yield self.remote
        p = patch.object(service, 'admin_session', session)
        p.start()
        self.addCleanup(p.stop)
        cfg = patch.object(service, 'configuration', return_value=SimpleNamespace(oidc_audience='kb-api'))
        cfg.start()
        self.addCleanup(cfg.stop)
        self.user_id = str(uuid4())
        self.row = {'id': self.user_id, 'username': 'jack', 'firstName': 'Jack',
                    'email': 'jack@example.com', 'enabled': True, 'createdTimestamp': 1700000000000}

    async def test_create_account_sequence_and_payload(self):
        self.remote.call.side_effect = [
            [{'id': 'rid'}], {'name': 'viewer'}, None, [self.row], None, None]
        result = await service.create_account(username='jack', name='Jack', email='jack@example.com',
                                              role='viewer', password=PASSWORD, temporary=True)
        calls = self.remote.call.call_args_list
        self.assertEqual(calls[2].args, ('POST', 'users'))
        self.assertEqual(calls[2].kwargs['json']['username'], 'jack')
        self.assertTrue(calls[2].kwargs['json']['emailVerified'])
        self.assertEqual(calls[4].args, (f'PUT', f'users/{self.user_id}/reset-password'))
        self.assertTrue(calls[4].kwargs['json']['temporary'])
        self.assertEqual(calls[5].args, ('POST', f'users/{self.user_id}/role-mappings/clients/rid'))
        self.assertEqual(result['roles'], ['viewer'])
        self.assertEqual(result['id'], self.user_id)

    async def test_create_without_email_omits_email_fields(self):
        self.remote.call.side_effect = [
            [{'id': 'rid'}], {'name': 'viewer'}, None, [self.row], None, None]
        await service.create_account(username='jack', name='Jack', email=None,
                                     role='viewer', password=PASSWORD, temporary=False)
        payload = self.remote.call.call_args_list[2].kwargs['json']
        self.assertNotIn('email', payload)
        self.assertNotIn('emailVerified', payload)

    async def test_failed_creation_cleans_up(self):
        self.remote.call.side_effect = [
            [{'id': 'rid'}], {'name': 'viewer'}, None, [self.row], HTTPException(503), None]
        with self.assertRaises(HTTPException):
            await service.create_account(username='jack', name='Jack', email=None,
                                         role='viewer', password=PASSWORD, temporary=True)
        self.remote.call.assert_awaited_with('DELETE', f'users/{self.user_id}')

    async def test_username_conflict_message(self):
        self.remote.call.side_effect = [[{'id': 'rid'}], {'name': 'viewer'}, HTTPException(409, '用户名已存在，请更换后重试')]
        with self.assertRaises(HTTPException) as error:
            await service.create_account(username='jack', name='Jack', email=None,
                                         role='viewer', password=PASSWORD, temporary=True)
        self.assertEqual(error.exception.detail, '用户名已存在，请更换后重试')

    async def test_invalid_role_rejected(self):
        with self.assertRaises(HTTPException) as error:
            await service.create_account(username='jack', name='Jack', email=None,
                                         role='guest', password=PASSWORD, temporary=True)
        self.assertEqual(error.exception.status_code, 400)

    async def test_list_filters_service_accounts_and_maps_roles(self):
        service_row = {'id': 'svc', 'username': 'service-account-x', 'serviceAccountClientLink': 'rid'}
        self.remote.call.side_effect = [
            [self.row, service_row], [{'id': 'rid'}], [{'name': 'admin'}]]
        rows = await service.list_accounts(search='jack', first=0, max_results=21)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['roles'], ['admin'])
        self.assertEqual(rows[0]['username'], 'jack')
        params = self.remote.call.call_args_list[0].kwargs['params']
        self.assertEqual(params['search'], 'jack')
        self.assertEqual(self.remote.call.call_args_list[2].args,
                         ('GET', f'users/{self.user_id}/role-mappings/clients/rid'))

    async def test_update_replaces_role(self):
        self.remote.call.side_effect = [
            self.row, None, [{'id': 'rid'}], [{'name': 'viewer'}],
            {'name': 'admin'}, None, [{'name': 'viewer'}]]
        result = await service.update_account(self.user_id, name='New', role='admin', enabled=True)
        calls = self.remote.call.call_args_list
        self.assertEqual(calls[1].kwargs['json'], {'firstName': 'New', 'enabled': True})
        self.assertEqual(calls[5].args[1], f'users/{self.user_id}/role-mappings/clients/rid')
        self.assertEqual(calls[6].args[0], 'DELETE')
        self.assertEqual(result['roles'], ['admin'])

    async def test_update_clears_email(self):
        self.remote.call.side_effect = [self.row, None, [{'id': 'rid'}], []]
        result = await service.update_account(self.user_id, email='')
        changes = self.remote.call.call_args_list[1].kwargs['json']
        self.assertIsNone(changes['email'])
        self.assertFalse(changes['emailVerified'])
        self.assertIsNone(result['email'])

    async def test_reset_password_and_delete(self):
        self.remote.call.side_effect = [self.row, None]
        await service.reset_password(self.user_id, password=PASSWORD, temporary=True)
        self.remote.call.assert_awaited_with(
            'PUT', f'users/{self.user_id}/reset-password',
            json={'type': 'password', 'value': PASSWORD, 'temporary': True})
        self.remote.call.side_effect = [self.row, None]
        await service.delete_account(self.user_id)
        self.remote.call.assert_awaited_with('DELETE', f'users/{self.user_id}')

    async def test_missing_user_maps_to_404(self):
        self.remote.call.side_effect = [HTTPException(404, '账号不存在')]
        with self.assertRaises(HTTPException) as error:
            await service.delete_account(uuid4())
        self.assertEqual(error.exception.status_code, 404)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(routes.router)
        self.app.dependency_overrides[routes.get_session] = lambda: None
        self.actor = SimpleNamespace(role='admin', id=uuid4(), username='boss')
        self.app.dependency_overrides[get_current_user] = lambda: self.actor
        self.client = TestClient(self.app)
        self.base = '/api/v1/portal/accounts'

    def test_all_endpoints_admin_only(self):
        self.actor.role = 'viewer'
        target = self.base + '/' + str(uuid4())
        for method, url, kwargs in [('GET', self.base, {}), ('POST', self.base, self.create_body()),
                                    ('PATCH', target, {'json': {'enabled': False}}),
                                    ('PUT', target + '/password', {'json': {'password': PASSWORD}}),
                                    ('DELETE', target, {})]:
            self.assertEqual(self.client.request(method, url, **kwargs).status_code, 403)

    @staticmethod
    def create_body(**overrides):
        body = {'username': 'newbie', 'name': '新同学', 'role': 'viewer',
                'password': PASSWORD, 'temporary': True}
        body.update(overrides)
        return {'json': body}

    def test_admin_cannot_assign_super_admin(self):
        r = self.client.post(self.base, **self.create_body(role='super_admin'))
        self.assertEqual(r.status_code, 403)
        self.assertIn('仅超级管理员', r.json()['detail'])

    def test_admin_cannot_write_super_admin_accounts(self):
        target = {'id': str(uuid4()), 'username': 'root', 'roles': ['super_admin'], 'enabled': True}
        user_id = target['id']
        with patch.object(service, 'get_account', new_callable=AsyncMock, return_value=target):
            for method, url, kwargs in [
                    ('PATCH', f'{self.base}/{user_id}', {'json': {'enabled': False}}),
                    ('PUT', f'{self.base}/{user_id}/password', {'json': {'password': PASSWORD}}),
                    ('DELETE', f'{self.base}/{user_id}', {})]:
                self.assertEqual(self.client.request(method, url, **kwargs).status_code, 403)

    def test_cannot_disable_or_delete_self(self):
        me = {'id': str(uuid4()), 'username': 'boss', 'roles': ['admin'], 'enabled': True}
        with patch.object(service, 'get_account', new_callable=AsyncMock, return_value=me):
            r = self.client.patch(f'{self.base}/{me["id"]}', json={'enabled': False})
            self.assertEqual(r.status_code, 400)
            r = self.client.patch(f'{self.base}/{me["id"]}', json={'role': 'viewer'})
            self.assertEqual(r.status_code, 400)
            r = self.client.delete(f'{self.base}/{me["id"]}')
            self.assertEqual(r.status_code, 400)

    def test_super_admin_can_assign_super_admin(self):
        self.actor.role = 'super_admin'
        row = {'id': str(uuid4()), 'username': 'newbie', 'name': '新同学', 'email': None,
               'enabled': True, 'created_at': None, 'roles': ['super_admin']}
        with patch.object(service, 'create_account', new_callable=AsyncMock, return_value=row), \
                patch.object(routes, 'write_audit', new_callable=AsyncMock):
            r = self.client.post(self.base, **self.create_body(role='super_admin'))
        self.assertEqual(r.status_code, 201)

    def test_create_success_audit_without_password(self):
        row = {'id': str(uuid4()), 'username': 'newbie', 'name': '新同学', 'email': None,
               'enabled': True, 'created_at': None, 'roles': ['viewer']}
        with patch.object(service, 'create_account', new_callable=AsyncMock, return_value=row), \
                patch.object(routes, 'write_audit', new_callable=AsyncMock) as audit:
            r = self.client.post(self.base, **self.create_body())
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.headers['cache-control'], 'no-store')
        self.assertNotIn(PASSWORD, str(audit.call_args))

    def test_list_has_more_trims_extra(self):
        items = [{'id': str(uuid4()), 'username': f'u{i}', 'name': '', 'email': None,
                  'enabled': True, 'created_at': None, 'roles': []} for i in range(21)]
        with patch.object(service, 'list_accounts', new_callable=AsyncMock, return_value=items):
            r = self.client.get(self.base)
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(body['items']), 20)
        self.assertTrue(body['has_more'])

    def test_empty_username_rejected(self):
        for bad in ('', ' '):
            r = self.client.post(self.base, **self.create_body(username=bad))
            self.assertEqual(r.status_code, 422)
