import request from './request'
import type { UserInfo, LoginRequest, LoginResponse, ApiKey, ApiKeyCreated } from '@/types/user'

export function login(data: LoginRequest) {
  return request.post<unknown, LoginResponse>('/auth/login', data)
}

export function getUserInfo() {
  return request.get<unknown, UserInfo>('/users/me')
}

export function getApiKeys() {
  return request.get<unknown, ApiKey[]>('/auth/api-keys')
}

export function createApiKey(name: string) {
  return request.post<unknown, ApiKeyCreated>('/auth/api-keys', { name })
}

export function deleteApiKey(id: string) {
  return request.delete<unknown, void>(`/auth/api-keys/${id}`)
}
