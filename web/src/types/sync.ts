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
  dify_dataset_name: string
  dify_dataset_id: string | null
  delete_policy: 'keep' | 'sync'
  cron: string
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
  cron: string
  enabled: boolean
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
