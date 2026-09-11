import http from './http'
import type { PreviewItem, Source, SourcePayload, SourceStats } from '@/types'

export async function listSources() { const { data } = await http.get<Source[]>('/sources'); return data }
export async function createSource(payload: SourcePayload) { const { data } = await http.post<Source>('/sources', payload); return data }
export async function updateSource(id: number, payload: Partial<SourcePayload>) { const { data } = await http.put<Source>(`/sources/${id}`, payload); return data }
export async function deleteSource(id: number) { await http.delete(`/sources/${id}`) }
export async function testSource(id: number) { const { data } = await http.post(`/sources/${id}/test`); return data }
export async function syncSource(id: number) { await http.post(`/sources/${id}/sync`) }
export async function previewSource(id: number) { const { data } = await http.post<PreviewItem[]>(`/sources/${id}/preview`); return data }
export async function sourceStats(id: number) { const { data } = await http.get<SourceStats>(`/sources/${id}/stats`); return data }
