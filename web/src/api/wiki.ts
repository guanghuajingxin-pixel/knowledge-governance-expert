import request from './request'

// Wiki 知识库（卡帕提 LLM WIKI 模式）：库 CRUD / 页面 / 生成记录 / Lint / 问答沉淀。
// 原料文档的导入/解析复用文档库管理（api/document-library，后端已对 wiki 库开放）。

export interface WikiRun {
  id: string
  kind: 'ingest' | 'lint'
  document_ids: string[]
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  pages_created: number
  pages_updated: number
  report: Record<string, unknown>
  error: string
  triggered_by: string
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface WikiLibrary {
  id: number
  name: string
  description: string
  enabled: boolean
  creator: string | null
  auto_generate: boolean
  page_count: number
  document_count: number
  last_run: WikiRun | null
  created_at: string
  updated_at: string
}

export interface WikiSourceRef {
  document_id?: string
  document_name?: string
  question?: string
}

export interface WikiPage {
  id: string
  title: string
  page_type: 'overview' | 'topic' | 'entity' | 'comparison' | 'qa'
  summary: string
  source_refs: WikiSourceRef[]
  status: string
  message: string
  version: number
  edited_by_human: boolean
  generated_model: string
  created_at: string
  updated_at: string
  content?: string
}

export interface WikiLibraryInput {
  name: string
  description: string
  auto_generate: boolean
}

export const listWikiLibraries = () =>
  request.get<unknown, WikiLibrary[]>('/wiki/libraries')

export const getWikiLibrary = (id: number) =>
  request.get<unknown, WikiLibrary>(`/wiki/libraries/${id}`)

export const createWikiLibrary = (data: WikiLibraryInput) =>
  request.post<unknown, WikiLibrary>('/wiki/libraries', data)

export const updateWikiLibrary = (id: number, data: Partial<WikiLibraryInput>) =>
  request.put<unknown, WikiLibrary>(`/wiki/libraries/${id}`, data)

export const deleteWikiLibrary = (id: number) =>
  request.delete<unknown, { ok: boolean }>(`/wiki/libraries/${id}`)

export const listWikiPages = (libraryId: number) =>
  request.get<unknown, WikiPage[]>(`/wiki/libraries/${libraryId}/pages`)

export const getWikiPage = (libraryId: number, pageId: string) =>
  request.get<unknown, WikiPage>(`/wiki/libraries/${libraryId}/pages/${pageId}`)

export const editWikiPage = (libraryId: number, pageId: string,
                             data: { title?: string; content: string; summary?: string }) =>
  request.put<unknown, WikiPage>(`/wiki/libraries/${libraryId}/pages/${pageId}`, data)

export const deleteWikiPage = (libraryId: number, pageId: string) =>
  request.delete<unknown, { ok: boolean }>(`/wiki/libraries/${libraryId}/pages/${pageId}`)

export const regenerateWikiPage = (libraryId: number, pageId: string) =>
  request.post<unknown, WikiPage>(`/wiki/libraries/${libraryId}/pages/${pageId}/regenerate`)

export const generateWiki = (libraryId: number, documentIds: string[] = []) =>
  request.post<unknown, { run_id: string; document_count: number }>(
    `/wiki/libraries/${libraryId}/generate`, { document_ids: documentIds })

export const listWikiRuns = (libraryId: number) =>
  request.get<unknown, WikiRun[]>(`/wiki/libraries/${libraryId}/runs`)

export const retryWikiRun = (libraryId: number, runId: string) =>
  request.post<unknown, { run_id: string }>(`/wiki/libraries/${libraryId}/runs/${runId}/retry`)

export const triggerWikiLint = (libraryId: number) =>
  request.post<unknown, { run_id: string }>(`/wiki/libraries/${libraryId}/lint`)

export const latestWikiLint = (libraryId: number) =>
  request.get<unknown, WikiRun | null>(`/wiki/libraries/${libraryId}/lint/latest`)

export const archiveQaToWiki = (libraryId: number, data: { title: string; content: string; question: string }) =>
  request.post<unknown, WikiPage>(`/wiki/libraries/${libraryId}/pages/qa-archive`, data)
