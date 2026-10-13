/**
 * 知识库类型元数据（公共）——筛选标签、卡片图标与配色统一从这里取，
 * 避免配置页/弹窗/列表多处各画各的导致样式漂移。
 */
import { markRaw, type Component } from 'vue'
import { ChatDotRound, Document, Files } from '@element-plus/icons-vue'
import type { KnowledgeLibrary } from '@/api/knowledge-library'

export type KbTypeKey = 'document' | 'material' | 'faq'

export const KB_TYPE_META: Record<KbTypeKey, { label: string; icon: Component; color: string; bg: string }> = {
  document: { label: '文档库', icon: markRaw(Document), color: 'var(--el-color-primary)', bg: 'var(--el-color-primary-light-9)' },
  material: { label: '物料库', icon: markRaw(Files), color: '#e6a23c', bg: '#fdf6ec' },
  faq: { label: '问答库', icon: markRaw(ChatDotRound), color: '#67c23a', bg: '#f0f9eb' },
}

export function kbTypeKey(lib: KnowledgeLibrary): KbTypeKey {
  if (lib.library_type === 'material') return 'material'
  return 'document'
}

export function kbTypeMeta(lib: KnowledgeLibrary) {
  return KB_TYPE_META[kbTypeKey(lib)]
}

export function kbTypeLabel(lib: KnowledgeLibrary): string {
  return KB_TYPE_META[kbTypeKey(lib)].label
}
