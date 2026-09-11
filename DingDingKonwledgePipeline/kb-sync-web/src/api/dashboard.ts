import http from './http'
import type { Dashboard } from '@/types'

export async function getDashboard() { const { data } = await http.get<Dashboard>('/dashboard'); return data }
