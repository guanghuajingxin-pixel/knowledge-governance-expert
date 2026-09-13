<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { deleteSource, listSources, previewSource, sourcesStatsAll, syncSource, updateSource } from '@/api/sync'
import type { SourceStatsItem } from '@/api/sync'
import type { PreviewItem, Source, SourceStats, Workspace } from '@/types/sync'
import { listWorkspaces } from '@/api/sync'
import StatusPill from './components/StatusPill.vue'
import SourceFormDialog from './components/SourceFormDialog.vue'
import PreviewDialog from './components/PreviewDialog.vue'
import { cronLabel } from './components/cron'

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
const previewLoading = ref(false)

const emit = defineEmits<{ (e: 'refresh-monitor'): void }>()

function statusOf(s: any) { return s.enabled ? 'ok' : 'off' }
function docsOf(id: number) { return statsMap.value[id]?.doc_count ?? '—' }
function workspaceName(id: string) { return workspaces.value.find((w) => w.workspaceId === id)?.name || id }
function isRunning(id: number) { return statsMap.value[id]?.last_run?.status === 'running' }

async function refresh(silent = false) {
  if (loading.value) return
  if (!silent) loading.value = true
  try {
    // 一次并发拿回：源列表 + 全部源的统计（原先还要逐源请求 /sources/{id}/stats，
    // N 个源就是 N 个请求，运行中每 3 秒重复一轮，后端连接池会被瞬间打满）
    // 知识库名称仅用于展示，静默轮询且本地已有时不再重复拉（钉钉侧接口较重）
    const needWs = !silent || workspaces.value.length === 0
    const [list, statsRes, ws] = await Promise.all([
      listSources(),
      sourcesStatsAll().catch(() => ({ items: [] as SourceStatsItem[] })),
      needWs ? listWorkspaces().catch(() => []) : Promise.resolve(workspaces.value),
    ])
    const next: Record<number, SourceStats> = {}
    for (const it of statsRes.items) {
      next[it.source_id] = { doc_count: it.doc_count, last_run: it.last_run }
    }
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
    // 启用 → 停用：二次确认；停用 → 启用：直接执行
    if (s.enabled) {
      await ElMessageBox.confirm(`确定停用同步任务「${s.name}」吗？停用后不参与定时同步，也无法立即同步。`, '停用同步任务', {
        confirmButtonText: '确定停用', cancelButtonText: '取消', type: 'warning',
      })
    }
    await updateSource(s.id, { enabled: !s.enabled })
    ElMessage.success(`已${s.enabled ? '停用' : '启用'}「${s.name}」`)
    await refresh()
  } catch { /* 取消或拦截器已提示 */ }
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
  if (previewLoading.value) return
  // 点击立即弹窗，加载在弹窗内等待（行内按钮不转圈）
  previewSourceObj.value = s
  previewItems.value = []
  previewVisible.value = true
  previewLoading.value = true
  try {
    // 服务端目录树快照缓存 10 分钟，命中秒回；未命中并发遍历（≤3）。
    previewItems.value = await previewSource(s.id)
  } catch {
    previewVisible.value = false // 加载失败直接收起弹窗，错误由拦截器提示
  } finally {
    previewLoading.value = false
  }
}
async function refreshPreview() {
  // 强制刷新：绕过服务端缓存重新遍历钉钉目录树，在弹窗内等待；
  // 保留用户在弹窗里已调整的「参与同步」开关状态
  const s = previewSourceObj.value
  if (!s || previewLoading.value) return
  previewLoading.value = true
  try {
    const enabledMap = new Map(previewItems.value
      .filter((item) => item.node_id)
      .map((item) => [item.node_id!, item.enabled !== false]))
    previewItems.value = (await previewSource(s.id, true)).map((item) =>
      item.node_id && enabledMap.has(item.node_id)
        ? { ...item, enabled: enabledMap.get(item.node_id) ?? true }
        : item)
    ElMessage.success('列表已刷新')
  } catch { /* 拦截器已提示 */ } finally {
    previewLoading.value = false
  }
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

function onMore(command: string, row: Source) {
  if (command === 'toggle') toggle(row)
  else if (command === 'edit') openEdit(row)
  else if (command === 'delete') remove(row)
}

onMounted(refresh)
onBeforeUnmount(() => { if (polling.value !== null) { window.clearInterval(polling.value); polling.value = null } })
</script>

<template>
  <div>
    <div class="sec-header">
      <b class="sec-title">从钉钉选择目录</b>
      <span class="sec-hint">维护钉钉知识库目录与目标知识库的映射，每个目录可独立配置定时同步</span>
      <el-button type="primary" style="margin-left:auto" @click="openAdd">+ 新增同步任务</el-button>
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
      <el-table-column label="目标知识库" min-width="120">
        <template #default="{ row }">
          <span style="font-size:12px">{{ row.dify_dataset_name || row.start_dir || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="定时任务" width="150">
        <template #default="{ row }">
          <span style="font-size:12px">{{ cronLabel(row.cron) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="70">
        <template #default="{ row }"><StatusPill :status="statusOf(row)" /></template>
      </el-table-column>
      <el-table-column label="文档数" width="70">
        <template #default="{ row }">{{ docsOf(row.id) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <div class="ops">
            <el-button size="small" link type="primary" :disabled="!row.enabled || isRunning(row.id)" @click="runNow(row as Source)">{{ isRunning(row.id) ? '同步中' : '立即同步' }}</el-button>
            <el-button size="small" link @click="preview(row)">同步列表</el-button>
            <el-dropdown trigger="click" @command="(cmd: string) => onMore(cmd, row as Source)">
              <el-button size="small" link>更多<el-icon style="margin-left:2px"><ArrowDown /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="toggle">{{ row.enabled ? '停用' : '启用' }}</el-dropdown-item>
                  <el-dropdown-item command="edit">编辑</el-dropdown-item>
                  <el-dropdown-item command="delete" divided style="color:var(--el-color-danger)">删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </template>
      </el-table-column>
      <template #empty><div style="padding:24px;color:var(--el-text-color-secondary)">暂无同步源，点击右上角新增</div></template>
    </el-table>

    <SourceFormDialog v-model:visible="formVisible" :source="editingSource" @saved="onSaved" />
    <PreviewDialog v-model:visible="previewVisible" :source-id="previewSourceObj?.id || 0" :name="previewSourceObj?.name || ''" :items="previewItems" :loading="previewLoading" @refresh="refreshPreview" @done="onPreviewDone" />
  </div>
</template>

<style scoped>
/* 标题行：与「文档同步」卡片头部一致的单行布局 */
.sec-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.sec-title {
  font-size: 14px;
}
.sec-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
/* 操作列：flex 布局 + 统一间距，保证各行动作水平对齐 */
.ops {
  display: flex;
  align-items: center;
  gap: 12px;
}
.ops .el-button + .el-button {
  margin-left: 0; /* 覆盖 Element Plus 相邻按钮默认 12px margin，统一用 gap 控制 */
}
</style>
