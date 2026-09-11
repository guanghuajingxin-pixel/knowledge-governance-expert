<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteSource, listSources, previewSource, sourceStats, syncSource, updateSource } from '@/api/sync'
import type { PreviewItem, Source, SourceStats, Workspace } from '@/types/sync'
import { listWorkspaces } from '@/api/sync'
import StatusPill from './components/StatusPill.vue'
import SourceFormDialog from './components/SourceFormDialog.vue'
import PreviewDialog from './components/PreviewDialog.vue'

const sources = ref<Source[]>([])
const workspaces = ref<Workspace[]>([])
const statsMap = ref<Record<number, SourceStats>>({})
const loading = ref(false)
const polling = ref<number | null>(null)

const formVisible = ref(false)
const editingSource = ref<Source | null>(null)
const previewVisible = ref(false)
const previewItems = ref<PreviewItem[]>([])
const previewSourceObj = ref<Source | null>(null)

const emit = defineEmits<{ (e: 'refresh-monitor'): void }>()

function statusOf(s: any) { return s.enabled ? 'ok' : 'off' }
function docsOf(id: number) { return statsMap.value[id]?.doc_count ?? '—' }
function workspaceName(id: string) { return workspaces.value.find((w) => w.workspaceId === id)?.name || id }
function isRunning(id: number) { return statsMap.value[id]?.last_run?.status === 'running' }

async function refresh(silent = false) {
  if (loading.value) return
  if (!silent) loading.value = true
  try {
    const list = await listSources()
    const ws = await listWorkspaces().catch(() => [])
    const next: Record<number, SourceStats> = {}
    await Promise.all(list.map(async (s) => {
      try { next[s.id] = await sourceStats(s.id) } catch { /* ignore */ }
    }))
    sources.value = list
    workspaces.value = ws
    statsMap.value = next
    // 有运行中任务时启动 3s 轮询，全部结束后自动停止（按钮恢复“立即同步”）。
    const hasRunning = list.some((s) => isRunning(s.id))
    if (hasRunning && polling.value === null) polling.value = window.setInterval(() => refresh(true), 3000)
    if (!hasRunning && polling.value !== null) { window.clearInterval(polling.value); polling.value = null }
  } finally { if (!silent) loading.value = false }
}

function openAdd() { editingSource.value = null; formVisible.value = true }
function openEdit(s: any) { editingSource.value = s; formVisible.value = true }
async function onSaved() { await refresh(); emit('refresh-monitor') }

async function toggle(s: any) {
  try {
    if (s.enabled) {
      await ElMessageBox.confirm(`确定停用同步源「${s.name}」吗？停用后不参与定时同步，也无法立即同步。`, '停用同步源', {
        confirmButtonText: '确定停用', cancelButtonText: '取消', type: 'warning',
      })
    }
    await updateSource(s.id, { enabled: !s.enabled })
    ElMessage.success(`已${s.enabled ? '停用' : '启用'}「${s.name}」`)
    await refresh()
  } catch { /* 拦截器已提示 */ }
}
async function remove(s: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除同步源「${s.name}」吗？其 Dify 知识库与已同步文档不会被删除，仅移除该同步配置。`,
      '删除同步源',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
    await deleteSource(s.id)
    ElMessage.success(`已删除同步源「${s.name}」（仅移除配置，Dify 文档保留）`)
    await refresh()
  } catch (e) { if (e !== 'cancel') { /* 拦截器已提示 */ } }
}
async function preview(s: any) {
  try {
    previewSourceObj.value = s
    previewItems.value = await previewSource(s.id)
    previewVisible.value = true
  } catch { /* 拦截器已提示 */ }
}
async function runNow(s: Source) {
  if (!s.enabled || isRunning(s.id)) return
  try {
    await ElMessageBox.confirm(
      `即将把「${s.name}」目录同步到 Dify，当前约 ${docsOf(s.id)} 个文档，是否启动？`,
      '确认立即同步',
      { confirmButtonText: '立即同步', cancelButtonText: '取消', type: 'warning' },
    )
    await syncSource(s.id)
    ElMessage.success(`「${s.name}」同步任务已启动`)
    // 服务端创建运行记录前先乐观显示“同步中”，随后轮询真实状态，完成后按钮自动恢复“立即同步”。
    statsMap.value[s.id] = { ...(statsMap.value[s.id] || { doc_count: null }), last_run: {
      id: -s.id, source_id: s.id, trigger: 'manual', status: 'running', started_at: new Date().toISOString(),
      finished_at: null, total: 0, created_count: 0, updated_count: 0, deleted_count: 0, failed_count: 0, message: '',
    } }
    if (polling.value === null) polling.value = window.setInterval(() => refresh(true), 3000)
    emit('refresh-monitor')
  } catch (error) {
    if (error !== 'cancel') { /* request interceptor displays API errors */ }
  }
}
function onPreviewDone() { refresh(); emit('refresh-monitor') }

onMounted(refresh)
onBeforeUnmount(() => { if (polling.value !== null) { window.clearInterval(polling.value); polling.value = null } })
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div>
        <h3 style="margin:0 0 4px">目录同步源</h3>
        <div style="font-size:12px;color:var(--el-text-color-secondary)">维护钉钉知识库目录与目标 Dify 知识库的映射；每个目录可独立配置 cron 定时同步</div>
      </div>
      <el-button type="primary" @click="openAdd">+ 新增同步源</el-button>
    </div>

    <el-table :data="sources" v-loading="loading" border size="small">
      <el-table-column label="名称" min-width="140">
        <template #default="{ row }"><b>{{ row.name }}</b></template>
      </el-table-column>
      <el-table-column label="钉钉知识库 / 起始目录" min-width="180">
        <template #default="{ row }">
          {{ workspaceName(row.workspace_id) }}
          <div style="color:var(--el-text-color-secondary);font-size:12px">{{ row.start_dir || '根目录' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="Dify 知识库" min-width="120">
        <template #default="{ row }">
          <span style="font-size:12px">{{ row.dify_dataset_name || row.start_dir || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="cron" width="130">
        <template #default="{ row }"><span style="font-size:12px">{{ row.cron }}</span></template>
      </el-table-column>
      <el-table-column label="状态" width="70">
        <template #default="{ row }"><StatusPill :status="statusOf(row)" /></template>
      </el-table-column>
      <el-table-column label="文档数" width="70">
        <template #default="{ row }">{{ docsOf(row.id) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="320" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" :disabled="!row.enabled || isRunning(row.id)" @click="runNow(row as Source)">{{ isRunning(row.id) ? '同步中' : '立即同步' }}</el-button>
          <el-button size="small" link @click="preview(row)">预演</el-button>
          <el-button size="small" link @click="openEdit(row)">编辑</el-button>
          <el-switch :model-value="row.enabled" inline-prompt active-text="启用" inactive-text="停用" style="margin:0 6px" @change="toggle(row)" />
          <el-button size="small" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty><div style="padding:24px;color:var(--el-text-color-secondary)">暂无同步源，点击右上角新增</div></template>
    </el-table>

    <SourceFormDialog v-model:visible="formVisible" :source="editingSource" @saved="onSaved" />
    <PreviewDialog v-model:visible="previewVisible" :source-id="previewSourceObj?.id || 0" :name="previewSourceObj?.name || ''" :items="previewItems" @done="onPreviewDone" />
  </div>
</template>
