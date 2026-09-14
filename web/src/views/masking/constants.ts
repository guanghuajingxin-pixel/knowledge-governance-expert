/**
 * 脱敏策略控制台共享常量：实体类型 / 脱敏动作 / 角色 / 场景 / 失败策略 的文案与选项。
 */
import type { EntityType, MaskAction, FailureStrategy } from '@/api/masking'

export const ENTITY_TYPES: EntityType[] = ['phone', 'id_card', 'bank_card', 'email', 'custom']

export const ENTITY_LABEL: Record<EntityType, string> = {
  phone: '手机号',
  id_card: '身份证',
  bank_card: '银行卡',
  email: '邮箱',
  custom: '敏感信息',
}

export const ENTITY_TAG: Record<EntityType, 'warning' | 'danger' | 'success' | 'info'> = {
  phone: 'warning',
  id_card: 'danger',
  bank_card: 'danger',
  email: 'success',
  custom: 'info',
}

export const ACTIONS: MaskAction[] = ['partial', 'generalize', 'replace', 'hash', 'truncate', 'reject']

export const ACTION_LABEL: Record<MaskAction, string> = {
  partial: '部分遮蔽',
  generalize: '泛化',
  replace: '替换',
  hash: '哈希',
  truncate: '截断',
  reject: '拒绝返回',
}

export const ACTION_EXAMPLE: Record<MaskAction, string> = {
  partial: '138****5678',
  generalize: '20k-30k',
  replace: '某客户',
  hash: 'a3f5…（可关联不暴露原文）',
  truncate: '仅保留前几位',
  reject: '命中片段不进入返回',
}

export const ROLE_OPTIONS = [
  { value: 'super_admin', label: '超级管理员' },
  { value: 'admin', label: '管理员' },
  { value: 'editor', label: '编辑者' },
  { value: 'viewer', label: '查看者' },
]

export const ROLE_LABEL: Record<string, string> = Object.fromEntries(
  ROLE_OPTIONS.map((r) => [r.value, r.label]),
)

export const SCENE_OPTIONS = [
  { value: 'search', label: '统一检索' },
  { value: 'chat', label: 'RAG 问答' },
]

export const SCENE_LABEL: Record<string, string> = Object.fromEntries(
  SCENE_OPTIONS.map((s) => [s.value, s.label]),
)

export const FAILURE_OPTIONS: { value: FailureStrategy; label: string; tip: string }[] = [
  { value: 'non_sensitive', label: '仅返回非敏感片段', tip: '脱敏引擎异常时丢弃无法确认安全的片段' },
  { value: 'block', label: '阻断返回', tip: '脱敏引擎异常时整次返回空结果' },
  { value: 'deny', label: '提示无权限', tip: '脱敏引擎异常时向用户返回无权限提示' },
]

export const FAILURE_LABEL: Record<string, string> = Object.fromEntries(
  FAILURE_OPTIONS.map((f) => [f.value, f.label]),
)

export const NODE_LABEL: Record<string, string> = {
  pre_llm: '送LLM前',
  post_output: '输出后过滤',
}

export const SCOPE_LABEL: Record<string, string> = {
  global: '全局',
  library: '知识库镜像',
  kb: '本地知识库',
}
