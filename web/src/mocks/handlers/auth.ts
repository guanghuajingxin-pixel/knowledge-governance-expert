import { http, HttpResponse } from 'msw'
import { mockUsers } from '../data/users'

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
]
