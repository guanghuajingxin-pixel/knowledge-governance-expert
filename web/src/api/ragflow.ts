import request from './request'

// RAGFlow 引擎接口（对应后端 /api/v1/ragflow/*）
// 只用于「知识源管理」登记时动态拉库列表，以及系统配置页测试连接。

export interface RagflowDataset {
  id: string
  name: string
  description?: string
  document_count?: number
  chunk_count?: number
  chunk_method?: string
  embedding_model_name?: string
}

export interface RagflowDocument {
  id: string
  name: string
  run?: string
  progress?: number
  chunk_count?: number
  size?: number
}

export interface TestRagflowResult {
  ok: boolean
  message?: string
}

export const listRagflowDatasets = () =>
  request.get<unknown, { items: RagflowDataset[]; error?: string }>('/ragflow/datasets')

export const listRagflowDocuments = (datasetId: string) =>
  request.get<unknown, { items: RagflowDocument[] }>(`/ragflow/datasets/${datasetId}/documents`)

export const createRagflowDataset = (data: {
  name: string; chunk_method?: string; embedding_model?: string; parser_config?: Record<string, unknown> | null
}) => request.post<unknown, { id: string; name: string }>('/ragflow/datasets', data)

export const testRagflow = (data: { base_url?: string; api_key?: string }) =>
  request.post<unknown, TestRagflowResult>('/ragflow/test', data)
