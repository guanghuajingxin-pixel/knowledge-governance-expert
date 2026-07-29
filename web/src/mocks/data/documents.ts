import type { Document } from '@/types/document'

const statuses = ['COMPLETED', 'COMPLETED', 'INDEXING', 'FAILED', 'COMPLETED'] as const

export const mockDocuments: Document[] = Array.from({ length: 28 }, (_, i) => ({
  id: `doc-${String(i + 1).padStart(3, '0')}`,
  kb_id: 'kb-001',
  directory_id: i % 3 === 0 ? 'dir-001' : i % 3 === 1 ? 'dir-002' : 'dir-003',
  filename: `document_${i + 1}.pdf`,
  original_filename: `产品手册第${i + 1}章.pdf`,
  file_type: i % 4 === 0 ? 'pdf' : i % 4 === 1 ? 'docx' : i % 4 === 2 ? 'md' : 'xlsx',
  file_size: 1024 * 1024 * (1 + (i % 5)),
  storage_path: `raw-docs/doc-${i + 1}.pdf`,
  status: statuses[i % statuses.length],
  chunk_count: 10 + (i % 20),
  error_message: i % 5 === 3 ? '解析超时' : null,
  created_at: `2026-06-${String((i % 28) + 1).padStart(2, '0')}T08:00:00Z`,
  updated_at: `2026-07-${String((i % 28) + 1).padStart(2, '0')}T10:00:00Z`,
}))
