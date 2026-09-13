import request from './request'

export interface DifyDataset {
  id: string
  name: string
  description: string
  document_count: number
  word_count: number
}

export interface DifyDatasetsResponse {
  items: DifyDataset[]
  error?: string
}

export const listDifyDatasets = () =>
  request.get<unknown, DifyDatasetsResponse>('/dify/datasets')

export const createDifyDataset = (name: string) =>
  request.post<unknown, { id: string; name: string }>('/dify/datasets', { name })

export interface DifyUploadResult {
  document_id: string
  name: string
  batch?: string
}

export const uploadDifyDocument = (datasetId: string, file: File, pipelineInputs?: Record<string, unknown>) => {
  const fd = new FormData()
  fd.append('file', file)
  if (pipelineInputs && Object.keys(pipelineInputs).length) {
    fd.append('pipeline_inputs', JSON.stringify(pipelineInputs))
  }
  return request.post<unknown, DifyUploadResult>(`/dify/datasets/${datasetId}/documents`, fd, {
    // 流水线数据集走 pipeline/run 阻塞模式（含解析+分段+索引），单个文档可能耗时数分钟
    timeout: 600000,
  })
}

/** 拉取当前 Dify ETL 类型及其支持的文档扩展名白名单 */
export const listSupportedExtensions = (datasetId?: string) =>
  request.get<unknown, { etl_type: string; extensions: string[]; max_upload_bytes: number }>('/dify/supported-extensions', { params: { dataset_id: datasetId || undefined } })

export const syncDingTalkFile = (datasetId: string, data: { node_id: string; name: string; size?: number; pipeline_inputs?: Record<string, unknown> }) =>
  request.post<unknown, DifyUploadResult>(`/dify/datasets/${datasetId}/sync-dingtalk`, data, {
    timeout: 600000,
  })
