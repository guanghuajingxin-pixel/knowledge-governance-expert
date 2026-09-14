import request from './request'

// 敏感信息管理：知识应用侧的敏感内容登记（内容/类型/状态），
// 供问答与检索链路脱敏管控；仅 super_admin / admin 可见可管。

export type SensitiveType = 'phone' | 'id_card' | 'bank_card' | 'email' | 'custom'

export interface SensitiveItem {
  id: number
  content: string
  type: SensitiveType
  description: string
  enabled: boolean
  created_by: string
  created_at: string
}

export interface SensitiveItemCreate {
  content: string
  type: SensitiveType
  description?: string
  enabled?: boolean
}

export interface SensitiveItemUpdate {
  content?: string
  type?: SensitiveType
  description?: string
  enabled?: boolean
}

export const listSensitiveItems = (params?: { type?: string; keyword?: string }) =>
  request.get<unknown, SensitiveItem[]>('/sensitive-items', { params })

export const createSensitiveItem = (data: SensitiveItemCreate) =>
  request.post<unknown, SensitiveItem>('/sensitive-items', data)

export const updateSensitiveItem = (id: number, data: SensitiveItemUpdate) =>
  request.put<unknown, SensitiveItem>(`/sensitive-items/${id}`, data)

export const deleteSensitiveItem = (id: number) =>
  request.delete<unknown, { ok: boolean }>(`/sensitive-items/${id}`)
