import request from './request'
import type { SearchRequest, SearchResponse } from '@/types/search'

export function search(data: SearchRequest) {
  return request.post<unknown, SearchResponse>('/search', data)
}

export function getTrace(chunkId: string) {
  return request.get<unknown, unknown>(`/search/trace/${chunkId}`)
}

// ===== 检索测试（调参用，返回原始召回分数）=====

export interface SearchTestRequest {
  query: string
  kb_ids: string[]
  top_k?: number
  search_type?: 'hybrid' | 'semantic' | 'keyword'
  filters?: {
    directory_ids?: string[]
    document_ids?: string[]
    file_types?: string[]
  }
  score_threshold?: number
  rerank_model_id?: string
  rerank?: boolean
}

export interface SearchTestHit {
  semantic_weight?: number
  rerank_score?: number
  score_type?: string
  token_similarity?: number
  vector_similarity?: number
  text: string
  score: number
  document_title: string
  document_id?: string
  chunk_index?: number
}

export interface SearchTestResponse {
  k: number
  search_type: string
  rerank: boolean
  results: SearchTestHit[]
  masking?: { applied: boolean; masked_count: number; hint: string }
}

export function searchTest(data: SearchTestRequest) {
  return request.post<unknown, SearchTestResponse>('/search/test', data)
}
