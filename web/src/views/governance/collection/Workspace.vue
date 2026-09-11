<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatDate } from '@/utils/format'
import { listSources, sourceStats, syncSource } from '@/api/sync'
import type { Run, Source, SourceStats } from '@/types/sync'
import StatusPill from './components/StatusPill.vue'

const sources = ref<Source[]>([])
const stats = ref<Record<number, SourceStats>>({})
const loading = ref(false)
const polling = ref<number | null>(null)
const emit = defineEmits<{ (e: 'refresh-monitor'): void }>()

function lastRun(sourceId: number): Run | null { return stats.value[sourceId]?.last_run || null }
function isRunning(sourceId: number) { return lastRun(sourceId)?.status === 'running' }
function result(run: Run | null) {
  if (!run) return '—'
  return `新 ${run.created_count} / 更 ${run.updated_count} / 删 ${run.deleted_count} / 败 ${run.failed_count}`
}

async function refresh() {
  if (loading.value) return
  loading.value = true
  try {
    sources.value = await listSources()
    const entries = await Promise.all(sources.value.map(async (source) => [source.id, await sourceStats(source.id)] as const))
    stats.value = Object.fromEntries(entries)
    const hasRunning = sources.value.some((source) => isRunning(source.id))
    if (hasRunning && polling.value === null) polling.value = window.setInterval(refresh, 3000)
    if (!hasRunning && polling.value !== null) { window.clearInterval(polling.value); polling.value = null }
  } finally { loading.value = false }
}

async function run(source: Source) {
  if (!source.enabled || isRunning(source.id)) return
  const count = stats.value[source.id]?.doc_count
  try {
    await ElMessageBox.confirm(
      `即将同步知识到 Dify 知识库，一共 ${count ?? '—'} 个文档，是否立即启动？`,
      '确认立即同步', { confirmButtonText: '立即启动', cancelButtonText: '取消', type: 'warning' },
    )
    await syncSource(source.id)
    ElMessage.success(`「${source.name}」同步任务已启动，可在运行监控中查看结果`)
    // 在服务端创建运行记录前即显示运行中，随后轮询最新统计结果。
    stats.value[source.id] = { ...(stats.value[source.id] || { doc_count: null }), last_run: {
      id: -source.id, source_id: source.id, trigger: 'manual', status: 'running', started_at: new Date().toISOString(),
      finished_at: null, total: 0, created_count: 0, updated_count: 0, deleted_count: 0, failed_count: 0, message: '',
    } }
    if (polling.value === null) polling.value = window.setInterval(refresh, 3000)
    emit('refresh-monitor')
  } catch (error) {
    if (error !== 'cancel') { /* request interceptor displays API errors */ }
  }
}

defineExpose({ refresh })
onMounted(refresh)
onBeforeUnmount(() => { if (polling.value !== null) window.clearInterval(polling.value) })
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div><h3 style="margin:0 0 4px">同步工作台</h3><div style="font-size:12px;color:var(--el-text-color-secondary)">在这里启动同步并实时查看本次结果</div></div>
      <el-button size="small" @click="refresh">刷新</el-button>
    </div>
    <el-table :data="sources" v-loading="loading" border size="small">
      <el-table-column label="同步源" min-width="150"><template #default="{ row }"><b>{{ row.name }}</b></template></el-table-column>
      <el-table-column label="Dify 知识库" min-width="150" prop="dify_dataset_name" />
      <el-table-column label="文档数" width="90"><template #default="{ row }">{{ stats[row.id]?.doc_count ?? '—' }}</template></el-table-column>
      <el-table-column label="本次同步结果" min-width="180"><template #default="{ row }"><span :style="lastRun(row.id)?.failed_count ? 'color:var(--el-color-danger)' : ''">{{ result(lastRun(row.id)) }}</span></template></el-table-column>
      <el-table-column label="当前阶段 / 结果说明" min-width="260" show-overflow-tooltip><template #default="{ row }">{{ lastRun(row.id)?.message || '—' }}</template></el-table-column>
      <el-table-column label="同步开始时间" width="165"><template #default="{ row }">{{ lastRun(row.id) ? formatDate(lastRun(row.id)!.started_at) : '—' }}</template></el-table-column>
      <el-table-column label="同步结束时间" width="165"><template #default="{ row }">{{ lastRun(row.id)?.finished_at ? formatDate(lastRun(row.id)!.finished_at!) : '—' }}</template></el-table-column>
      <el-table-column label="状态 / 操作" width="165" fixed="right"><template #default="{ row }"><StatusPill :status="lastRun(row.id)?.status || (row.enabled ? 'enabled' : 'disabled')" /><el-button size="small" link type="primary" :disabled="!row.enabled || isRunning(row.id)" @click="run(row as Source)">{{ isRunning(row.id) ? '同步中' : '立即同步' }}</el-button></template></el-table-column>
      <template #empty><div style="padding:24px;color:var(--el-text-color-secondary)">暂无同步源，请先在“同步源管理”中创建</div></template>
    </el-table>
  </div>
</template>
