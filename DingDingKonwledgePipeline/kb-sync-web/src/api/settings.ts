import http from './http'
import type { Settings } from '@/types'

export async function getSettings() { const { data } = await http.get<Settings>('/settings'); return data }
export async function updateSettings(payload: Partial<Settings>) { const { data } = await http.put<Settings>('/settings', payload); return data }
