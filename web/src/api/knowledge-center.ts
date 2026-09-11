import request from './request'
import type { KbTreeNode, KnowledgeCenterDocument, TrashItem, TaskQueueStats, KcDocumentQuery, UploaderOption, DingTalkDocResult, DingTalkWorkspace, DingTalkNode, KnowledgeSource, KnowledgeSourcePayload } from '@/types/knowledge-center'
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

/** 获取文档创建人列表 */
export function fetchUploaders(kbType?: string) {
  return request.get<unknown, UploaderOption[]>('/knowledge-center/uploaders', {
    params: kbType ? { kb_type: kbType } : {},
  })
}

/** 钉钉知识库文件列表（实时拉取钉钉开放平台，首次/手动刷新遍历较慢，超时 10 分钟） */
export function fetchDingTalkDocuments(params: {
  page: number
  size: number
  workspace_id?: string
  creator_id?: string
  search?: string
  directory?: string
  refresh?: boolean
}) {
  return request.get<unknown, DingTalkDocResult>('/knowledge-center/dingtalk/documents', {
    params,
    timeout: 600000,
  })
}

/** 实时列出钉钉团队知识库（单次 API 调用，轻量） */
export function fetchDingTalkWorkspaces() {
  return request.get<unknown, { items: DingTalkWorkspace[]; error: string | null }>('/knowledge-center/dingtalk/workspaces', { timeout: 60000 })
}

/** 实时列出钉钉某父节点下的直接子节点（单次 API 调用，轻量） */
export function fetchDingTalkNodes(parentNodeId: string) {
  return request.get<unknown, { items: DingTalkNode[] }>('/knowledge-center/dingtalk/nodes', {
    params: { parent_node_id: parentNodeId },
    timeout: 60000,
  })
}

// ========== 知识源登记（企业知识库注册表）==========

/** 知识库列表：系统内所有「选择知识库」的地方均从此接口取数 */
export function listKnowledgeSources(params?: { source_type?: string; enabled_only?: boolean }) {
  return request.get<unknown, KnowledgeSource[]>('/knowledge-center/knowledge-sources', { params })
}

/** 新增知识库登记 */
export function createKnowledgeSource(payload: KnowledgeSourcePayload) {
  return request.post<unknown, KnowledgeSource>('/knowledge-center/knowledge-sources', payload)
}

/** 更新知识库登记 */
export function updateKnowledgeSource(id: number, payload: Partial<KnowledgeSourcePayload>) {
  return request.put<unknown, KnowledgeSource>(`/knowledge-center/knowledge-sources/${id}`, payload)
}

/** 删除知识库登记 */
export function deleteKnowledgeSource(id: number) {
  return request.delete<unknown, { ok: boolean }>(`/knowledge-center/knowledge-sources/${id}`)
}

/** 获取某知识库下的目录（通过知识库 ID 获取目录结构） */
export function fetchKnowledgeSourceDirectories(sourceId: number, parentNodeId?: string) {
  return request.get<unknown, { source_type: string; root_node_id: string; items: any[] }>(
    `/knowledge-center/knowledge-sources/${sourceId}/directories`,
    { params: parentNodeId ? { parent_node_id: parentNodeId } : {} },
  )
}
