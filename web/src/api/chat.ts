import request from './request'
import type { SearchResult } from '@/types/search'

export interface ChatRequest {
  query: string
  kb_ids: string[]
  top_k?: number
}

export interface ChatResponse {
  answer: string
  citations: SearchResult[]
}

export const chat = (data: ChatRequest) =>
  request.post<unknown, ChatResponse>('/search/chat', data)
