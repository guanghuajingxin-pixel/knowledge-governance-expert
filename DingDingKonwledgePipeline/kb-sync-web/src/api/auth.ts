import http from './http'

export async function login(username: string, password: string): Promise<string> {
  const { data } = await http.post('/auth/login', { username, password })
  return data.token as string
}
