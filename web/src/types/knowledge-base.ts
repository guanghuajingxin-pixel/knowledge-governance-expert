export type KbType = 'DOCUMENT' | 'FAQ'
export type ChunkStrategy = 'FIXED_SIZE' | 'PARAGRAPH' | 'MARKDOWN_HEADER' | 'SENTENCE'

export interface KnowledgeBase {
  id: string
  name: string
  description: string
  kb_type: KbType
  owner_id: string
  chunk_strategy: ChunkStrategy
  chunk_size: number
  chunk_overlap: number
  embedding_model: string
  es_index_name: string
  status: string
  is_favorite: boolean
  owner_name?: string
  document_count?: number
  created_at: string
  updated_at: string
}

export interface KbCreateRequest {
  name: string
  description?: string
  kb_type: KbType
  chunk_strategy?: ChunkStrategy
  chunk_size?: number
  chunk_overlap?: number
}

export interface Directory {
  id: string
  kb_id: string
  parent_id: string | null
  name: string
  sort_order: number
  created_at: string
  children?: Directory[]
}
