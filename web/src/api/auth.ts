import request from './request'
import type { DingtalkLoginChannel, LoginRequest, LoginResponse, UserInfo } from '@/types/user'

export function login(data: LoginRequest) {
  return request.post<unknown, LoginResponse>('/auth/login', data)
}

export function getUserInfo() {
  return request.get<unknown, UserInfo>('/users/me')
}

/** 钉钉配置（公开端点）：corpId / AppKey / 免登与扫码开关 / 回调地址 */
export interface DingtalkConfig {
  corp_id: string
  app_key: string
  auto_login_enabled: boolean
  qr_login_enabled: boolean
  redirect_uri: string
}

/**
 * 读取钉钉登录配置。
 * @param redirectUri 可选，扫码登录回调地址（后端校验白名单后原样返回）
 */
export function getDingtalkConfig(redirectUri?: string) {
  return request.get<unknown, DingtalkConfig>('/auth/dingtalk-config', {
    params: redirectUri ? { redirect_uri: redirectUri } : undefined,
  })
}

/** 钉钉登录：auth_code → JWT（首次自动建档，返回 must_set_password 时需引导设密） */
export function dingtalkLogin(data: { auth_code: string; channel?: DingtalkLoginChannel }) {
  return request.post<unknown, LoginResponse>('/auth/dingtalk-login', data)
}

/** 首次登录 / 管理员重置后设置本地密码（需 JWT）；成功后返回新 token（同 login 结构 + ok） */
export function setPassword(data: { new_password: string; new_password_confirm: string }) {
  return request.post<unknown, LoginResponse & { ok: boolean }>('/auth/set-password', data)
}

/** 已登录用户自助修改密码（需旧密码；成功后建议强制重新登录） */
export function changePassword(data: {
  old_password: string
  new_password: string
  new_password_confirm: string
}) {
  return request.post<unknown, { ok: boolean }>('/auth/change-password', data)
}

/** 把当前登录账号与钉钉身份绑定（扫码授权码换 dt_userid / dt_unionid）；成功后重签新 token */
export function bindDingtalkBinding(authCode: string) {
  return request.post<unknown, LoginResponse & { ok: boolean }>('/users/me/dingtalk-binding', {
    auth_code: authCode,
  })
}
