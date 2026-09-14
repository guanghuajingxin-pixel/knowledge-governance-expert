<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { formatDate } from '@/utils/format'
import {
  listFailures, listLogs, listRuns, listSources, retryAllFailures, retryFailure, sourcesStatsAll,
} from '@/api/sync'
import type { Failure, Log, Run, Source, SourceStats } from '@/types/sync'
import type { SourceStatsItem } from '@/api/sync'
import StatusPill from './components/StatusPill.vue'

// ===== 数据 =====
const sources = ref<Source[]>([])
const runs = ref<Run[]>([])
const failures = ref<Failure[]>([])
const logs = ref<Log[]>([])
const statsMap = ref<Record<number, SourceStats>>({})
const loadingRuns = ref(false)
const loadingFail = ref(false)
const loadingLogs = ref(false)

// ===== 日志筛选 =====
const lv = ref('')
const srcKeyword = ref('')
const date = ref('')
const now = Date.now()
const filteredLogs = computed(() => logs.value.filter((l) => {
  if (lv.value && l.level.toLowerCase() !== lv.value) return false
  if (srcKeyword.value && !l.message.includes(srcKeyword.value)) return false
  if (date.value) {
    const t = new Date(l.created_at + (l.created_at.endsWith('Z') ? '' : 'Z')).getTime()
    const days = date.value === '今天' ? 1 : date.value === '最近 3 天' ? 3 : 7
    if (now - t > days * 86400000) return false
  }
  return true
}))

// ===== 工具 =====
function sourceName(id: number) { return sources.value.find((s) => s.id === id)?.name || `#${id}` }
function dur(r: any) {
  if (!r.finished_at) return '运行中…'
  const s = new Date(r.started_at + (r.started_at.endsWith('Z') ? '' : 'Z')).getTime()
  const e = new Date(r.finished_at + (r.finished_at.endsWith('Z') ? '' : 'Z')).getTime()
  const sec = Math.max(0, Math.round((e - s) / 1000))
  if (sec < 60) return `${sec} 秒`
  const m = Math.floor(sec / 60); return `${m} 分 ${sec % 60} 秒`
}
function skippedOf(r: any) { return Math.max(0, r.total - r.created_count - r.updated_count - r.deleted_count - r.failed_count) }
function lvClass(level: string) { const v = level.toLowerCase(); return v === 'error' ? 'danger' : v === 'warn' ? 'warning' : 'info' }

// ===== 加载 =====
async function refresh() {
  await Promise.all([loadRuns(), loadFailures(), loadLogs(), loadSourcesAndStats()])
}
async function loadSourcesAndStats() {
  // 批量统计接口（2 条聚合 SQL）替代逐源 sourceStats 的 N+1：
  // 10 个源从 11 请求/轮（每 5s）降到 2 请求
  try {
    const [list, statsRes] = await Promise.all([
      listSources(),
      sourcesStatsAll().catch(() => ({ items: [] as SourceStatsItem[] })),
    ])
    sources.value = list
    const next: Record<number, SourceStats> = {}
    for (const it of statsRes.items) {
      next[it.source_id] = { doc_count: it.doc_count, last_run: it.last_run }
    }
    statsMap.value = next
  } catch { /* 拦截器已提示 */ }
}
async function loadRuns() {
  loadingRuns.value = true
  try { runs.value = await listRuns({ limit: 50 }) } finally { loadingRuns.value = false }
}
async function loadFailures() {
  loadingFail.value = true
  try { failures.value = await listFailures({ limit: 50 }) } finally { loadingFail.value = false }
}
async function loadLogs() {
  loadingLogs.value = true
  try { logs.value = await listLogs({ limit: 500 }) } finally { loadingLogs.value = false }
}

async function retryOne(id: number) {
  try { await retryFailure(id); ElMessage.success('正在重试该失败项'); await refresh() }
  catch { /* 拦截器已提示 */ }
}
async function retryAll() {
  if (!failures.value.length) { ElMessage.warning('没有待重试的失败项'); return }
  try { await retryAllFailures(); ElMessage.success(`正在重试 ${failures.value.length} 个失败项`); await refresh() }
  catch { /* 拦截器已提示 */ }
}

defineExpose({ refresh })
let pollTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false
async function poll() {
  try { await refresh() } catch { /* 拦截器已提示 */ }
  finally {
    if (disposed) return
    // 动态轮询：有运行中任务 5s 高频盯进度；全部空闲降为 30s 低频巡检
    const hasRunning = Object.values(statsMap.value).some((st) => st.last_run?.status === 'running')
      || runs.value.some((r) => r.status === 'running')
    pollTimer = setTimeout(poll, hasRunning ? 5000 : 30000)
  }
}
onMounted(poll)
onBeforeUnmount(() => { disposed = true; clearTimeout(pollTimer) })
</script>

<template>
  <div>
    <!-- ① 失败清单 -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <h3 style="margin:0">失败清单（待处理）</h3>
      <el-button size="small" @click="retryAll">全部重试</el-button>
    </div>
    <el-table :data="failures" v-loading="loadingFail" size="small" border style="margin-bottom:18px">
      <el-table-column label="时间" width="150">
        <template #default="{ row }"><span style="font-size:12px">{{ formatDate(row.created_at) }}</span></template>
      </el-table-column>
      <el-table-column label="同步源" width="130">
        <template #default="{ row }">{{ sourceName(row.source_id) }}</template>
      </el-table-column>
      <el-table-column label="文档" min-width="140">
        <template #default="{ row }">{{ row.name || row.node_id || '—' }}</template>
      </el-table-column>
      <el-table-column label="错误原因" min-width="220">
        <template #default="{ row }"><span style="font-size:12px;color:var(--el-text-color-secondary)">{{ row.error }}</span></template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default><StatusPill status="err" /></template>
      </el-table-column>
      <el-table-column label="操作" width="80">
        <template #default="{ row }"><el-button size="small" link type="primary" @click="retryOne(row.id)">重试</el-button></template>
      </el-table-column>
      <template #empty><div style="padding:16px;color:var(--el-text-color-secondary)">暂无待处理失败，全部同步正常</div></template>
    </el-table>

    <!-- ② 同步历史 -->
    <h3 style="margin:0 0 8px">同步历史</h3>
    <el-table :data="runs" v-loading="loadingRuns" size="small" border style="margin-bottom:18px">
      <el-table-column label="开始时间" width="150">
        <template #default="{ row }"><span style="font-size:12px">{{ formatDate(row.started_at) }}</span></template>
      </el-table-column>
      <el-table-column label="触发" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.trigger === 'manual' ? 'warning' : 'info'">{{ row.trigger === 'manual' ? '手动' : '定时' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="同步源" min-width="120">
        <template #default="{ row }">{{ sourceName(row.source_id) }}</template>
      </el-table-column>
      <el-table-column label="耗时" width="90">
        <template #default="{ row }"><span style="font-size:12px">{{ dur(row) }}</span></template>
      </el-table-column>
      <el-table-column label="新增" width="60" prop="created_count" />
      <el-table-column label="更新" width="60" prop="updated_count" />
      <el-table-column label="删除" width="60" prop="deleted_count" />
      <el-table-column label="跳过" width="60">
        <template #default="{ row }">{{ skippedOf(row) }}</template>
      </el-table-column>
      <el-table-column label="失败" width="60">
        <template #default="{ row }"><span :style="row.failed_count ? 'color:var(--el-color-danger)' : ''">{{ row.failed_count }}</span></template>
      </el-table-column>
      <el-table-column label="结果" width="90">
        <template #default="{ row }"><StatusPill :status="row.status" /></template>
      </el-table-column>
      <template #empty><div style="padding:16px;color:var(--el-text-color-secondary)">暂无同步历史</div></template>
    </el-table>

    <!-- ③ 运行日志 -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <h3 style="margin:0">运行日志</h3>
      <div style="display:flex;gap:8px">
        <el-select v-model="lv" placeholder="全部级别" clearable size="small" style="width:120px">
          <el-option label="info" value="info" /><el-option label="warn" value="warn" /><el-option label="error" value="error" />
        </el-select>
        <el-input v-model="srcKeyword" placeholder="关键字" clearable size="small" style="width:140px" />
        <el-select v-model="date" placeholder="全部时间" clearable size="small" style="width:140px">
          <el-option label="今天" value="今天" /><el-option label="最近 3 天" value="最近 3 天" /><el-option label="最近 7 天" value="最近 7 天" />
        </el-select>
      </div>
    </div>
    <div v-loading="loadingLogs" style="border:1px solid var(--el-border-color);border-radius:6px;max-height:360px;overflow:auto;background:var(--el-fill-color-blank)">
      <div v-if="!filteredLogs.length" style="padding:20px;color:var(--el-text-color-secondary);text-align:center">无匹配日志</div>
      <div v-for="l in filteredLogs" :key="l.id" style="display:flex;gap:10px;padding:6px 12px;border-bottom:1px solid var(--el-border-color-lighter);font-size:12px">
        <span style="color:var(--el-text-color-secondary);min-width:130px">{{ formatDate(l.created_at) }}</span>
        <el-tag size="small" :type="lvClass(l.level)" style="min-width:50px;text-align:center">{{ l.level.toLowerCase() }}</el-tag>
        <span style="flex:1;word-break:break-all">{{ l.message }}</span>
      </div>
    </div>
  </div>
</template>
