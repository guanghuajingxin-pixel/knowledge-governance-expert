import type { KnowledgeBase, Directory } from '@/types/knowledge-base'

export const mockKnowledgeBases: KnowledgeBase[] = [
  {
    id: 'kb-001',
    name: '产品技术文档库',
    description: '包含所有产品的技术说明、API 文档和架构设计',
    kb_type: 'DOCUMENT',
    owner_id: 'u-001',
    chunk_strategy: 'PARAGRAPH',
    chunk_size: 512,
    chunk_overlap: 150,
    embedding_model: 'bge-m3',
    es_index_name: 'kb_kb-001',
    status: 'active',
    is_favorite: false,
    document_count: 28,
    created_at: '2026-06-01T08:00:00Z',
    updated_at: '2026-07-20T10:00:00Z',
  },
  {
    id: 'kb-002',
    name: '客户常见问题库',
    description: '客户高频问题与标准答案',
    kb_type: 'DOCUMENT',
    owner_id: 'u-001',
    chunk_strategy: 'PARAGRAPH',
    chunk_size: 512,
    chunk_overlap: 150,
    embedding_model: 'bge-m3',
    es_index_name: 'kb_kb-002',
    status: 'active',
    is_favorite: true,
    document_count: 12,
    created_at: '2026-06-10T08:00:00Z',
    updated_at: '2026-07-25T10:00:00Z',
  },
  {
    id: 'kb-003',
    name: '运维手册',
    description: '部署、监控、故障排查手册',
    kb_type: 'DOCUMENT',
    owner_id: 'u-002',
    chunk_strategy: 'MARKDOWN_HEADER',
    chunk_size: 768,
    chunk_overlap: 200,
    embedding_model: 'bge-m3',
    es_index_name: 'kb_kb-003',
    status: 'active',
    is_favorite: false,
    document_count: 8,
    created_at: '2026-06-20T08:00:00Z',
    updated_at: '2026-07-22T10:00:00Z',
  },
]

export const mockDirectories: Record<string, Directory[]> = {
  'kb-001': [
    {
      id: 'dir-001', kb_id: 'kb-001', parent_id: null, name: '架构设计', sort_order: 1, created_at: '2026-06-01T08:00:00Z',
      children: [
        { id: 'dir-011', kb_id: 'kb-001', parent_id: 'dir-001', name: '微服务', sort_order: 1, created_at: '2026-06-01T08:00:00Z' },
        { id: 'dir-012', kb_id: 'kb-001', parent_id: 'dir-001', name: '数据模型', sort_order: 2, created_at: '2026-06-01T08:00:00Z' },
      ],
    },
    { id: 'dir-002', kb_id: 'kb-001', parent_id: null, name: 'API 文档', sort_order: 2, created_at: '2026-06-02T08:00:00Z' },
    { id: 'dir-003', kb_id: 'kb-001', parent_id: null, name: '认证授权', sort_order: 3, created_at: '2026-06-03T08:00:00Z' },
  ],
}
