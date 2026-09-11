import { defineStore } from 'pinia'
import { getDashboard } from '@/api/dashboard'
import { listSources, sourceStats } from '@/api/sources'
import { listJobs } from '@/api/jobs'
import { listFailures, listRuns } from '@/api/runs'
import { listWorkspaces } from '@/api/dingtalk'
import type { Dashboard, Failure, Job, Run, Source, SourceStats } from '@/types'

export const useAppStore = defineStore('app', {
  state: () => ({
    sources: [] as Source[],
    jobs: [] as Job[],
    dashboard: null as Dashboard | null,
    runs: [] as Run[],
    failures: [] as Failure[],
    sourceStatsMap: {} as Record<number, SourceStats>,
    workspaceNames: {} as Record<string, string>,
  }),
  actions: {
    async refreshSources() {
      this.sources = await listSources()
      const stats = await Promise.allSettled(this.sources.map((s) => sourceStats(s.id)))
      stats.forEach((r, i) => {
        if (r.status === 'fulfilled') this.sourceStatsMap[this.sources[i].id] = r.value
      })
    },
    async refreshWorkspaces() {
      const workspaces = await listWorkspaces()
      this.workspaceNames = Object.fromEntries(workspaces.map((w) => [w.workspaceId, w.name]))
    },
    async refreshJobs() { this.jobs = await listJobs() },
    async refreshDashboard() { this.dashboard = await getDashboard() },
    async refreshRuns() { this.runs = await listRuns({ limit: 100 }) },
    async refreshFailures() { this.failures = await listFailures({ limit: 200 }) },
    async refreshAll() {
      await Promise.all([
        this.refreshSources(),
        this.refreshJobs(),
        this.refreshDashboard(),
        this.refreshRuns(),
        this.refreshFailures(),
        this.refreshWorkspaces(),
      ])
    },
    sourceName(id: number | null): string {
      if (id === null || id === undefined) return '—'
      const s = this.sources.find((x) => x.id === id)
      return s ? s.name : `#${id}`
    },
    sourceStats(id: number): SourceStats | undefined {
      return this.sourceStatsMap[id]
    },
    workspaceName(id: string): string {
      return this.workspaceNames[id] || id
    },
  },
})