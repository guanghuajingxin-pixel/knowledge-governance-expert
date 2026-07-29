import { http, HttpResponse } from 'msw'
import { mockUsers, mockApiKeys } from '../data/users'

const base = '/api/v1'

export const authHandlers = [
  http.post(`${base}/auth/login`, async ({ request }) => {
    const body = (await request.json()) as { username: string; password: string }
    const user = mockUsers.find((u) => u.username === body.username)
    if (!user) {
      return HttpResponse.json({ code: 401, message: '用户名或密码错误', data: null }, { status: 401 })
    }
    return HttpResponse.json({
      access_token: 'mock-jwt-token-' + user.id,
      token_type: 'bearer',
      user,
    })
  }),

  http.get(`${base}/users/me`, ({ request }) => {
    const auth = request.headers.get('Authorization') || ''
    const id = auth.replace('mock-jwt-token-', '')
    const user = mockUsers.find((u) => u.id === id) || mockUsers[0]
    return HttpResponse.json(user)
  }),

  http.get(`${base}/auth/api-keys`, () => {
    return HttpResponse.json(mockApiKeys)
  }),

  http.post(`${base}/auth/api-keys`, async ({ request }) => {
    const body = (await request.json()) as { name: string }
    const newKey = {
      id: 'k-' + Date.now(),
      name: body.name,
      key_prefix: 'kb-' + Math.random().toString(36).slice(2, 8),
      is_active: true,
      last_used_at: null,
      created_at: new Date().toISOString(),
      raw_key: 'kb-' + Math.random().toString(36).slice(2, 14) + Math.random().toString(36).slice(2, 14),
    }
    return HttpResponse.json(newKey)
  }),

  http.delete(`${base}/auth/api-keys/:id`, ({ params }) => {
    const idx = mockApiKeys.findIndex((k) => k.id === params.id)
    if (idx >= 0) mockApiKeys.splice(idx, 1)
    return HttpResponse.json(null, { status: 204 })
  }),
]
