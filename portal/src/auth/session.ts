import { ref } from 'vue'
import { login as passwordLogin, post, type Identity } from '../api/chat'
import { createSsoClient, type AuthConfig } from './sso-client'

/** 本地调试登录令牌（写死，与 kb-api .env 的 DEV_AUTH_TOKEN 一致；仅本地开发使用） */
const DEV_LOGIN_TOKEN = 'kge-local-dev-token'

export const sso = createSsoClient('portal')
export const authConfig = ref<AuthConfig | null>(null)
export const authError = ref<string>('')
export const identity = ref<Identity | null>(null)
export const isAuthReady = ref<boolean>(false)
/** 本地地址（localhost/127.0.0.1）才显示本地调试登录入口；生产域名自动隐藏 */
export const devAuthEnabled = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(location.hostname)
const devToken = ref<string>('')

export async function initializeAuth() {
  isAuthReady.value = false
  authError.value = ''
  try {
    authConfig.value = await sso.init()
    // Remove the obsolete browser-only gate. It is never authentication evidence.
    localStorage.removeItem('jack-aigc-portal.session')
    if (sso.isSso) {
      sso.subscribe(token => {
        if (devToken.value) return // 本地调试会话优先，SSO 适配器事件不覆盖
        if (!token) identity.value = null
        else if (identity.value) identity.value.access_token = token
      })
      const token = await sso.getToken()
      if (token) {
        const response = await fetch('/api/v1/users/me', { headers: { Authorization: `Bearer ${token}` } })
        if (!response.ok) {
          const body = await response.json().catch(() => null) as { detail?: string } | null
          throw new Error(body?.detail || '统一账号尚未获得访问权限，请联系管理员。')
        }
        identity.value = { access_token: token, user: await response.json() }
      }
    }
  } catch (error) { authError.value = error instanceof Error ? error.message : '登录服务不可用。' }
  finally { isAuthReady.value = true }
}
export async function signIn(username: string, password: string) {
  if (!authConfig.value) throw new Error('登录服务尚未就绪，请先重试连接。')
  if (sso.isSso) return sso.login()
  identity.value = await passwordLogin(username, password)
}
/** 本地调试登录：写死令牌经 /auth/dev-login 换发标准 JWT，绕过远程统一登录 */
export async function devSignIn() {
  const result = await post<Identity>('/auth/dev-login', { token: DEV_LOGIN_TOKEN })
  if (!result?.access_token || !result.user?.username) throw new Error('本地调试登录返回异常，请检查 kb-api 配置。')
  devToken.value = result.access_token
  identity.value = result
}
export async function accessToken(): Promise<string> {
  if (devToken.value) return devToken.value
  return sso.isSso ? sso.getToken() : identity.value?.access_token || ''
}
export async function signOut() {
  const wasDevSession = Boolean(devToken.value)
  identity.value = null
  devToken.value = ''
  // 调试会话与远程 SSO 无关，登出只清本地态，不跳转身份中心
  if (sso.isSso && !wasDevSession) await sso.logout()
}
