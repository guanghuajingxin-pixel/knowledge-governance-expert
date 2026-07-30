import request from './request'
import type { UserInfo } from '@/types/user'

export interface Page<T> { items: T[]; total: number; page: number; size: number }
export interface UserCreatePayload { username: string; password: string; email?: string; role: string }
export interface UserUpdatePayload { email?: string; role?: string; is_active?: boolean; password?: string }

export function getUsers(page = 1, size = 20) {
  return request.get<unknown, Page<UserInfo>>('/users', { params: { page, size } })
}
export function createUser(data: UserCreatePayload) {
  return request.post<unknown, UserInfo>('/users', data)
}
export function updateUser(id: string, data: UserUpdatePayload) {
  return request.put<unknown, UserInfo>(`/users/${id}`, data)
}
export function deleteUser(id: string) {
  return request.delete<unknown, void>(`/users/${id}`)
}
