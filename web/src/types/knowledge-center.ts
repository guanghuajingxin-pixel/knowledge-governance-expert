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
  uploader_id: string | null
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
  uploader_id?: string
  page?: number
  size?: number
}

/** 创建人选项 */
export interface UploaderOption {
  id: string
  name: string
}

/** 钉钉知识库文件（实时拉取自钉钉开放平台） */
export interface DingTalkFile {
  node_id: string
  workspace_id: string
  workspace_name: string
  name: string
  /** 上级目录路径，多层目录用 / 分隔，根目录为 "/" */
  directory_path: string
  category: string | null
  extension: string | null
  size: number
  url: string | null
  creator_id: string
  creator_name: string | null
  created_at: string | null
  modified_at: string | null
}

/** 钉钉知识库 / 创建人选项 */
export interface DingTalkOption {
  id: string
  name: string
}

/** 钉钉团队知识库（实时列表，含根节点 ID） */
export interface DingTalkWorkspace {
  id: string
  name: string
  root_node_id: string
}

/** 钉钉目录子节点（实时，按父节点查询） */
export interface DingTalkNode {
  node_id: string
  name: string
  is_folder: boolean
  has_children: boolean
  extension: string | null
  size: number
  url: string | null
  creator_id: string
  created_at: string | null
  modified_at: string | null
}

/** 钉钉文件列表查询结果 */
export interface DingTalkDocResult {
  items: DingTalkFile[]
  total: number
  page: number
  size: number
  workspaces: DingTalkOption[]
  creators: DingTalkOption[]
  /** 后台正在遍历钉钉知识库时为 true（前端轮询） */
  loading?: boolean
  error?: string | null
}

/** 知识源登记（企业知识库注册表） */
export interface KnowledgeSource {
  id: number
  name: string
  source_type: 'dingtalk_workspace' | 'dify_dataset' | 'business_system'
  external_id: string
  description: string
  config: Record<string, any> | null
  enabled: boolean
  created_at: string
  updated_at: string
}

/** 知识源创建/更新参数 */
export interface KnowledgeSourcePayload {
  name: string
  source_type: KnowledgeSource['source_type']
  external_id: string
  description?: string
  config?: Record<string, any> | null
  enabled?: boolean
}
