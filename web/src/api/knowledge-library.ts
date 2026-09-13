import request from './request'

// 知识库（检索抽象层）：统一登记 RAGFlow / DIFY 知识库镜像，供智能体检索选库。
// 仅登记 platform + dataset_id 引用，不支持导入/解析新文档；
// 与「知识源管理」（推送路径定义）相互独立。

export type LibraryPlatform = 'dify' | 'ragflow'

export interface KnowledgeLibrary {
  id: number
  name: string
  platform: LibraryPlatform
  dataset_id: string
  description: string
  enabled: boolean
  updated_at: string
}

export interface KnowledgeLibraryCreate {
  name: string
  platform: LibraryPlatform
  dataset_id: string
  description?: string
  enabled?: boolean
}

export interface KnowledgeLibraryUpdate {
  name?: string
  description?: string
  enabled?: boolean
}

export const listKnowledgeLibraries = (enabledOnly = false) =>
  request.get<unknown, KnowledgeLibrary[]>('/knowledge-libraries', {
    params: enabledOnly ? { enabled_only: true } : {},
  })

export const createKnowledgeLibrary = (data: KnowledgeLibraryCreate) =>
  request.post<unknown, KnowledgeLibrary>('/knowledge-libraries', data)

export const updateKnowledgeLibrary = (id: number, data: KnowledgeLibraryUpdate) =>
  request.put<unknown, KnowledgeLibrary>(`/knowledge-libraries/${id}`, data)

export const deleteKnowledgeLibrary = (id: number) =>
  request.delete<unknown, { ok: boolean }>(`/knowledge-libraries/${id}`)
