export type FaqStatus = 'DRAFT' | 'PENDING' | 'INDEXED' | 'FAILED'

/** FAQ 问答库（kb_type=FAQ 的知识库，经 faq-service 读列） */
export interface FaqKb {
  id: string
  name: string
  description: string | null
  entry_count: number
  created_at: string | null
}

export interface FaqEntry {
  id: string
  kb_id: string
  directory_id: string | null
  question: string
  answer: string
  keywords: string[]
  /** 相似问：归属于问题的问句变体，检索命中任一相似问即召回同一答案；列表中仅算一条数据 */
  similar_questions: string[]
  source_document_id: string | null
  status: FaqStatus
  created_at: string
  updated_at: string
}

export interface FaqEntryCreateRequest {
  question: string
  answer: string
  keywords?: string[]
  similar_questions?: string[]
  directory_id?: string | null
}

/** 批量导入结果：imported=入库条数；failed=解析无效行数；index_failed=向量索引失败条数 */
export interface FaqImportResult {
  imported: number
  failed: number
  index_failed: number
}
