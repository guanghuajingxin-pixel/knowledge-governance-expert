import request from './request'
import type { FaqEntry, FaqEntryCreateRequest } from '@/types/faq'
import type { PageQuery, PageResult } from '@/types/api'

export function listFaqEntries(kbId: string, params?: PageQuery & { status?: string; keyword?: string }) {
  return request.get<unknown, PageResult<FaqEntry>>(`/faq/knowledge-bases/${kbId}/entries`, { params })
}

export function createFaqEntry(kbId: string, data: FaqEntryCreateRequest) {
  return request.post<unknown, FaqEntry>(`/faq/knowledge-bases/${kbId}/entries`, data)
}

export function updateFaqEntry(id: string, data: Partial<FaqEntryCreateRequest>) {
  return request.put<unknown, FaqEntry>(`/faq/entries/${id}`, data)
}

export function deleteFaqEntry(id: string) {
  return request.delete<unknown, void>(`/faq/entries/${id}`)
}

export function importFaqEntries(kbId: string, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post<unknown, { imported: number; failed: number }>(`/faq/knowledge-bases/${kbId}/entries/batch`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
