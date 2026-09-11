import { defineStore } from 'pinia'
import * as authApi from '@/api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('kb_token') || '',
    username: localStorage.getItem('kb_username') || 'admin',
  }),
  getters: {
    isLoggedIn: (state) => !!state.token,
  },
  actions: {
    async login(username: string, password: string) {
      const token = await authApi.login(username, password)
      this.token = token
      this.username = username
      localStorage.setItem('kb_token', token)
      localStorage.setItem('kb_username', username)
    },
    logout() {
      this.token = ''
      localStorage.removeItem('kb_token')
      localStorage.removeItem('kb_username')
    },
  },
})
