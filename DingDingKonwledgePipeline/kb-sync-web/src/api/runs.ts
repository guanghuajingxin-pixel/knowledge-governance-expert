import http from './http'
import type { Failure, Log, Run, RunDetail } from '@/types'

export async function listRuns(params?: { source_id?: number; limit?: number; offset?: number }) { const { data } = await http.get<Run[]>('/runs', { params }); return data }
export async function getRun(id: number) { const { data } = await http.get<RunDetail>(`/runs/${id}`); return data }
export async function listFailures(params?: { run_id?: number; limit?: number; offset?: number }) { const { data } = await http.get<Failure[]>('/failures', { params }); return data }
export async function listLogs(params?: { run_id?: number; limit?: number; offset?: number }) { const { data } = await http.get<Log[]>('/logs', { params }); return data }
export async function retryFailure(id: number) { await http.post(`/failures/${id}/retry`) }
export async function retryAllFailures() { await http.post('/failures/retry-all') }
