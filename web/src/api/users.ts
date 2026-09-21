import request from './request'
import type { UserInfo } from '@/types/user'

export interface Page<T> { items: T[]; total: number; page: number; size: number }
export interface UserCreatePayload { username: string; password: string; email?: string; role: string }
export interface UserUpdatePayload {
  email?: string | null
  role?: string
  is_active?: boolean
  password?: string
  /** 重置密码时要求用户下次登录改密 */
  must_change_password?: boolean
}

/**
 * 用户列表。
 * @param includeBinding 为 true 时每行附 dingtalk_binding（钉钉姓名 / dt_userid / 绑定时间）
 */
export function getUsers(page = 1, size = 20, includeBinding = true) {
  return request.get<unknown, Page<UserInfo>>('/users', {
    params: { page, size, include_binding: includeBinding },
  })
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
/** 解绑钉钉身份（保留本地用户）；最后一名 super_admin 后端返回 409 */
export function unbindDingtalk(id: string) {
  return request.delete<unknown, { ok: boolean }>(`/users/${id}/dingtalk-binding`)
}
