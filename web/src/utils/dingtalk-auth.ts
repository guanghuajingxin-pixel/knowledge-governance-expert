// 钉钉扫码登录 / 账号绑定共用工具：授权地址拼装、state 防伪校验、登录后统一跳转
import type { RouteLocationRaw } from 'vue-router'
import type { LoginResponse } from '@/types/user'

/** 扫码授权 state 的临时存放键（回调校验后立即清除） */
export const DINGTALK_OAUTH_STATE_KEY = 'kb_oauth_state'

/** 钉钉扫码授权回调页（全页跳转回本站） */
export const DINGTALK_CALLBACK_PATH = '/login/callback'

/** 生成随机 state（防 CSRF；回调页与 sessionStorage 中留存值比对） */
export function randomOAuthState(): string {
  const c = typeof globalThis !== 'undefined' ? globalThis.crypto : undefined
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, '')
  if (c?.getRandomValues) {
    const bytes = new Uint8Array(16)
    c.getRandomValues(bytes)
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`
}

export function saveDingtalkOAuthState(state: string) {
  try {
    sessionStorage.setItem(DINGTALK_OAUTH_STATE_KEY, state)
  } catch {
    // 隐私模式或存储被禁用：降级为不校验（回调页会提示重新登录）
  }
}

/** 读取并清除 state（单次消费） */
export function takeDingtalkOAuthState(): string {
  try {
    const v = sessionStorage.getItem(DINGTALK_OAUTH_STATE_KEY) || ''
    sessionStorage.removeItem(DINGTALK_OAUTH_STATE_KEY)
    return v
  } catch {
    return ''
  }
}

export function clearDingtalkOAuthState() {
  try {
    sessionStorage.removeItem(DINGTALK_OAUTH_STATE_KEY)
  } catch {
    // 忽略：存储不可用时本就无残留
  }
}

/** 本站回调地址（钉钉应用后台需登记同一域名） */
export function dingtalkCallbackUrl(): string {
  return `${window.location.origin}${DINGTALK_CALLBACK_PATH}`
}

/** 钉钉统一授权页地址（scope=openid，扫码与账号绑定共用） */
export function buildDingtalkAuthUrl(appKey: string, state: string, redirectUri = dingtalkCallbackUrl()): string {
  return 'https://login.dingtalk.com/oauth2/auth'
    + `?redirect_uri=${encodeURIComponent(redirectUri)}`
    + '&response_type=code'
    + `&client_id=${encodeURIComponent(appKey)}`
    + '&scope=openid'
    + `&state=${encodeURIComponent(state)}`
    + '&prompt=consent'
}

/** 发起钉钉授权：留存 state 后整页跳转（不引入钉钉 JS SDK） */
export function gotoDingtalkAuth(appKey: string, redirectUri = dingtalkCallbackUrl()): string {
  const state = randomOAuthState()
  saveDingtalkOAuthState(state)
  const url = buildDingtalkAuthUrl(appKey, state, redirectUri)
  window.location.href = url
  return url
}

/** 仅接受站内相对路径，避免开放重定向 */
export function safeRedirect(value: unknown, fallback = '/chat'): string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : fallback
}

/**
 * 登录成功后的统一去向：需要设密时先去设密页（带原目标），否则回原目标页。
 * token / userInfo 的落地由 userStore.applyLogin 负责。
 */
export function loginDestination(res: LoginResponse, redirect = '/chat'): RouteLocationRaw {
  if (res.must_set_password || res.user?.must_change_password) {
    return { path: '/onboarding/set-password', query: { redirect } }
  }
  return redirect
}

/** 密码强度：至少 8 位且同时包含字母和数字（与后端 set-password 校验一致） */
export function checkPasswordStrength(pwd: string): string | null {
  if (!pwd || pwd.length < 8) return '密码至少 8 位'
  if (pwd.length > 64) return '密码最长 64 位'
  if (!/[A-Za-z]/.test(pwd)) return '密码须包含字母'
  if (!/[0-9]/.test(pwd)) return '密码须包含数字'
  return null
}
