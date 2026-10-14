import request from './request'
import type { FaqEntry, FaqEntryCreateRequest, FaqImportResult, FaqKb } from '@/types/faq'
import type { PageQuery, PageResult } from '@/types/api'

export function listFaqKbs() {
  return request.get<unknown, FaqKb[]>('/faq/knowledge-bases')
}

/** 编辑 FAQ 问答库基础信息（名称/描述） */
export function updateFaqKb(id: string, data: { name: string; description?: string | null }) {
  return request.put<unknown, FaqKb>(`/faq/knowledge-bases/${id}`, data)
}

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
  return request.post<unknown, FaqImportResult>(`/faq/knowledge-bases/${kbId}/entries/batch`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    // 批量导入逐条建向量索引，大文件耗时较长，放宽到 5 分钟
    timeout: 300000,
  })
}
