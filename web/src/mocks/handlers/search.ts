import { http, HttpResponse } from 'msw'
import { mockSearchResults } from '../data/search-results'

const base = '/api/v1'

export const searchHandlers = [
  http.post(`${base}/search`, async () => {
    return HttpResponse.json({
      results: mockSearchResults,
      total: mockSearchResults.length,
      took_ms: 145,
    })
  }),

  http.get(`${base}/search/trace/:chunkId`, ({ params }) => {
    const result = mockSearchResults.find((r) => r.chunk_id === params.chunkId)
    if (!result) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    return HttpResponse.json(result)
  }),
]
