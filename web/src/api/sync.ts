// 钉钉知识库 → Dify 定时增量同步：API 封装（前缀 /api/v1/sync）
import request from './request'
import type {
  Failure, Log, PipelineVariablesResponse, PreviewItem, Run, RunDetail, Source, SourcePayload, SourceStats,
  TaskListResponse, TaskQuery, TreeNode, TreeNodeLite, Workspace,
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

// 预演需后端遍历钉钉目录树（服务端 10 分钟缓存，命中秒回）；
// 首次/强制刷新需完整遍历，大库可能超过全局 30s 超时——单独放宽为 10 分钟。
export const previewSource = (id: number, refresh = false) =>
  request.post<unknown, PreviewItem[]>(`${BASE}/sources/${id}/preview`, undefined,
    { timeout: 10 * 60 * 1000, params: refresh ? { refresh: true } : undefined })

export const updatePreviewSettings = (id: number, items: Array<{ node_id: string; name?: string; category?: string; enabled: boolean }>) =>
  request.put(`${BASE}/sources/${id}/preview-settings`, { items })

export const sourceStats = (id: number) =>
  request.get<unknown, SourceStats>(`${BASE}/sources/${id}/stats`)

/** 批量版：一次拿回所有同步源的文档数与最近一次运行。
 *  列表页必须用这个——原先逐源并发请求 sourceStats（N 个源 N 个请求，
 *  有任务运行时每 3 秒重复一轮），是把后端连接池打满、整站点击卡顿的主因之一。 */
export interface SourceStatsItem extends SourceStats {
  source_id: number
}

export const sourcesStatsAll = () =>
  request.get<unknown, { items: SourceStatsItem[] }>(`${BASE}/sources/stats`)

/** 拉取流水线数据集的 input form 变量 schema（分段参数定义），用于自动生成配置表单 */
export const listPipelineVariables = (datasetId: string) =>
  request.get<unknown, PipelineVariablesResponse>(`${BASE}/pipeline-variables`, { params: { dataset_id: datasetId } })

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

export const importPipelineSchema = (datasetId: string, file: File) => {
  const data = new FormData()
  data.append('file', file)
  return request.post<unknown, PipelineVariablesResponse>(`${BASE}/pipeline-schema`, data, { params: { dataset_id: datasetId } })
}

// ---------- 同步队列：逐文档任务 ----------
export const listTasks = (params: TaskQuery) =>
  request.get<unknown, TaskListResponse>(`${BASE}/tasks`, { params })

export const retryTask = (id: number) => request.post(`${BASE}/tasks/${id}/retry`)

export const batchRetryTasks = (ids: number[]) =>
  request.post<unknown, { ok: boolean; submitted: number; skipped: number; message: string }>(`${BASE}/tasks/batch-retry`, { ids })

export const batchDeleteTasks = (ids: number[]) =>
  request.post<unknown, { ok: boolean; deleted: number; message: string }>(`${BASE}/tasks/batch-delete`, { ids })
