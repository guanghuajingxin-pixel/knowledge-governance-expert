import request from './request'
import type { KnowledgeBase, KbCreateRequest, Directory, KbType } from '@/types/knowledge-base'
import type { PageQuery, PageResult } from '@/types/api'

export interface KbListParams extends PageQuery {
  kb_type?: KbType
  search?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

export function listKnowledgeBases(params?: KbListParams) {
  return request.get<unknown, PageResult<KnowledgeBase>>('/knowledge-bases', { params })
}

export function getKnowledgeBase(id: string) {
  return request.get<unknown, KnowledgeBase>(`/knowledge-bases/${id}`)
}

export function createKnowledgeBase(data: KbCreateRequest) {
  return request.post<unknown, KnowledgeBase>('/knowledge-bases', data)
}

export function updateKnowledgeBase(id: string, data: Partial<KbCreateRequest>) {
  return request.put<unknown, KnowledgeBase>(`/knowledge-bases/${id}`, data)
}

export function deleteKnowledgeBase(id: string) {
  return request.delete<unknown, void>(`/knowledge-bases/${id}`)
}

export function getDirectoryTree(kbId: string) {
  return request.get<unknown, Directory[]>(`/knowledge-bases/${kbId}/directories`)
}

export function createDirectory(kbId: string, data: { name: string; parent_id: string | null }) {
  return request.post<unknown, Directory>(`/knowledge-bases/${kbId}/directories`, data)
}

export function updateDirectory(id: string, data: { name?: string; parent_id?: string | null }) {
  return request.put<unknown, Directory>(`/directories/${id}`, data)
}

export function deleteDirectory(id: string) {
  return request.delete<unknown, void>(`/directories/${id}`)
}
