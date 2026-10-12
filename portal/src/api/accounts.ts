import { ApiError } from './chat'

export interface PortalAccount {
  id: string
  username: string
  name: string
  email: string | null
  enabled: boolean
  created_at: string | null
  roles: string[]
}

export interface AccountListResult {
  items: PortalAccount[]
  page: number
  page_size: number
  has_more: boolean
}

export interface AccountCreateInput {
  username: string
  name: string
  email?: string
  role: string
  password: string
  temporary: boolean
}

export interface AccountUpdateInput {
  name?: string
  /** 空串表示清除邮箱；不传表示不变 */
  email?: string
  role?: string
  enabled?: boolean
}

async function request<T>(method: string, path: string, token: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/v1/portal/accounts${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
  } catch {
    throw new ApiError('暂时无法连接账号服务，请检查网络后重试。')
  }
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null)
    const detail = data && typeof data === 'object' && 'detail' in data
      && typeof (data as { detail: unknown }).detail === 'string'
      ? (data as { detail: string }).detail : ''
    throw new ApiError(
      response.status === 401 ? '登录状态无效，请重新登录。' : detail || `账号服务暂不可用（${response.status}），请稍后重试。`,
      response.status,
    )
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function listAccounts(token: string, params: { search?: string; page: number; page_size?: number }): Promise<AccountListResult> {
  const query = new URLSearchParams({
    search: params.search || '',
    page: String(params.page),
    page_size: String(params.page_size || 20),
  })
  return request<AccountListResult>('GET', `?${query.toString()}`, token)
}

export function createAccount(token: string, body: AccountCreateInput): Promise<PortalAccount> {
  return request<PortalAccount>('POST', '', token, body)
}

export function updateAccount(token: string, id: string, body: AccountUpdateInput): Promise<PortalAccount> {
  return request<PortalAccount>('PATCH', `/${id}`, token, body)
}

export function resetPassword(token: string, id: string, body: { password: string; temporary: boolean }): Promise<void> {
  return request<void>('PUT', `/${id}/password`, token, body)
}

export function deleteAccount(token: string, id: string): Promise<void> {
  return request<void>('DELETE', `/${id}`, token)
}
