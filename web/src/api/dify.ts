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

export const uploadDifyDocument = (datasetId: string, file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return request.post<unknown, DifyUploadResult>(`/dify/datasets/${datasetId}/documents`, fd, {
    timeout: 240000,
  })
}

export const syncDingTalkFile = (datasetId: string, data: { node_id: string; name: string; size?: number }) =>
  request.post<unknown, DifyUploadResult>(`/dify/datasets/${datasetId}/sync-dingtalk`, data, {
    timeout: 600000,
  })
