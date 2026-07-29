import request from './request'

export interface SettingItem {
  label: string
  value: string
  is_set: boolean
  is_secret: boolean
}

export type SettingsResponse = Record<string, SettingItem>

export const getSettings = () => request.get<unknown, SettingsResponse>('/settings')

export const setSetting = (data: { key: string; value: string }) =>
  request.put<unknown, { ok: boolean }>('/settings', data)
