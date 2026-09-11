export type SearchType = 'hybrid' | 'semantic' | 'keyword' | 'faq'
export type SourceType = 'DOCUMENT' | 'FAQ'

export interface SearchRequest {
  query: string
  kb_ids: string[]
  top_k?: number
  search_type?: SearchType
  filters?: {
    directory_ids?: string[]
    file_types?: string[]
  }
}

export interface SearchResult {
  citation_id?: number
  evidence_id?: string
  source?: string
  quote?: string
  partial?: boolean
  chunk_id: string
  text: string
  score: number
  source_type: SourceType
  document_id: string
  document_title: string
  page_number: number | null
  total_chunks: number
  directory_path: string
  source_path: string
  preview_url: string
  preview_type: string
  content_hash: string
  faq_answer: string | null
  /** 钉钉文档等外链引用的可跳转 URL（会话历史恢复/纠错跳转用） */
  url?: string
  node_id?: string
  extension?: string
}

export interface SearchResponse {
  results: SearchResult[]
  total: number
  took_ms: number
}
