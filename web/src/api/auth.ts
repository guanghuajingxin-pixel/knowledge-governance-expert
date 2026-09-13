import request from './request'
import type { UserInfo, LoginRequest, LoginResponse } from '@/types/user'

export function login(data: LoginRequest) {
  return request.post<unknown, LoginResponse>('/auth/login', data)
}

export function getUserInfo() {
  return request.get<unknown, UserInfo>('/users/me')
}

/** 钉钉 H5 免登前置：corpId + 开关（公开端点） */
export function getDingtalkConfig() {
  return request.get<unknown, { corp_id: string; auto_login_enabled: boolean }>('/auth/dingtalk-config')
}

/** 钉钉 H5 免登：authCode → JWT（首次自动建档） */
export function dingtalkLogin(authCode: string) {
  return request.post<unknown, LoginResponse>('/auth/dingtalk-login', { auth_code: authCode })
}
