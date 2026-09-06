import request from './request'

/** 治理标准：钉钉 AI 多维表《杰克知识管理规范》记录 */
export interface StandardDoc {
  record_id: string
  doc_type: string
  code: string
  version: string
  status: string
  effective_date: string
  link: string
  maintainer: string
}

export interface StandardsResponse {
  items: StandardDoc[]
  total: number
  error?: string | null
  fetched_at?: string
}

export const getStandards = () =>
  request.get<unknown, StandardsResponse>('/governance/standards')
