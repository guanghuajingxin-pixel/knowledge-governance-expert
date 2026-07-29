import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { UserInfo, LoginRequest, LoginResponse } from '@/types/user'
import { login as loginApi, getUserInfo } from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(localStorage.getItem('kb_token') || '')
  const userInfo = ref<UserInfo | null>(null)

  function setToken(t: string) {
    token.value = t
    localStorage.setItem('kb_token', t)
  }

  async function login(payload: LoginRequest) {
    const res: LoginResponse = await loginApi(payload)
    setToken(res.access_token)
    userInfo.value = res.user
    localStorage.setItem('kb_user', JSON.stringify(res.user))
    return res
  }

  async function fetchUserInfo() {
    const res = await getUserInfo()
    userInfo.value = res
    localStorage.setItem('kb_user', JSON.stringify(res))
    return res
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem('kb_token')
    localStorage.removeItem('kb_user')
  }

  function restoreUser() {
    const cached = localStorage.getItem('kb_user')
    if (cached) {
      userInfo.value = JSON.parse(cached)
    }
  }

  return { token, userInfo, setToken, login, fetchUserInfo, logout, restoreUser }
})
