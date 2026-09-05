/**
 * 知识中心类型定义
 */
import type { DocStatus } from './document'

/** 知识中心文档（跨知识库聚合视图） */
export interface KnowledgeCenterDocument {
  id: string
  kb_id: string
  kb_name: string
  kb_type: string
  directory_id: string | null
  directory_name: string | null
  original_filename: string
  file_type: string
  file_size: number
  status: DocStatus | 'ACTIVE' | 'DELETED'
  chunk_count: number
  uploader_name: string | null
  created_at: string
  updated_at: string
}

/** 知识中心统一目录树节点 */
export interface KcDirectoryNode {
  id: string
  kb_id: string
  parent_id: string | null
  name: string
  sort_order: number
  document_count: number
  children?: KcDirectoryNode[]
}

/** 知识中心知识库树（顶层节点） */
export interface KbTreeNode {
  kb_id: string
  kb_name: string
  kb_type: string
  document_count: number
  children: KcDirectoryNode[]
}

/** 回收站条目 */
export interface TrashItem {
  id: string
  original_filename: string
  directory_name: string | null
  kb_name: string
  operator_name: string
  deleted_at: string
  remaining_days: number
}

/** 任务队列统计 */
export interface TaskQueueStats {
  total: number
  executing: number
  completed: number
  failed: number
}

/** 文档查询参数 */
export interface KcDocumentQuery {
  kb_id?: string
  directory_id?: string
  search?: string
  date_from?: string
  date_to?: string
  status?: string
  page?: number
  size?: number
}
