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

export interface TestLLMResult {
  ok: boolean
  latency_ms?: number
  model?: string
  reply?: string
  message?: string
}

export const testLLM = (data: { base_url?: string; api_key?: string; model?: string; profile_id?: string }) =>
  request.post<unknown, TestLLMResult>('/settings/test-llm', data)

export interface LlmModelsResult {
  ok: boolean
  models: string[]
  message?: string
}

export const listLlmModels = (params: { base_url?: string; api_key?: string }) =>
  request.get<unknown, LlmModelsResult>('/settings/llm-models', { params })

// ============ Dify 多配置 ============

export interface DifyProfile {
  id: string
  name: string
  base_url: string
  api_key: string
  dataset_ids: string
  enabled: boolean
  created_at: string | null
}

export const listDifyProfiles = () =>
  request.get<unknown, DifyProfile[]>('/settings/dify-profiles')

export const createDifyProfile = (data: Omit<DifyProfile, 'id' | 'enabled' | 'created_at'>) =>
  request.post<unknown, DifyProfile>('/settings/dify-profiles', data)

export const updateDifyProfile = (id: string, data: Omit<DifyProfile, 'id' | 'enabled' | 'created_at'>) =>
  request.put<unknown, DifyProfile>(`/settings/dify-profiles/${id}`, data)

export const deleteDifyProfile = (id: string) =>
  request.delete<unknown, void>(`/settings/dify-profiles/${id}`)

export const enableDifyProfile = (id: string) =>
  request.put<unknown, { ok: boolean }>(`/settings/dify-profiles/${id}/enable`)

// ============ LLM 供应商配置（多供应商 × 多模型） ============

export interface LlmModelEntry {
  name: string
  enabled: boolean
  is_default: boolean
}

export interface LlmProfile {
  id: string
  name: string
  provider: string
  base_url: string
  api_key: string          // 脱敏回显
  has_key: boolean
  models: LlmModelEntry[]
  created_at: string | null
}

export interface EnabledLlmModel {
  profile_id: string
  profile_name: string
  provider: string
  model: string
  is_default: boolean
}

export const listLlmProfiles = () =>
  request.get<unknown, LlmProfile[]>('/settings/llm-profiles')

export const createLlmProfile = (data: {
  name: string; provider: string; base_url: string; api_key: string; models: LlmModelEntry[]
}) => request.post<unknown, { ok: boolean; id: string }>('/settings/llm-profiles', data)

export const updateLlmProfile = (id: string, data: {
  name: string; provider: string; base_url: string; api_key: string; models: LlmModelEntry[]
}) => request.put<unknown, { ok: boolean }>(`/settings/llm-profiles/${id}`, data)

export const deleteLlmProfile = (id: string) =>
  request.delete<unknown, void>(`/settings/llm-profiles/${id}`)

export const refreshLlmProfileModels = (id: string) =>
  request.post<unknown, { ok: boolean; models: LlmModelEntry[] }>(`/settings/llm-profiles/${id}/refresh-models`)

export const listEnabledLlmModels = () =>
  request.get<unknown, { models: EnabledLlmModel[] }>('/settings/llm-enabled-models')

export interface TestDingtalkResult {
  ok: boolean
  latency_ms?: number
  workspace_count?: number
  message?: string
}

export const testDingtalk = (data: { app_key?: string; app_secret?: string; operator_union_id?: string }) =>
  request.post<unknown, TestDingtalkResult>('/settings/test-dingtalk', data)

export interface TestDifyResult {
  ok: boolean
  latency_ms?: number
  message?: string
}

export const testDify = (data: { base_url?: string; api_key?: string; profile_id?: string }) =>
  request.post<unknown, TestDifyResult>('/settings/test-dify', data)

export interface TestMinerUResult {
  ok: boolean
  latency_ms?: number
  message?: string
}

export const testMineru = (data: { api_key?: string }) =>
  request.post<unknown, TestMinerUResult>('/settings/test-mineru', data)
