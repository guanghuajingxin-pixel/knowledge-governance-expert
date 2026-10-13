import request from './request'
import type { LoginRequest, LoginResponse, UserInfo } from '@/types/user'

export function login(data: LoginRequest) {
  return request.post<unknown, LoginResponse>('/auth/login', data)
}

/** 本地调试登录：写死令牌（与 kb-api .env 的 DEV_AUTH_TOKEN 一致）换发标准 JWT */
export function devLogin(token: string) {
  return request.post<unknown, LoginResponse>('/auth/dev-login', { token })
}

export function getUserInfo() {
  return request.get<unknown, UserInfo>('/users/me')
}
