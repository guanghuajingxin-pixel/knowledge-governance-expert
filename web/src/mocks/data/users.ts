import type { UserInfo } from '@/types/user'

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
