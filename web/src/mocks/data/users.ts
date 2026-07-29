import type { UserInfo, ApiKey } from '@/types/user'

export const mockUsers: UserInfo[] = [
  {
    id: 'u-001',
    username: 'admin',
    email: 'admin@kb.com',
    role: 'super_admin',
    is_active: true,
    created_at: '2026-06-01T08:00:00Z',
  },
  {
    id: 'u-002',
    username: 'editor',
    email: 'editor@kb.com',
    role: 'editor',
    is_active: true,
    created_at: '2026-06-15T08:00:00Z',
  },
]

export const mockApiKeys: ApiKey[] = [
  {
    id: 'k-001',
    name: '生产环境调用',
    key_prefix: 'kb-a1b2c3',
    is_active: true,
    last_used_at: '2026-07-28T10:00:00Z',
    created_at: '2026-07-01T08:00:00Z',
  },
  {
    id: 'k-002',
    name: '测试环境',
    key_prefix: 'kb-d4e5f6',
    is_active: false,
    last_used_at: null,
    created_at: '2026-07-20T08:00:00Z',
  },
]
