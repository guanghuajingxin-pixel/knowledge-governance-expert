import request from './request'

// ============ 问答反馈（点赞/纠错/没找到） ============
export interface FeedbackPayload {
  feedback_type: 'helpful' | 'correct' | 'notfound'
  session_id?: string
  message_id?: string
  knowledge_title?: string
  knowledge_url?: string
  error_type?: string
  content?: string
  question?: string
}

export const submitFeedback = (data: FeedbackPayload) =>
  request.post<unknown, { ok: boolean; id: string; status: string }>('/qa/feedback', data)

export const ERROR_TYPES = ['内容错误', '知识重复', '知识过期', '知识难理解', '知识不完整', '知识模板错误', '其它']

// ============ 问答明细 ============
export interface QaStep {
  title?: string
  detail?: string
  done?: boolean
  node?: string
}

export interface QaRetrieval {
  document_title?: string
  title?: string
  text?: string
  score?: number
  chunk_index?: number | string
  chunk_id?: string
  page_number?: number | null
  url?: string
  /** 检索来源（dify/ragflow/local/dingtalk）；旧数据无此字段 */
  source?: string
  /** 该分段是否被答案实际引用（false=仅召回未使用）；旧数据无此字段视为已引用 */
  cited?: boolean
}

export interface QaFeedbackTag {
  feedback_type: string
  error_type?: string | null
  content?: string | null
  status: string
}

export interface QaDetailItem {
  question_id: string
  message_id: string | null
  session_id: string | null
  session_title: string
  username: string
  user_id: string | null
  question: string
  answer: string
  meta: string
  asked_at: string | null
  steps: QaStep[]
  retrieval: QaRetrieval[]
  model: string
  duration_ms?: number | null
  feedbacks: QaFeedbackTag[]
}

export interface QaDetailsResponse {
  items: QaDetailItem[]
  total: number
  page: number
  page_size: number
}

export interface QaDetailQuery {
  date_from?: string
  date_to?: string
  keyword?: string
  user?: string
  feedback?: string
  page?: number
  page_size?: number
}

export const getQaDetails = (params: QaDetailQuery) =>
  request.get<unknown, QaDetailsResponse>('/qa/details', { params })

// ============ 知识纠错工单 ============
export interface CorrectionItem {
  id: string
  knowledge_title: string
  knowledge_url: string
  question: string
  error_type: string
  content: string
  status: string
  status_label: string
  applicant: string
  handler: string | null
  handler_note: string
  created_at: string | null
}

export interface CorrectionsResponse {
  items: CorrectionItem[]
  total: number
  page: number
  page_size: number
  error_types: string[]
}

export const getCorrections = (params: {
  keyword?: string
  error_type?: string
  status?: string
  page?: number
  page_size?: number
}) => request.get<unknown, CorrectionsResponse>('/qa/corrections', { params })

export const updateCorrection = (id: string, data: { status: string; handler_note?: string }) =>
  request.put<unknown, { ok: boolean; status: string }>(`/qa/corrections/${id}`, data)
