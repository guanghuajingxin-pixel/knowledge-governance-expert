import request from './request'
import type { SearchRequest, SearchResponse } from '@/types/search'

export function search(data: SearchRequest) {
  return request.post<unknown, SearchResponse>('/search', data)
}

export function getTrace(chunkId: string) {
  return request.get<unknown, unknown>(`/search/trace/${chunkId}`)
}
