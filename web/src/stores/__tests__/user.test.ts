/// <reference types="vitest/globals" />
import { setActivePinia, createPinia } from 'pinia'
import { useUserStore } from '../user'

describe('useUserStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('初始状态 token 为空', () => {
    const store = useUserStore()
    expect(store.token).toBe('')
    expect(store.userInfo).toBeNull()
  })

  it('setToken 持久化到 localStorage', () => {
    const store = useUserStore()
    store.setToken('abc123')
    expect(store.token).toBe('abc123')
    expect(localStorage.getItem('kb_token')).toBe('abc123')
  })

  it('logout 清除 token 和用户信息', () => {
    const store = useUserStore()
    store.setToken('abc123')
    store.userInfo = { id: '1', username: 'a', email: 'a@b.c', role: 'admin', is_active: true, created_at: '' }
    store.logout()
    expect(store.token).toBe('')
    expect(store.userInfo).toBeNull()
    expect(localStorage.getItem('kb_token')).toBeNull()
  })
})
