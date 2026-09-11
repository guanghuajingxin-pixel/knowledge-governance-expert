import http from './http'
import type { Job, JobPayload } from '@/types'

export async function listJobs() { const { data } = await http.get<Job[]>('/jobs'); return data }
export async function createJob(payload: JobPayload) { const { data } = await http.post<Job>('/jobs', payload); return data }
export async function updateJob(id: number, payload: Partial<JobPayload>) { const { data } = await http.put<Job>(`/jobs/${id}`, payload); return data }
export async function deleteJob(id: number) { await http.delete(`/jobs/${id}`) }
export async function runJob(id: number) { await http.post(`/jobs/${id}/run`) }
export async function toggleJob(id: number) { const { data } = await http.post<Job>(`/jobs/${id}/toggle`); return data }
