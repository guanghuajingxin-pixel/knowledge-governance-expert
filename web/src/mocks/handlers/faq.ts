import { http, HttpResponse } from 'msw'
import { mockFaqEntries, mockFaqKb } from '../data/faq-entries'
import type { FaqEntryCreateRequest } from '@/types/faq'

const base = '/api/v1'

export const faqHandlers = [
  // 问答库列表：数组结构，含实际问答数（与 faq-service 口径一致）
  http.get(`${base}/faq/knowledge-bases`, () => {
    return HttpResponse.json([{ ...mockFaqKb, entry_count: mockFaqEntries.filter(e => e.kb_id === mockFaqKb.id).length }])
  }),

  http.get(`${base}/faq/knowledge-bases/:id/entries`, ({ request, params }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') || 1)
    const size = Number(url.searchParams.get('size') || 10)
    const keyword = url.searchParams.get('keyword')
    let items = mockFaqEntries.filter((e) => e.kb_id === params.id)
    if (keyword) items = items.filter((e) => e.question.includes(keyword)
      || e.answer.includes(keyword)
      || e.similar_questions.some(s => s.includes(keyword)))
    const total = items.length
    const start = (page - 1) * size
    return HttpResponse.json({ items: items.slice(start, start + size), total, page, size })
  }),

  http.post(`${base}/faq/knowledge-bases/:id/entries`, async ({ request, params }) => {
    const body = (await request.json()) as FaqEntryCreateRequest
    const newEntry = {
      ...body,
      similar_questions: body.similar_questions || [],
      keywords: body.keywords || [],
      id: 'faq-' + Date.now(),
      kb_id: params.id as string,
      source_document_id: null,
      status: 'INDEXED',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    mockFaqEntries.unshift(newEntry as any)
    return HttpResponse.json(newEntry)
  }),

  http.put(`${base}/faq/entries/:id`, async ({ request, params }) => {
    const body = (await request.json()) as Partial<FaqEntryCreateRequest>
    const idx = mockFaqEntries.findIndex((e) => e.id === params.id)
    if (idx < 0) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    mockFaqEntries[idx] = { ...mockFaqEntries[idx], ...body, updated_at: new Date().toISOString() } as any
    return HttpResponse.json(mockFaqEntries[idx])
  }),

  http.delete(`${base}/faq/entries/:id`, ({ params }) => {
    const idx = mockFaqEntries.findIndex((e) => e.id === params.id)
    if (idx >= 0) mockFaqEntries.splice(idx, 1)
    return HttpResponse.json(null, { status: 204 })
  }),

  http.post(`${base}/faq/knowledge-bases/:id/entries/batch`, async ({ request }) => {
    // Parse multipart body to acknowledge the upload; mock returns a fixed result.
    await request.formData()
    return HttpResponse.json({ imported: 10, failed: 0, index_failed: 0 })
  }),
]
