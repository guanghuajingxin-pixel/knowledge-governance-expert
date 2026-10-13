import { ref } from 'vue'
import { createSsoClient, type AuthConfig } from './sso-client'

export const sso = createSsoClient('web', import.meta.env.VITE_API_BASE_URL || '/api/v1')
export const authConfig = ref<AuthConfig | null>(null)
export const authError = ref<string>('')
/** 本地地址（localhost/127.0.0.1）才显示本地调试登录入口；生产域名自动隐藏 */
export const isLocalAddress = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(location.hostname)
/** 本地调试会话标志：为 true 时请求拦截器直接使用 store 中的 dev JWT，不再向 SSO 适配器取 token */
export const devSession = ref(false)
export async function initializeAuth() {
  authError.value = ''
  try { authConfig.value = await sso.init() }
  catch (error) { authError.value = error instanceof Error ? error.message : '登录服务不可用。' }
}
