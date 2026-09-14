import request from './request'

// 检索返回脱敏策略控制台：条件 → 识别 → 动作 → 执行节点 → 兜底 → 审计。
// 管理「检索返回策略」而非数据本身：送LLM前脱敏（底线）+ 输出后二次过滤；
// 仅 super_admin / admin 可见可管（数据安全要求）。

export type EntityType = 'phone' | 'id_card' | 'bank_card' | 'email' | 'custom'
export type MaskAction = 'partial' | 'generalize' | 'replace' | 'hash' | 'truncate' | 'reject'
export type ScopeType = 'global' | 'library' | 'kb'
export type FailureStrategy = 'block' | 'non_sensitive' | 'deny'
export type MaskScene = 'search' | 'chat'

export interface RegexRule {
  pattern: string
  label?: string
  entity_type?: EntityType
}

export interface ContextRule {
  keyword: string
  entity_type: EntityType
}

export interface MaskingPolicy {
  id: number
  name: string
  description: string
  scope_type: ScopeType
  scope_id: string
  priority: number
  user_roles: string[]
  scenes: MaskScene[]
  regex_rules: RegexRule[]
  dict_types: EntityType[]
  context_rules: ContextRule[]
  actions: Partial<Record<EntityType, MaskAction>>
  pre_llm_enabled: boolean
  post_output_enabled: boolean
  failure_strategy: FailureStrategy
  enabled: boolean
  created_by: string
  created_at: string
  updated_at: string
}

export interface MaskingPolicyPayload {
  name: string
  description?: string
  scope_type?: ScopeType
  scope_id?: string
  priority?: number
  user_roles?: string[]
  scenes?: MaskScene[]
  regex_rules?: RegexRule[]
  dict_types?: EntityType[]
  context_rules?: ContextRule[]
  actions?: Partial<Record<EntityType, MaskAction>>
  pre_llm_enabled?: boolean
  post_output_enabled?: boolean
  failure_strategy?: FailureStrategy
  enabled?: boolean
}

export interface MaskingExemption {
  id: number
  user_id: string
  scope_type: ScopeType
  scope_id: string
  entity_types: EntityType[]
  reason: string
  granted_by: string
  expires_at: string | null
  created_at: string
  username: string
}

export interface MaskingExemptionPayload {
  user_id: string
  scope_type?: ScopeType
  scope_id?: string
  entity_types?: EntityType[]
  reason?: string
  expires_at?: string | null
}

export interface RuleHit {
  rule: string
  entity_type: EntityType
  count: number
}

export interface MaskingLog {
  id: number
  username: string
  scene: MaskScene | 'sandbox'
  node: 'pre_llm' | 'post_output'
  query: string
  policy_ids: number[]
  rule_hits: RuleHit[]
  masked_count: number
  blocked: boolean
  exempted: boolean
  created_at: string
}

export interface MaskingGlobal {
  enabled: boolean
  pre_llm: boolean
  post_output: boolean
  failure_strategy: FailureStrategy
  hint: string
}

export interface SandboxHit {
  content: string
  document_title: string
  score?: number
  source?: string
}

export interface SandboxDetail {
  index: number
  title: string
  hits: RuleHit[]
  rejected: boolean
}

export interface SandboxResult {
  global_enabled: boolean
  pre_llm_enabled: boolean
  policies_applied: string[]
  masking_active: boolean
  raw: SandboxHit[]
  masked: SandboxHit[]
  detail: SandboxDetail[]
  summary: RuleHit[]
  masked_count: number
  exempted_types: string[]
  note?: string
  local_error?: string
  dify_error?: string
  ragflow_error?: string
}

// ===== 策略 =====
export const listMaskingPolicies = () =>
  request.get<unknown, MaskingPolicy[]>('/masking-policies')

export const createMaskingPolicy = (data: MaskingPolicyPayload) =>
  request.post<unknown, MaskingPolicy>('/masking-policies', data)

export const updateMaskingPolicy = (id: number, data: MaskingPolicyPayload) =>
  request.put<unknown, MaskingPolicy>(`/masking-policies/${id}`, data)

export const deleteMaskingPolicy = (id: number) =>
  request.delete<unknown, { deleted: boolean }>(`/masking-policies/${id}`)

// ===== 豁免 =====
export const listMaskingExemptions = () =>
  request.get<unknown, MaskingExemption[]>('/masking-exemptions')

export const createMaskingExemption = (data: MaskingExemptionPayload) =>
  request.post<unknown, MaskingExemption>('/masking-exemptions', data)

export const deleteMaskingExemption = (id: number) =>
  request.delete<unknown, { deleted: boolean }>(`/masking-exemptions/${id}`)

// ===== 审计日志 =====
export const listMaskingLogs = (params?: { scene?: string; node?: string; page?: number; page_size?: number }) =>
  request.get<unknown, { total: number; items: MaskingLog[] }>('/masking-logs', { params })

// ===== 全局策略 =====
export const getMaskingGlobal = () =>
  request.get<unknown, MaskingGlobal>('/masking-global')

export const putMaskingGlobal = (data: Partial<MaskingGlobal>) =>
  request.put<unknown, MaskingGlobal>('/masking-global', data)

// ===== 预览沙箱 =====
export const maskingSandbox = (data: {
  query: string
  kb_ids?: string[]
  library_ids?: number[]
  mock_role?: string
  scene?: MaskScene
  top_k?: number
}) =>
  request.post<unknown, SandboxResult>('/masking/sandbox', data)
