// 钉钉知识库 → Dify 定时增量同步：类型定义

export interface Workspace {
  workspaceId: string
  rootNodeId: string
  name: string
  [key: string]: any
}

export interface TreeNodeLite {
  nodeId: string
  name: string
  category: string
  hasChildren: boolean
}

export interface TreeNode {
  nodeId: string
  name: string
  category: string
  hasChildren: boolean
  children: TreeNode[]
}

export interface Source {
  id: number
  name: string
  workspace_id: string
  root_node_id: string
  start_dir: string
  /** 目标引擎：dify | ragflow */
  backend_type: 'dify' | 'ragflow'
  dify_dataset_name: string
  dify_dataset_id: string | null
  delete_policy: 'keep' | 'sync'
  cron: string
  enabled: boolean
  /** 流水线数据集的 input form 变量值（分段参数），如 {max_chunk_length: 1024} */
  pipeline_inputs: Record<string, any>
  created_at: string
  updated_at: string
}

export interface SourcePayload {
  dify_dataset_id?: string | null
  name: string
  workspace_id: string
  root_node_id: string
  start_dir?: string
  /** 目标引擎：dify | ragflow */
  backend_type?: 'dify' | 'ragflow'
  dify_dataset_name: string
  delete_policy: 'keep' | 'sync'
  cron: string
  enabled: boolean
  pipeline_inputs: Record<string, any>
}

/** Dify 流水线 input form 单个变量的 schema（来自 workflows.rag_pipeline_variables） */
export interface PipelineVariable {
  variable: string
  label: string
  type: 'number' | 'text-input' | 'select' | 'checkbox' | string
  required: boolean
  default_value: unknown
  options: string[]
  unit: string
  tooltips: string
}

export interface PipelineVariablesResponse {
  runtime_mode: string
  schema_source: string
  /** dify_db_url 是否已配置；false 时前端降级为 JSON 编辑器 */
  configured: boolean
  variables: PipelineVariable[]
}

export interface Run {
  id: number
  source_id: number
  trigger: 'manual' | 'schedule'
  status: 'running' | 'success' | 'partial' | 'failed'
  started_at: string
  finished_at: string | null
  total: number
  created_count: number
  updated_count: number
  deleted_count: number
  failed_count: number
  message: string
}

export interface Failure {
  id: number
  run_id: number
  source_id: number
  node_id: string | null
  name: string
  error: string
  created_at: string
}

export interface Log {
  id: number
  run_id: number | null
  level: string
  message: string
  created_at: string
}

export interface RunDetail {
  run: Run
  failures: Failure[]
  logs: Log[]
}

export interface PreviewItem {
  node_id?: string
  name?: string
  category?: string
  enabled?: boolean
  action: '新增' | '更新' | '删除' | '跳过'
  doc: string
  note: string
}

export interface SourceStats {
  doc_count: number | null
  last_run: Run | null
}
