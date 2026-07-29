import { http, HttpResponse } from 'msw'
import { mockDocuments } from '../data/documents'
import { generateMockSegments } from '../data/segments'

const base = '/api/v1'

export const documentHandlers = [
  http.get(`${base}/documents`, ({ request }) => {
    const url = new URL(request.url)
    const kbId = url.searchParams.get('kb_id')
    const page = Number(url.searchParams.get('page') || 1)
    const size = Number(url.searchParams.get('size') || 10)
    let items = mockDocuments
    if (kbId) items = items.filter((d) => d.kb_id === kbId)
    const total = items.length
    const start = (page - 1) * size
    const paged = items.slice(start, start + size)
    return HttpResponse.json({ items: paged, total, page, size })
  }),

  http.get(`${base}/documents/:id`, ({ params }) => {
    const doc = mockDocuments.find((d) => d.id === params.id)
    if (!doc) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    return HttpResponse.json(doc)
  }),

  http.post(`${base}/documents/upload`, async ({ request }) => {
    const formData = await request.formData()
    const file = formData.get('file') as File
    const newDoc = {
      id: 'doc-' + Date.now(),
      kb_id: formData.get('kb_id') as string,
      directory_id: (formData.get('directory_id') as string) || null,
      filename: file.name,
      original_filename: file.name,
      file_type: file.name.split('.').pop() || 'unknown',
      file_size: file.size,
      storage_path: `raw-docs/${file.name}`,
      status: 'PENDING',
      chunk_count: 0,
      error_message: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    mockDocuments.unshift(newDoc as any)
    return HttpResponse.json({ document_id: newDoc.id, job_id: 'job-' + Date.now(), status: 'PENDING' })
  }),

  http.delete(`${base}/documents/:id`, ({ params }) => {
    const idx = mockDocuments.findIndex((d) => d.id === params.id)
    if (idx >= 0) mockDocuments.splice(idx, 1)
    return HttpResponse.json(null, { status: 204 })
  }),

  http.get(`${base}/documents/:id/preview`, ({ params }) => {
    const doc = mockDocuments.find((d) => d.id === params.id)
    if (!doc) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    return HttpResponse.json({
      preview_url: `http://localhost:8012/onlinePreview?url=encoded_${doc.id}`,
      preview_type: doc.file_type === 'pdf' ? 'pdf' : 'office',
    })
  }),

  http.get(`${base}/documents/:id/segments`, ({ request, params }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') || 1)
    const size = Number(url.searchParams.get('size') || 10)
    const all = generateMockSegments(params.id as string, 12)
    const start = (page - 1) * size
    const paged = all.slice(start, start + size)
    return HttpResponse.json({ items: paged, total: all.length, page, size })
  }),
]
