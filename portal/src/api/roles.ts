import { ApiError } from './chat'

export interface PortalRole {
  id: string
  code: string
  name: string
  description: string
  is_system: boolean
  /** null = 未配置（全部菜单）；列表 = 白名单 */
  menu_permissions: string[] | null
  user_count: number
  created_at: string | null
  updated_at: string | null
}

export interface RoleCreateInput {
  code: string
  name: string
  description?: string
  menu_permissions?: string[] | null
}

/** 全量替换语义：name/description 传 null 表示不变；menu_permissions 传 null 表示恢复全部菜单 */
export interface RoleUpdateInput {
  name?: string
  description?: string | null
  menu_permissions?: string[] | null
}

export interface MenuNode {
  key: string
  label: string
  children?: MenuNode[]
}

export interface MenuTree {
  groups: Array<{ key: string; label: string; children: MenuNode[] }>
}

export interface MenuPermissionsResult {
  menu_permissions: string[] | null
  effective: string[] | null
}

async function request<T>(method: string, path: string, token: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/v1/portal${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
  } catch {
    throw new ApiError('暂时无法连接角色服务，请检查网络后重试。')
  }
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null)
    const detail = data && typeof data === 'object' && 'detail' in data
      && typeof (data as { detail: unknown }).detail === 'string'
      ? (data as { detail: string }).detail : ''
    throw new ApiError(
      response.status === 401 ? '登录状态无效，请重新登录。' : detail || `角色服务暂不可用（${response.status}），请稍后重试。`,
      response.status,
    )
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function listMenus(token: string): Promise<MenuTree> {
  return request<MenuTree>('GET', '/menus', token)
}

export function listRoles(token: string): Promise<PortalRole[]> {
  return request<PortalRole[]>('GET', '/roles', token)
}

export function createRole(token: string, body: RoleCreateInput): Promise<PortalRole> {
  return request<PortalRole>('POST', '/roles', token, body)
}

export function updateRole(token: string, id: string, body: RoleUpdateInput): Promise<PortalRole> {
  return request<PortalRole>('PUT', `/roles/${id}`, token, body)
}

export function deleteRole(token: string, id: string): Promise<void> {
  return request<void>('DELETE', `/roles/${id}`, token)
}
