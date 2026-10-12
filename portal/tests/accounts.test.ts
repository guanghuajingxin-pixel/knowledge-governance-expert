import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createAccount, deleteAccount, listAccounts, resetPassword, updateAccount,
} from '../src/api/accounts'
import { pageFromHash } from '../src/config/apps'

const token = 'unit-test-token'
afterEach(() => vi.unstubAllGlobals())
function mockResponse(body: unknown, status = 200) {
  const mock = vi.fn().mockResolvedValue(new Response(
    status === 204 ? null : JSON.stringify(body),
    { status, headers: { 'Content-Type': 'application/json' } },
  ))
  vi.stubGlobal('fetch', mock)
  return mock
}

describe('portal account api', () => {
  it('lists accounts with search and pagination parameters', async () => {
    const fetch = mockResponse({ items: [], page: 2, page_size: 20, has_more: false })
    await listAccounts(token, { search: '张三', page: 2 })
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/v1/portal/accounts?search=%E5%BC%A0%E4%B8%89&page=2&page_size=20')
    expect(init.headers.Authorization).toBe(`Bearer ${token}`)
  })

  it('creates an account with role and temporary password flag', async () => {
    const fetch = mockResponse({ id: 'u1', username: 'zhangsan', name: '张三', email: null, enabled: true, created_at: null, roles: ['viewer'] }, 201)
    await createAccount(token, { username: 'zhangsan', name: '张三', role: 'viewer', password: 'Abcdef123456', temporary: true })
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/v1/portal/accounts')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ username: 'zhangsan', name: '张三', role: 'viewer', password: 'Abcdef123456', temporary: true })
  })

  it('updates an account and clears email with an empty string', async () => {
    const fetch = mockResponse({ id: 'u1', username: 'zhangsan', name: '张三', email: null, enabled: true, created_at: null, roles: ['admin'] })
    await updateAccount(token, 'u1', { name: '张三三', email: '', role: 'admin' })
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/v1/portal/accounts/u1')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual({ name: '张三三', email: '', role: 'admin' })
  })

  it('resets password without expecting a response body', async () => {
    const fetch = mockResponse(null, 204)
    await expect(resetPassword(token, 'u1', { password: 'Abcdef123456', temporary: true })).resolves.toBeUndefined()
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/v1/portal/accounts/u1/password')
    expect(init.method).toBe('PUT')
  })

  it('deletes an account', async () => {
    const fetch = mockResponse(null, 204)
    await deleteAccount(token, 'u1')
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/v1/portal/accounts/u1')
    expect(init.method).toBe('DELETE')
  })

  it('surfaces backend detail messages for permission errors', async () => {
    mockResponse({ detail: '仅超级管理员可分配超级管理员角色' }, 403)
    await expect(createAccount(token, { username: 'x', name: 'x', role: 'super_admin', password: 'Abcdef123456', temporary: true }))
      .rejects.toThrow('仅超级管理员可分配超级管理员角色')
  })

  it('keeps expired authentication distinguishable from service failures', async () => {
    mockResponse({}, 401)
    await expect(listAccounts(token, { page: 1 })).rejects.toMatchObject({ status: 401 })
  })
})

describe('portal navigation', () => {
  it('supports the accounts management deep link', () => {
    expect(pageFromHash('#/accounts')).toBe('accounts')
    expect(pageFromHash('#/account')).toBe('home')
  })
})
