export type DocStatus =
  | 'PENDING' | 'PARSING' | 'CHUNKING' | 'EMBEDDING'
  | 'INDEXING' | 'COMPLETED' | 'FAILED'

export interface Document {
  id: string
  kb_id: string
  directory_id: string | null
  filename: string
  original_filename: string
  file_type: string
  file_size: number
  storage_path: string
  status: DocStatus
  chunk_count: number
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface Segment {
  id: string
  document_id: string
  faq_entry_id: string | null
  es_chunk_id: string
  chunk_index: number
  content: string
  content_hash: string
  token_count: number
  embedding_dim: number | null
  created_at: string
}
