import request from './request'

// 知识库（检索抽象层）：本地文档库统一注册表，供智能体检索选库与检索测试。
// 文档的导入/解析走文档库管理（api/document-library）；
// 与「知识源管理」（推送路径定义）相互独立。

export interface KnowledgeLibrary {
  id: number
  name: string
  /** 历史保留字段（外部镜像下线后本地库为空串） */
  platform: string
  dataset_id: string
  library_type: 'document' | 'material'
  description: string
  enabled: boolean
  updated_at: string
}

export interface KnowledgeLibraryUpdate {
  name?: string
  description?: string
  enabled?: boolean
}

export const listKnowledgeLibraries = (enabledOnly = false) =>
  request.get<unknown, KnowledgeLibrary[]>('/knowledge-libraries', {
    params: enabledOnly ? { enabled_only: true } : {},
  })

export const updateKnowledgeLibrary = (id: number, data: KnowledgeLibraryUpdate) =>
  request.put<unknown, KnowledgeLibrary>(`/knowledge-libraries/${id}`, data)

// ===== 检索测试：按知识库逐库执行与智能问答一致的底层检索 =====

export interface RetrievalTestHit {
  semantic_weight?: number
  score_type?: string
  token_similarity?: number
  vector_similarity?: number
  rerank_score?: number
  matched_content?: string
  retrieval_enhancements?: {
    filename?: string
    summary?: string
    questions?: string[]
    image_captions?: Array<{image: string; caption: string}>
    errors?: Record<string, string>
  }
  score: number
  content: string
  document_title: string
  document_id?: string
  dataset_id?: string
  segment_id?: string
  page_number?: number | null
  source?: string
  library_id: number
  library_name: string
}

export interface RetrievalTestLib {
  library_id: number
  name: string
  platform: string
  dataset_id: string
  enabled: boolean
  ok: boolean
  count: number
  error: string
}

export interface RetrievalTestResult {
  query: string
  top_k: number
  elapsed_ms: number
  libraries: RetrievalTestLib[]
  hits: RetrievalTestHit[]
  total: number
}

export interface RetrievalTestParams {
  document_ids?: string[]
  rerank?: boolean
  rerank_model_id?: string
  query: string
  library_ids?: number[]
  top_k?: number
  /** 检索模式：hybrid=混合检索（默认）、vector=向量检索、fulltext=全文检索 */
  mode?: 'hybrid' | 'vector' | 'fulltext'
  /** 最终相关性分数阈值 */
  similarity_threshold?: number
  /** 混合检索的向量权重 */
  vector_similarity_weight?: number
}

export const testKnowledgeRetrieval = (data: RetrievalTestParams) =>
  request.post<unknown, RetrievalTestResult>('/knowledge-libraries/retrieval-test', data)
