"""门户角色管理：CRUD 护栏、菜单权限解析语义与路由接线。"""
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.deps import get_current_user
from app.routes import portal_roles as routes
from app.services import portal_roles as service
from app.services import menu_permissions as perms_service


def role_row(**overrides):
    row = SimpleNamespace(id=uuid4(), code='kb_ops', name='知识运营', description=None,
                          is_system=False, menu_permissions=None,
                          created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1))
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


class ValidationTests(unittest.TestCase):
    def test_code_pattern(self):
        for bad in ('Abc', '1abc', 'a', '有中文', 'a' * 51, 'kb-ops'):
            with self.assertRaises(HTTPException) as error:
                service.validate_code(bad)
            self.assertEqual(error.exception.status_code, 400)
        service.validate_code('kb_ops')
        service.validate_code('market_readonly_2026')

    def test_code_cannot_reuse_system_codes(self):
        with self.assertRaises(HTTPException) as error:
            service.validate_code('admin')
        self.assertEqual(error.exception.status_code, 400)

    def test_menu_permissions_semantics(self):
        self.assertIsNone(service.validate_menu_permissions(None))
        for bad in ([], ['unknown-key']):
            with self.assertRaises(HTTPException) as error:
                service.validate_menu_permissions(bad)
            self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(service.validate_menu_permissions(['/chat', 'portal.home']),
                         ['/chat', 'portal.home'])


class ServiceCrudTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = AsyncMock()
        # code 查重默认命中 None、本地用户计数 0（AsyncMock.return_value 仍是 AsyncMock，
        # 必须用普通 lambda 覆写 scalar_one_or_none / scalar）
        self.session.execute.return_value.scalar_one_or_none = lambda: None
        self.session.execute.return_value.scalar = lambda: 0
        settings = patch.object(service, 'get_settings',
                                return_value=SimpleNamespace(auth_provider='local'))
        settings.start()
        self.addCleanup(settings.stop)

    async def test_create_role_local_mode(self):
        result = await service.create_role(self.session, code='kb_ops', name='知识运营',
                                           description=None, menu_permissions=['/chat'])
        self.session.add.assert_called_once()
        self.session.commit.assert_awaited()
        self.assertEqual(result['code'], 'kb_ops')
        self.assertEqual(result['menu_permissions'], ['/chat'])

    async def test_create_role_conflict_409(self):
        self.session.execute.return_value.scalar_one_or_none = lambda: role_row()
        with self.assertRaises(HTTPException) as error:
            await service.create_role(self.session, code='kb_ops', name='知识运营',
                                      description=None, menu_permissions=None)
        self.assertEqual(error.exception.status_code, 409)

    async def test_create_role_keycloak_sync_failure_rolls_back(self):
        with patch.object(service, 'get_settings',
                          return_value=SimpleNamespace(auth_provider='keycloak')), \
                patch.object(service, '_sync_create_client_role',
                             new_callable=AsyncMock, side_effect=HTTPException(503, '身份中心暂不可用')):
            with self.assertRaises(HTTPException):
                await service.create_role(self.session, code='kb_ops', name='知识运营',
                                          description=None, menu_permissions=None)
        self.session.delete.assert_called_once()
        self.session.commit.assert_awaited()

    async def test_update_system_role_rejects_name_change(self):
        row = role_row(code='admin', name='管理员', is_system=True)
        self.session.get.return_value = row
        with self.assertRaises(HTTPException) as error:
            await service.update_role(self.session, row.id, name='新名字',
                                      description=None, menu_permissions=service.UNSET)
        self.assertEqual(error.exception.status_code, 400)

    async def test_update_system_role_allows_menu_permissions(self):
        row = role_row(code='viewer', name='查看者', is_system=True)
        self.session.get.return_value = row
        with patch.object(service, 'user_count', new_callable=AsyncMock, return_value=3):
            result = await service.update_role(self.session, row.id, name='查看者',
                                               description=None, menu_permissions=['/chat'])
        self.assertEqual(row.menu_permissions, ['/chat'])
        self.assertEqual(result['user_count'], 3)

    async def test_update_unset_menu_permissions_keeps_value(self):
        row = role_row(menu_permissions=['/chat'])
        self.session.get.return_value = row
        await service.update_role(self.session, row.id, name='知识运营',
                                  description='新描述', menu_permissions=service.UNSET)
        self.assertEqual(row.menu_permissions, ['/chat'])
        self.assertEqual(row.description, '新描述')

    async def test_update_null_menu_permissions_resets_to_all(self):
        row = role_row(menu_permissions=['/chat'])
        self.session.get.return_value = row
        with patch.object(service, 'user_count', new_callable=AsyncMock, return_value=0):
            await service.update_role(self.session, row.id, name='知识运营',
                                      description=None, menu_permissions=None)
        self.assertIsNone(row.menu_permissions)

    async def test_delete_system_role_rejected(self):
        row = role_row(code='admin', is_system=True)
        self.session.get.return_value = row
        with self.assertRaises(HTTPException) as error:
            await service.delete_role(self.session, row.id)
        self.assertEqual(error.exception.status_code, 400)

    async def test_delete_in_use_role_rejected(self):
        row = role_row()
        self.session.get.return_value = row
        with patch.object(service, 'user_count', new_callable=AsyncMock, return_value=2):
            with self.assertRaises(HTTPException) as error:
                await service.delete_role(self.session, row.id)
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn('2 个用户', error.exception.detail)

    async def test_delete_role_local(self):
        row = role_row()
        self.session.get.return_value = row
        with patch.object(service, 'user_count', new_callable=AsyncMock, return_value=0), \
                patch.object(service, 'get_settings',
                             return_value=SimpleNamespace(auth_provider='local')):
            await service.delete_role(self.session, row.id)
        self.session.delete.assert_called_once_with(row)

    async def test_delete_role_keycloak_syncs_client_role(self):
        row = role_row()
        self.session.get.return_value = row
        with patch.object(service, 'user_count', new_callable=AsyncMock, return_value=0), \
                patch.object(service, 'get_settings',
                             return_value=SimpleNamespace(auth_provider='keycloak')), \
                patch.object(service, '_sync_delete_client_role',
                             new_callable=AsyncMock) as sync:
            await service.delete_role(self.session, row.id)
        sync.assert_awaited_once_with('kb_ops')


class MenuPermissionResolutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = AsyncMock()
        self.user = SimpleNamespace(id=uuid4(), role='viewer')

    def _override(self, value):
        """构造 override 查询结果（value=None 表示无覆盖行）。"""
        row = (SimpleNamespace(user_id=str(self.user.id), menu_permissions=value)
               if value is not None else None)
        self.session.execute.return_value.scalar_one_or_none = lambda: row

    async def test_super_admin_bypass(self):
        self.user.role = 'super_admin'
        self.assertIsNone(await perms_service.resolve_menu_permissions(self.session, self.user))

    async def test_override_wins(self):
        self._override(['/chat', '/model'])
        self.assertEqual(await perms_service.resolve_menu_permissions(self.session, self.user),
                         ['/chat', '/model'])

    async def test_falls_back_to_role_when_no_override(self):
        role = SimpleNamespace(code='viewer', menu_permissions=['/chat'])
        results = iter([None, role])
        self.session.execute = AsyncMock(side_effect=lambda *a, **k: SimpleNamespace(
            scalar_one_or_none=lambda: next(results)))
        self.assertEqual(await perms_service.resolve_menu_permissions(self.session, self.user),
                         ['/chat'])

    async def test_missing_role_row_fail_open(self):
        self._override(None)
        self.assertIsNone(await perms_service.resolve_menu_permissions(self.session, self.user))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(routes.router)
        self.app.dependency_overrides[routes.get_session] = lambda: None
        self.actor = SimpleNamespace(role='admin', id=uuid4(), username='boss')
        self.app.dependency_overrides[get_current_user] = lambda: self.actor
        self.client = TestClient(self.app)
        self.base = '/api/v1/portal'

    @staticmethod
    def role_out(**overrides):
        body = {'id': str(uuid4()), 'code': 'kb_ops', 'name': '知识运营', 'description': '',
                'is_system': False, 'menu_permissions': None, 'user_count': 0,
                'created_at': None, 'updated_at': None}
        body.update(overrides)
        return body

    def test_endpoints_admin_only(self):
        self.actor.role = 'viewer'
        role_id = str(uuid4())
        for method, url, kwargs in [
                ('GET', f'{self.base}/menus', {}),
                ('GET', f'{self.base}/roles', {}),
                ('POST', f'{self.base}/roles',
                 {'json': {'code': 'kb_ops', 'name': '知识运营'}}),
                ('PUT', f'{self.base}/roles/{role_id}',
                 {'json': {'menu_permissions': ['/chat']}}),
                ('DELETE', f'{self.base}/roles/{role_id}', {})]:
            self.assertEqual(self.client.request(method, url, **kwargs).status_code, 403)

    def test_menus_endpoint_returns_groups(self):
        r = self.client.get(f'{self.base}/menus')
        self.assertEqual(r.status_code, 200)
        groups = r.json()['groups']
        self.assertEqual([g['key'] for g in groups], ['portal', 'web'])
        web = groups[1]
        self.assertIn({'key': '/chat', 'label': '智能问答'}, web['children'])

    def test_list_roles_wiring(self):
        with patch.object(service, 'list_roles', new_callable=AsyncMock,
                          return_value=[self.role_out(code='viewer', name='查看者')]):
            r = self.client.get(f'{self.base}/roles')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]['code'], 'viewer')

    def test_update_distinguishes_unset_and_null(self):
        role_id = str(uuid4())
        with patch.object(service, 'update_role', new_callable=AsyncMock,
                          return_value=self.role_out(id=role_id)) as update, \
                patch.object(routes, 'write_audit', new_callable=AsyncMock):
            r = self.client.put(f'{self.base}/roles/{role_id}', json={'menu_permissions': None})
        self.assertEqual(r.status_code, 200)
        self.assertIs(update.call_args.kwargs['menu_permissions'], None)
        # 未提交 menu_permissions 字段 → UNSET 哨兵
        with patch.object(service, 'update_role', new_callable=AsyncMock,
                          return_value=self.role_out(id=role_id, name='新名称')) as update, \
                patch.object(routes, 'write_audit', new_callable=AsyncMock):
            r = self.client.put(f'{self.base}/roles/{role_id}', json={'name': '新名称'})
        self.assertEqual(r.status_code, 200)
        self.assertIs(update.call_args.kwargs['menu_permissions'], service.UNSET)

    def test_create_role_validation_and_audit(self):
        with patch.object(service, 'create_role', new_callable=AsyncMock,
                          return_value=self.role_out()) as create, \
                patch.object(routes, 'write_audit', new_callable=AsyncMock) as audit:
            r = self.client.post(f'{self.base}/roles',
                                 json={'code': 'kb_ops', 'name': '知识运营',
                                       'menu_permissions': ['/chat', 'portal.home']})
        self.assertEqual(r.status_code, 201)
        create.assert_awaited_once()
        self.assertEqual(audit.call_args.kwargs['action'], 'portal_role_create')


if __name__ == '__main__':
    unittest.main()
