import request from './request'
import type { UserInfo, LoginRequest, LoginResponse } from '@/types/user'

export function login(data: LoginRequest) {
  return request.post<unknown, LoginResponse>('/auth/login', data)
}

export function getUserInfo() {
  return request.get<unknown, UserInfo>('/users/me')
}
