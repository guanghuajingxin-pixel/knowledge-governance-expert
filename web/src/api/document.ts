import request from './request'
import type { Document, Segment, DocStatus } from '@/types/document'
import type { PageQuery, PageResult } from '@/types/api'

export function listDocuments(params: PageQuery & { kb_id: string; directory_id?: string; status?: DocStatus }) {
  return request.get<unknown, PageResult<Document>>('/documents', { params })
}

export function getDocument(id: string) {
  return request.get<unknown, Document>(`/documents/${id}`)
}

export function uploadDocument(file: File, kbId: string, directoryId?: string) {
  const formData = new FormData()
  formData.append('file', file)
  const params: Record<string, string> = { kb_id: kbId }
  if (directoryId) params.directory_id = directoryId
  return request.post<unknown, { document_id: string; job_id: string; status: string }>('/documents/upload', formData, {
    params,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function deleteDocument(id: string) {
  return request.delete<unknown, void>(`/documents/${id}`)
}

export function getDocumentPreviewUrl(id: string) {
  return request.get<unknown, { preview_url: string; preview_type: string }>(`/documents/${id}/preview`)
}

export function getDocumentSegments(id: string, params: PageQuery) {
  return request.get<unknown, PageResult<Segment>>(`/documents/${id}/segments`, { params })
}

export function reprocessDocument(id: string) {
  return request.post<unknown, void>(`/documents/${id}/reprocess`)
}
