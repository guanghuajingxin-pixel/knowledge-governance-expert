import request from './request'

// ============ 结构化处理（知识加工 · 二级页） ============

export type StructuredEngine = 'kit_v1' | 'cloud_v4'

export interface StructuredEngines {
  kit_v1: { available: boolean; base_url: string }
  cloud_v4: { available: boolean; base_url: string }
}

export const getStructuredEngines = () =>
  request.get<unknown, StructuredEngines>('/structured/engines')

export interface StructuredTask {
  id: string
  file_name: string
  file_ext: string
  engine: StructuredEngine
  tier: string
  ocr_mode: string
  status: 'pending' | 'parsing' | 'completed' | 'failed' | string
  error: string | null
  block_count: number
  created_at: string | null
  finished_at: string | null
}

export const createStructuredTask = (data: FormData) =>
  request.post<unknown, { id: string; status: string }>('/structured/tasks', data)

export const listStructuredTasks = (limit = 50) =>
  request.get<unknown, { items: StructuredTask[] }>('/structured/tasks', { params: { limit } })

export const getStructuredTask = (id: string) =>
  request.get<unknown, StructuredTask>(`/structured/tasks/${id}`)

export interface StructuredContent {
  id: string
  file_name: string
  status: string
  content: Record<string, unknown>[]
  markdown: string
  meta: Record<string, unknown>
}

export const getStructuredTaskContent = (id: string) =>
  request.get<unknown, StructuredContent>(`/structured/tasks/${id}/content`)

export const deleteStructuredTask = (id: string) =>
  request.delete<unknown, { ok: boolean }>(`/structured/tasks/${id}`)

// ---- 表结构 + 映射 ----
export interface StructuredColumn {
  name: string
  type: string
  path?: string
  const?: string | null
}

export interface StructuredSchema {
  id: string
  name: string
  target_table: string
  row_source: string
  columns: StructuredColumn[]
  description: string
  updated_at: string | null
}

export const listStructuredSchemas = () =>
  request.get<unknown, { items: StructuredSchema[] }>('/structured/schemas')

export const createStructuredSchema = (data: {
  name: string
  target_table: string
  row_source: string
  columns: StructuredColumn[]
  description?: string
}) => request.post<unknown, StructuredSchema>('/structured/schemas', data)

export const updateStructuredSchema = (
  id: string,
  data: Partial<{
    name: string
    target_table: string
    row_source: string
    columns: StructuredColumn[]
    description: string
  }>,
) => request.put<unknown, StructuredSchema>(`/structured/schemas/${id}`, data)

export const deleteStructuredSchema = (id: string) =>
  request.delete<unknown, { ok: boolean }>(`/structured/schemas/${id}`)

// ---- 预览 / 写入 ----
export interface StructuredPreview {
  columns: string[]
  rows: Record<string, unknown>[]
  total: number
  warnings: string[]
}

export const previewStructured = (
  data: { task_id: string; schema_id?: string; row_source?: string; columns?: StructuredColumn[] },
  limit = 50,
) => request.post<unknown, StructuredPreview>('/structured/preview', data, { params: { limit } })

export interface StructuredWriteResult {
  target_table: string
  rows_written: number
  warnings: string[]
}

export const writeStructured = (data: { task_id: string; schema_id: string }) =>
  request.post<unknown, StructuredWriteResult>('/structured/write', data)

export interface StructuredWriteLog {
  id: string
  schema_id: string | null
  task_id: string | null
  target_table: string
  rows_written: number
  status: string
  error: string | null
  created_at: string | null
}

export const listStructuredWriteLogs = (limit = 50) =>
  request.get<unknown, { items: StructuredWriteLog[] }>('/structured/write-logs', { params: { limit } })

export interface StructuredTableInfo {
  table: string
  rows: number
}

export const listStructuredTables = () =>
  request.get<unknown, { items: StructuredTableInfo[] }>('/structured/tables')

// ---- 写入目标库配置 ----
export interface StructuredTarget {
  url_masked: string
  source: string
}

export const getStructuredTarget = () =>
  request.get<unknown, StructuredTarget>('/structured/target')

export interface StructuredTargetTest {
  ok: boolean
  message: string
}

export const testStructuredTarget = (url?: string) =>
  request.post<unknown, StructuredTargetTest>('/structured/test-target', { url: url || '' })
