import { http, HttpResponse } from 'msw'
import { mockKnowledgeBases, mockDirectories } from '../data/knowledge-bases'
import type { KnowledgeBase, KbCreateRequest } from '@/types/knowledge-base'

const base = '/api/v1'

export const kbHandlers = [
  http.get(`${base}/knowledge-bases`, ({ request }) => {
    const url = new URL(request.url)
    const kbType = url.searchParams.get('kb_type')
    let items = mockKnowledgeBases
    if (kbType) items = items.filter((k) => k.kb_type === kbType)
    return HttpResponse.json({ items, total: items.length, page: 1, size: items.length })
  }),

  http.get(`${base}/knowledge-bases/:id`, ({ params }) => {
    const kb = mockKnowledgeBases.find((k) => k.id === params.id)
    if (!kb) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    return HttpResponse.json(kb)
  }),

  http.post(`${base}/knowledge-bases`, async ({ request }) => {
    const body = (await request.json()) as KbCreateRequest
    const newKb: KnowledgeBase = {
      id: 'kb-' + Date.now(),
      name: body.name,
      description: body.description ?? '',
      kb_type: body.kb_type,
      owner_id: 'u-001',
      chunk_strategy: body.chunk_strategy ?? 'FIXED_SIZE',
      chunk_size: body.chunk_size ?? 512,
      chunk_overlap: body.chunk_overlap ?? 150,
      embedding_model: 'bge-m3',
      es_index_name: 'kb_kb-' + Date.now(),
      document_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    mockKnowledgeBases.push(newKb)
    return HttpResponse.json(newKb)
  }),

  http.put(`${base}/knowledge-bases/:id`, async ({ request, params }) => {
    const body = (await request.json()) as Partial<KbCreateRequest>
    const idx = mockKnowledgeBases.findIndex((k) => k.id === params.id)
    if (idx < 0) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    mockKnowledgeBases[idx] = { ...mockKnowledgeBases[idx], ...body, updated_at: new Date().toISOString() }
    return HttpResponse.json(mockKnowledgeBases[idx])
  }),

  http.delete(`${base}/knowledge-bases/:id`, ({ params }) => {
    const idx = mockKnowledgeBases.findIndex((k) => k.id === params.id)
    if (idx >= 0) mockKnowledgeBases.splice(idx, 1)
    return HttpResponse.json(null, { status: 204 })
  }),

  http.get(`${base}/knowledge-bases/:id/directories`, ({ params }) => {
    const dirs = mockDirectories[params.id as string] || []
    return HttpResponse.json(dirs)
  }),

  http.post(`${base}/knowledge-bases/:id/directories`, async ({ request, params }) => {
    const body = (await request.json()) as { name: string; parent_id: string | null }
    const newDir = {
      id: 'dir-' + Date.now(),
      kb_id: params.id as string,
      parent_id: body.parent_id,
      name: body.name,
      sort_order: 99,
      created_at: new Date().toISOString(),
    }
    if (!mockDirectories[params.id as string]) mockDirectories[params.id as string] = []
    mockDirectories[params.id as string].push(newDir)
    return HttpResponse.json(newDir)
  }),
]
