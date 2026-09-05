import request from './request'
import type { KbTreeNode, KnowledgeCenterDocument, TrashItem, TaskQueueStats, KcDocumentQuery } from '@/types/knowledge-center'
import type { PageQuery, PageResult } from '@/types/api'

/** 获取统一目录树 */
export function fetchDirectoryTree(kbType?: string) {
  return request.get<unknown, KbTreeNode[]>('/knowledge-center/directories', {
    params: kbType ? { kb_type: kbType } : {},
  })
}

/** 跨知识库文档列表 */
export function fetchDocuments(params: KcDocumentQuery) {
  return request.get<unknown, PageResult<KnowledgeCenterDocument>>('/knowledge-center/documents', { params })
}

/** 获取文档详情 */
export function fetchDocumentDetail(id: string) {
  return request.get<unknown, KnowledgeCenterDocument>(`/knowledge-center/documents/${id}`)
}

/** 回收站列表 */
export function fetchRecycleBin(params: PageQuery) {
  return request.get<unknown, PageResult<TrashItem>>('/knowledge-center/recycle-bin', { params })
}

/** 从回收站恢复文档 */
export function restoreDocument(id: string) {
  return request.post<unknown, { ok: boolean }>(`/knowledge-center/recycle-bin/${id}/restore`)
}

/** 永久删除文档 */
export function permanentDeleteDocument(id: string) {
  return request.delete<unknown, { ok: boolean }>(`/knowledge-center/recycle-bin/${id}`)
}

/** 任务队列统计 */
export function fetchTaskStats(kbType?: string) {
  return request.get<unknown, TaskQueueStats>('/knowledge-center/task-stats', {
    params: kbType ? { kb_type: kbType } : {},
  })
}
