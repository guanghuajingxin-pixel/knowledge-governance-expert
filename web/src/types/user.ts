export type UserRole = 'super_admin' | 'admin' | 'editor' | 'viewer'

export interface UserInfo {
  id: string
  username: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: UserInfo
}

export interface ApiKey {
  id: string
  name: string
  key_prefix: string
  is_active: boolean
  last_used_at: string | null
  created_at: string
}

export interface ApiKeyCreated extends ApiKey {
  raw_key: string
}
