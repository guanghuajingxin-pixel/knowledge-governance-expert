import type { Segment } from '@/types/document'

export function generateMockSegments(documentId: string, count: number = 12): Segment[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `${documentId}-seg-${i + 1}`,
    document_id: documentId,
    faq_entry_id: null,
    es_chunk_id: `${documentId}_chunk_${i}`,
    chunk_index: i,
    content: `这是文档 ${documentId} 的第 ${i + 1} 个切片内容。知识库系统通过将长文档切分为多个语义片段，使得检索能够精准定位到相关段落。每个切片保留上下文信息，支持溯源到原始文档的具体位置。切片大小根据配置的策略动态调整，本切片使用的策略为段落切片，最大 token 数 512，重叠 150。`,
    content_hash: `sha256:${Math.random().toString(16).slice(2, 18)}`,
    token_count: 400 + (i % 120),
    embedding_dim: 1024,
    created_at: '2026-07-20T10:00:00Z',
  }))
}
