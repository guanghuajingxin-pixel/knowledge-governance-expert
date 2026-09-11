import request from './request'

// 文档加工项
export interface ProcessedDocumentItem {
  document_id: string
  name: string
  word_count: number
  status: string
  process_status: string // pending|processing|completed|failed
  tags: string[]
  summary: string
  doc_type: string
  processed_at: string | null
}

export interface ProcessedDocumentsResponse {
  items: ProcessedDocumentItem[]
}

// 单文档加工详情
export interface ProcessedDocumentDetail {
  exists: boolean
  document_id: string
  dataset_id: string
  name: string
  tags: string[]
  summary: string
  keywords: string[]
  doc_type: string
  process_status: string
  error_message: string
  updated_at: string | null
}

// 增强结果
export interface EnhanceResult {
  status: string
  document_id: string
  name: string
  tags: string[]
  summary: string
  keywords: string[]
  doc_type: string
}

// 知识关系
export interface KnowledgeRelationItem {
  target_doc_id: string
  target_name: string
  relation_type: string
  weight: number
  description: string
}

// 知识图谱
export interface KnowledgeGraphNode {
  id: string
  name: string
  tags: string[]
  doc_type: string
}

export interface KnowledgeGraphEdge {
  source: string
  target: string
  relation_type: string
  weight: number
  description: string
}

export interface KnowledgeGraph {
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
}

// 标签
export interface KnowledgeTag {
  id: string
  name: string
  color: string
  count: number
}

// 上下文扩展
export interface ContextExpansion {
  summaries: {
    document_id: string
    name: string
    summary: string
    tags: string[]
    doc_type: string
  }[]
  related: {
    document_id: string
    name: string
    relation_type: string
    weight: number
    description: string
    summary: string
    tags: string[]
  }[]
  tags: string[]
}

// 统计
export interface ProcessStats {
  total_documents: number
  completed: number
  failed: number
  relations: number
  tags: number
}

// ============ API ============

export const listProcessedDocuments = (datasetId: string) =>
  request.get<unknown, ProcessedDocumentsResponse>(`/process/datasets/${datasetId}/documents`)

export const getProcessedDocument = (documentId: string) =>
  request.get<unknown, ProcessedDocumentDetail>(`/process/documents/${documentId}`)

export const enhanceDocument = (datasetId: string, documentId: string) =>
  request.post<unknown, EnhanceResult>(`/process/datasets/${datasetId}/documents/${documentId}/enhance`)

export const enhanceAllDocuments = (datasetId: string) =>
  request.post<unknown, { total: number; completed: number; failed: number; results: any[] }>(
    `/process/datasets/${datasetId}/enhance-all`,
  )

export const buildRelations = (datasetId: string) =>
  request.post<unknown, { status: string; created: number; doc_count?: number; reason?: string }>(
    `/process/datasets/${datasetId}/build-relations`,
  )

export const getDocumentRelations = (documentId: string) =>
  request.get<unknown, { items: KnowledgeRelationItem[] }>(`/process/documents/${documentId}/relations`)

export const getKnowledgeGraph = (datasetId: string) =>
  request.get<unknown, KnowledgeGraph>(`/process/datasets/${datasetId}/graph`)

export const expandContext = (documentIds: string[], query: string, maxRelated = 3) =>
  request.get<unknown, ContextExpansion>('/process/context/expand', {
    params: { document_ids: documentIds.join(','), query, max_related: maxRelated },
  })

export const listKnowledgeTags = () =>
  request.get<unknown, { items: KnowledgeTag[] }>('/process/tags')

export const getProcessStats = () =>
  request.get<unknown, ProcessStats>('/process/stats')
