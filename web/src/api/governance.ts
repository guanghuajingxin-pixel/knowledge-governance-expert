import request from './request'

/** 治理标准：钉钉 AI 多维表《杰克知识管理规范》记录 */
export interface StandardDoc {
  record_id: string
  doc_type: string
  code: string
  version: string
  status: string
  effective_date: string
  link: string
  maintainer: string
}

export interface StandardsResponse {
  items: StandardDoc[]
  total: number
  error?: string | null
  fetched_at?: string
  /** 后端 60s 缓存：true=本次返回的是缓存数据 */
  from_cache?: boolean
  /** true=缓存已过期，旧数据先展示、后台正在重新拉取 */
  stale?: boolean
}

/** refresh=true 时绕过服务端缓存强制重拉钉钉多维表（页面「刷新」按钮用） */
export const getStandards = (refresh = false) =>
  request.get<unknown, StandardsResponse>('/governance/standards',
    { params: refresh ? { refresh: true } : undefined })

export interface KnowledgeGap {
  directory_id: string
  kb_id: string
  kb_name: string
  directory_path: string
  owner: string
  document_count: number
  /** 直接子文件夹数（不含目录本身与孙级）；钉钉行为快照内直属子文件夹，本地行为直接子目录 */
  folder_count: number
  /** 行来源：local=本地知识库目录（可维护Owner） dingtalk=钉钉知识库文件夹（实时拉取） */
  source?: 'local' | 'dingtalk'
  /** 钉钉知识库首页链接（仅 dingtalk 行） */
  kb_url?: string
  /** 该目录在钉钉中的节点链接（仅 dingtalk 行）；根目录同样可跳转知识库首页 */
  dingtalk_url?: string
}
export interface GapFilters {
  kb_id?: string
  owner?: string
  document_state: 'all' | 'empty' | 'has'
}
export interface GapResponse {
  items: KnowledgeGap[]
  total: number
  knowledge_bases: { id: string; name: string }[]
  owners: string[]
  error?: string | null
}
export const getGaps = (params: GapFilters & { page: number; size: number }) =>
  request.get<unknown, GapResponse>('/governance/gaps', { params })
export const exportGaps = (params: GapFilters) =>
  request.get<unknown, Blob>('/governance/gaps/export', { params, responseType: 'blob' })
/** 钉钉知识库文件夹快照刷新状态 */
export interface DingtalkRefreshStatus {
  running: boolean
  done: number
  error?: string | null
  folder_count: number
  fetched_at?: string | null
}
/** 触发后台刷新（全量遍历钉钉知识库文件夹，进度轮询 status 接口） */
export const refreshDingtalkFolders = (kbId: string) =>
  request.post<unknown, { ok: boolean; running: boolean }>('/governance/gaps/dingtalk/refresh', null, { params: { kb_id: kbId } })
export const getDingtalkRefreshStatus = (kbId: string) =>
  request.get<unknown, DingtalkRefreshStatus>('/governance/gaps/dingtalk/refresh/status', { params: { kb_id: kbId } })
export const getOwnerTemplate = (params?: { kb_id?: string }) =>
  request.get<unknown, Blob>('/governance/gaps/owner-template', { params, responseType: 'blob' })
export const saveGapOwner = (id: string, owner: string) =>
  request.put(`/governance/gaps/${id}/owner`, { owner })
/** 维护钉钉知识库文件夹的知识Owner（owner 留空清除） */
export const saveDingtalkOwner = (kbId: string, nodeId: string, owner: string) =>
  request.put<unknown, { ok: boolean }>('/governance/gaps/dingtalk/owner',
    { kb_id: kbId, node_id: nodeId, owner })
/** 通过钉钉机器人给知识Owner发单聊通知（该目录下的知识为空） */
export const notifyGapOwner = (kbId: string, nodeId: string) =>
  request.post<unknown, { ok: boolean; message?: string }>('/governance/gaps/dingtalk/notify',
    { kb_id: kbId, node_id: nodeId })
export const importGapOwners = (file: File) => {
  const data = new FormData()
  data.append('file', file)
  return request.post<unknown, { updated: number }>('/governance/gaps/owners/import', data)
}
