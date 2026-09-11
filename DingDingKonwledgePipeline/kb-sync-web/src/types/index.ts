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
  dify_dataset_name: string
  dify_dataset_id: string | null
  delete_policy: 'keep' | 'sync'
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface SourcePayload {
  name: string
  workspace_id: string
  root_node_id: string
  start_dir?: string
  dify_dataset_name: string
  delete_policy: 'keep' | 'sync'
  enabled: boolean
}

export interface Job {
  id: number
  name: string
  source_id: number | null
  cron: string
  description: string
  enabled: boolean
  last_run_at: string | null
  next_run_at: string | null
  created_at: string
  updated_at: string
}

export interface JobPayload {
  name: string
  source_id: number | null
  cron: string
  description?: string
  enabled: boolean
}

export interface Run {
  id: number
  job_id: number | null
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

export interface Settings {
  dingtalk_webhook: string
  alert_failure_threshold: number
  default_delete_policy: 'keep' | 'sync'
  export_format: 'markdown' | 'docx' | 'pdf'
  max_depth: number
  dify_wait_indexing: boolean
  dingtalk_operator_id: string
}

export interface Dashboard {
  source_count: number
  job_count: number
  enabled_job_count: number
  doc_count: number
  run_count_today: number
  failed_today: number
  last_run: Run | null
}

export interface RunDetail {
  run: Run
  failures: Failure[]
  logs: Log[]
}

export interface PreviewItem {
  action: '新增' | '更新' | '删除' | '跳过'
  doc: string
  note: string
}

export interface SourceStats {
  doc_count: number
  last_run: Run | null
}
