export type FaqStatus = 'DRAFT' | 'PENDING' | 'INDEXED' | 'FAILED'

export interface FaqEntry {
  id: string
  kb_id: string
  directory_id: string | null
  question: string
  answer: string
  keywords: string[]
  source_document_id: string | null
  category_tags: string[]
  view_count: number
  helpful_count: number
  status: FaqStatus
  created_at: string
  updated_at: string
}

export interface FaqEntryCreateRequest {
  question: string
  answer: string
  keywords?: string[]
  category_tags?: string[]
  directory_id?: string | null
}
