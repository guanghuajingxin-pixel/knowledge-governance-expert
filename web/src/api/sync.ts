// 钉钉知识库 → Dify 定时增量同步：API 封装（前缀 /api/v1/sync）
import request from './request'
import type {
  Failure, Log, PreviewItem, Run, RunDetail, Source, SourcePayload, SourceStats,
  TreeNode, TreeNodeLite, Workspace,
} from '@/types/sync'

const BASE = '/sync'

// ---------- 钉钉目录 ----------
export const listWorkspaces = () =>
  request.get<unknown, Workspace[]>(`${BASE}/dingtalk/workspaces`)

export const buildTree = (rootNodeId: string, depth = 5) =>
  request.get<unknown, TreeNode[]>(`${BASE}/dingtalk/tree`, { params: { root_node_id: rootNodeId, depth } })

export const listNodes = (parentNodeId: string) =>
  request.get<unknown, TreeNodeLite[]>(`${BASE}/dingtalk/nodes`, { params: { parent_node_id: parentNodeId } })

// ---------- 同步源 ----------
export const listSources = () => request.get<unknown, Source[]>(`${BASE}/sources`)

export const createSource = (payload: SourcePayload) =>
  request.post<unknown, Source>(`${BASE}/sources`, payload)

export const updateSource = (id: number, payload: Partial<SourcePayload>) =>
  request.put<unknown, Source>(`${BASE}/sources/${id}`, payload)

export const deleteSource = (id: number) => request.delete(`${BASE}/sources/${id}`)

export const testSource = (id: number) => request.post(`${BASE}/sources/${id}/test`)

export const testSourceDraft = (payload: SourcePayload) =>
  request.post(`${BASE}/sources/test`, payload)

export const syncSource = (id: number) => request.post(`${BASE}/sources/${id}/sync`)

export const previewSource = (id: number) =>
  request.post<unknown, PreviewItem[]>(`${BASE}/sources/${id}/preview`)

export const updatePreviewSettings = (id: number, items: Array<{ node_id: string; name?: string; category?: string; enabled: boolean }>) =>
  request.put(`${BASE}/sources/${id}/preview-settings`, { items })

export const sourceStats = (id: number) =>
  request.get<unknown, SourceStats>(`${BASE}/sources/${id}/stats`)

// ---------- 运行记录 / 失败 / 日志 ----------
export const listRuns = (params?: { source_id?: number; limit?: number; offset?: number }) =>
  request.get<unknown, Run[]>(`${BASE}/runs`, { params })

export const getRun = (id: number) =>
  request.get<unknown, RunDetail>(`${BASE}/runs/${id}`)

export const listFailures = (params?: { source_id?: number; run_id?: number; limit?: number; offset?: number }) =>
  request.get<unknown, Failure[]>(`${BASE}/failures`, { params })

export const listLogs = (params?: { run_id?: number; level?: string; limit?: number; offset?: number }) =>
  request.get<unknown, Log[]>(`${BASE}/logs`, { params })

export const retryFailure = (id: number) => request.post(`${BASE}/failures/${id}/retry`)

export const retryAllFailures = () => request.post(`${BASE}/failures/retry-all`)
