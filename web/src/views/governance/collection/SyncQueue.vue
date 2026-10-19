<script setup lang="ts">
// 同步队列：知识同步过程的逐文档任务列表。
// 三个页签（待处理/处理中/已完成）+ 筛选（同步源/文档类型/执行结果/处理时长/名称/时间）
// + 批量管理（批量重试/批量清理）+ 失败任务级重试（只重处理单个钉钉节点，不整源重跑）。
// 清理：任意非「处理中」状态的任务均可清理（成功/失败/待处理）；未同步完成的任务
// 清理时联动把映射置为不参与自动同步（防下轮编目重建），已同步的知识不受影响。
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { TableInstance } from 'element-plus'
import { ArrowDown, ArrowUp, Collection as CollectionIcon, Refresh } from '@element-plus/icons-vue'
import KgPagination from '@/components/common/KgPagination.vue'
import { batchDeleteAllTasks, batchDeleteTasks, batchRetryTasks, fetchTaskStats, listSources, listTasks, retryTask } from '@/api/sync'
import type { Source, SyncTask } from '@/types/sync'
import { formatDate, formatFileSize } from '@/utils/format'

const router = useRouter()

// ===== 页签与列表 =====
const activeTab = ref<'pending' | 'running' | 'done'>('done')
const tabs = ref({ pending: 0, running: 0, done: 0 })
const items = ref<SyncTask[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const selection = ref<SyncTask[]>([])
const tableRef = ref<TableInstance>()
const sources = ref<Source[]>([])

/**
 * 彻底清空勾选：必须同时清表格组件内部状态与 selection。
 * 勾选列开启了 reserve-selection（跨页/跨刷新按 row-key 保留勾选），
 * 只重置 selection 变量不会取消表格内部的保留记录，数据刷新后
 * Element Plus 会把历史上勾过、且未被本次操作覆盖的所有行重新回填，
 * 造成「弹窗数量累计膨胀」。
 */
function clearSelectionAll() {
  tableRef.value?.clearSelection()
  selection.value = []
}

// ===== 筛选 =====
const filters = ref<{ source_id?: number; ext: string; status: string; duration: string }>({
  source_id: undefined, ext: '', status: '', duration: '',
})
const advanced = ref<{ keyword: string; range: [string, string] | null }>({ keyword: '', range: null })
const expanded = ref(false)

const EXT_OPTIONS = ['docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt', 'pdf', 'md', 'txt', 'csv', 'adoc', 'axls', 'able']
const DURATION_OPTIONS = [
  { label: '10 秒内', value: 'lt10' },
  { label: '10 秒 ~ 1 分钟', value: '10_60' },
  { label: '1 ~ 5 分钟', value: '60_300' },
  { label: '5 分钟以上', value: 'gt300' },
]

const STATUS_TEXT: Record<string, string> = { pending: '待处理', running: '处理中', success: '成功', failed: '失败' }
const STATUS_TAG: Record<string, 'success' | 'danger' | 'warning' | 'info'> = {
  pending: 'info', running: 'warning', success: 'success', failed: 'danger',
}
const ACTION_TEXT: Record<string, string> = { create: '新建', update: '更新', delete: '删除' }

function formatDuration(sec: number | null | undefined, status: string): string {
  if (status === 'running') return '处理中…'
  if (status === 'pending' || sec == null) return '-'
  if (sec < 60) return `${sec} 秒`
  const m = Math.floor(sec / 60)
  return `${m} 分 ${sec % 60} 秒`
}

// ===== 加载 =====
async function load() {
  loading.value = true
  try {
    const res = await listTasks({
      tab: activeTab.value,
      status: filters.value.status,
      source_id: filters.value.source_id,
      ext: filters.value.ext,
      duration: filters.value.duration,
      keyword: advanced.value.keyword,
      start_from: advanced.value.range?.[0] || '',
      start_to: advanced.value.range?.[1] || '',
      page: page.value,
      size: size.value,
    })
    items.value = res.items
    total.value = res.total
    tabs.value = res.tabs
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function reset() {
  filters.value = { source_id: undefined, ext: '', status: '', duration: '' }
  advanced.value = { keyword: '', range: null }
  page.value = 1
  load()
}

function onTabChange() {
  clearSelectionAll()
  page.value = 1
  load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

function onSizeChange(s: number) {
  size.value = s
  page.value = 1
  load()
}

function goLibrary() {
  router.push('/apply/knowledge-libraries')
}

// ===== 重试 / 批量 =====
async function retryOne(row: SyncTask) {
  try {
    const res = await retryTask(row.id) as { message?: string }
    ElMessage.success(res?.message || '重试已提交')
    load()
  } catch { /* 拦截器已提示 */ }
}

function retryableIds(): number[] {
  return selection.value.filter((t) => t.status === 'failed').map((t) => t.id)
}

function deletableIds(): number[] {
  return selection.value
    .filter((t) => t.status !== 'running')
    .map((t) => t.id)
}

async function batchRetry() {
  const ids = retryableIds()
  if (!ids.length) {
    ElMessage.warning('请先勾选失败任务')
    return
  }
  try {
    const res = await batchRetryTasks(ids)
    ElMessage.success(res.message)
    clearSelectionAll()
    load()
  } catch { /* 拦截器已提示 */ }
}

/** 含未同步完成（待处理/失败）任务时的清理提示：这些文档会停止自动同步 */
function deleteConfirmText(ids: number[]): string {
  const unsynced = selection.value
    .filter((t) => t.status !== 'running' && t.status !== 'success').length
  if (unsynced > 0) {
    return `将清理 ${ids.length} 个任务；其中 ${unsynced} 个尚未同步完成，对应文档将停止自动同步（如需恢复，请在「钉钉知识同步 → 同步列表」重新开启）；已同步的知识不受影响。是否继续？`
  }
  return `将清理 ${ids.length} 个已结束的任务记录；已同步的知识不受影响。是否继续？`
}

async function batchDelete() {
  const ids = deletableIds()
  if (!ids.length) {
    ElMessage.warning('请先勾选要清理的任务（处理中的除外）')
    return
  }
  try {
    await ElMessageBox.confirm(
      deleteConfirmText(ids),
      '删除选中', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const res = await batchDeleteTasks(ids)
    ElMessage.success(res.message)
    clearSelectionAll()
    load()
  } catch { /* 拦截器已提示 */ }
}

/** 删除所有：当前页签+筛选条件命中的全部任务（含未翻到的页），处理中的除外 */
async function deleteAll() {
  if (activeTab.value === 'running') return
  const scopeText = filters.value.status === 'success'
    ? '已成功'
    : filters.value.status === 'failed' ? '失败' : '全部已结束'
  try {
    await ElMessageBox.confirm(
      `将删除当前范围内（${scopeText}，共 ${total.value} 个）的全部任务记录，含未翻到的页；处理中的不受影响。`
      + '未同步完成的文档将停止自动同步；已同步的知识不受影响。是否继续？',
      '删除所有', { type: 'warning', confirmButtonText: '全部删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const res = await batchDeleteAllTasks({
      tab: activeTab.value,
      status: filters.value.status,
      source_id: filters.value.source_id,
      ext: filters.value.ext,
      duration: filters.value.duration,
      keyword: advanced.value.keyword,
      start_from: advanced.value.range?.[0] || '',
      start_to: advanced.value.range?.[1] || '',
    })
    ElMessage.success(res.message)
    clearSelectionAll()
    load()
  } catch { /* 拦截器已提示 */ }
}

/** 批量管理下拉分发 */
function onBatchCommand(cmd: string | number | object) {
  if (cmd === 'retry') batchRetry()
  else if (cmd === 'delete-selected') batchDelete()
  else if (cmd === 'delete-all') deleteAll()
}

async function removeOne(row: SyncTask) {
  try {
    await ElMessageBox.confirm(
      row.status === 'success'
        ? '将清理该条任务记录；已同步的知识不受影响。是否继续？'
        : '将清理该任务；尚未同步完成的文档将停止自动同步（如需恢复，请在「钉钉知识同步 → 同步列表」重新开启）。是否继续？',
      '清理任务', { type: 'warning', confirmButtonText: '清理', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const res = await batchDeleteTasks([row.id])
    ElMessage.success(res.message)
    tableRef.value?.toggleRowSelection(row, false)
    load()
  } catch { /* 拦截器已提示 */ }
}

// ===== 轮询：页签计数每 5s 实时刷新（轻量 stats 接口）；列表仅在有排队任务且未勾选时刷新 =====
let pollTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false
function schedulePoll() {
  pollTimer = setTimeout(async () => {
    if (disposed) return
    // 页签计数始终实时：轻量 stats 轮询与列表解耦，勾选/空闲/任意页签都刷新。
    // 列表本体仍只在有排队任务且未勾选时自动刷新（避免干扰浏览与勾选）。
    fetchTaskStats().then((s) => { tabs.value = s }).catch(() => { /* 下轮重试 */ })
    if ((tabs.value.pending + tabs.value.running > 0) && !selection.value.length && !loading.value) {
      await load()
    }
    schedulePoll()
  }, 5000)
}

onMounted(async () => {
  listSources().then((list) => { sources.value = list }).catch(() => { /* 拦截器已提示 */ })
  await load()
  // 首次进入：有排队中的任务（如新编目的自动同步）默认停在「待处理」页签
  if (tabs.value.pending > 0 && activeTab.value === 'done') {
    activeTab.value = 'pending'
    page.value = 1
    await load()
  }
  schedulePoll()
})
onBeforeUnmount(() => {
  disposed = true
  clearTimeout(pollTimer)
})
</script>

<template>
  <div class="kge-page queue-page">
    <el-card shadow="never" class="queue-card">
      <!-- 页签 -->
      <el-tabs v-model="activeTab" class="queue-tabs" @tab-change="onTabChange">
        <el-tab-pane name="pending">
          <template #label>
            待处理<span v-if="tabs.pending" class="tab-count">（{{ tabs.pending }}）</span>
          </template>
        </el-tab-pane>
        <el-tab-pane name="running">
          <template #label>
            处理中<span v-if="tabs.running" class="tab-count">（{{ tabs.running }}）</span>
          </template>
        </el-tab-pane>
        <el-tab-pane name="done">
          <template #label>
            已完成<span v-if="tabs.done" class="tab-count">（{{ tabs.done }}）</span>
          </template>
        </el-tab-pane>
      </el-tabs>

      <!-- 筛选栏：默认一行 3 个过滤器；次要项折叠进展开区；
           查询/重置与展开开关固定在第一行右侧，展开时位置不动 -->
      <div class="filter-bar" :class="{ expanded }">
        <el-form inline class="filter-fields" label-width="68px" @submit.prevent>
          <el-form-item label="同步源">
            <el-select v-model="filters.source_id" placeholder="全部同步源" clearable style="width: 220px">
              <el-option v-for="s in sources" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="文档类型">
            <el-select v-model="filters.ext" placeholder="全部类型" clearable style="width: 220px">
              <el-option v-for="e in EXT_OPTIONS" :key="e" :label="`.${e}`" :value="e" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="activeTab === 'done'" label="执行结果">
            <el-select v-model="filters.status" placeholder="全部结果" clearable style="width: 220px">
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
            </el-select>
          </el-form-item>
          <el-form-item label="处理时长" class="fi-extra">
            <el-select v-model="filters.duration" placeholder="全部时长" clearable style="width: 220px">
              <el-option v-for="d in DURATION_OPTIONS" :key="d.value" :label="d.label" :value="d.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="任务名称" class="fi-extra">
            <el-input v-model="advanced.keyword" placeholder="按文档名称搜索" clearable style="width: 220px"
                      @keyup.enter="search" />
          </el-form-item>
          <el-form-item label="开始时间" class="fi-extra">
            <el-date-picker v-model="advanced.range" type="daterange" value-format="YYYY-MM-DD"
                            start-placeholder="开始日期" end-placeholder="结束日期" style="width: 220px" />
          </el-form-item>
        </el-form>
        <div class="filter-actions">
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="reset">重置</el-button>
          <el-button link type="primary" @click="expanded = !expanded">
            {{ expanded ? '收起' : '展开' }}<el-icon class="el-icon--right"><ArrowUp v-if="expanded" /><ArrowDown v-else /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- 批量管理：批量重试/删除选中/删除所有收进同一下拉 -->
      <div class="batch-bar">
        <el-dropdown popper-class="batch-mgmt-dropdown" @command="onBatchCommand">
          <el-button>
            批量管理<el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="retry" :disabled="!retryableIds().length">批量重试</el-dropdown-item>
              <el-dropdown-item command="delete-selected" :disabled="!selection.length" class="danger-item">
                删除选中
              </el-dropdown-item>
              <el-dropdown-item command="delete-all" :disabled="activeTab === 'running' || !total" class="danger-item">
                删除所有
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <span v-if="selection.length" class="batch-hint">已选 {{ selection.length }} 个任务</span>
        <el-button link type="primary" class="refresh-btn" :icon="Refresh" @click="load">刷新</el-button>
      </div>

      <!-- 任务表 -->
      <div class="table-fill">
      <el-table ref="tableRef" :data="items" v-loading="loading" border size="small" row-key="id" height="100%"
                @selection-change="(rows: unknown[]) => (selection = rows as SyncTask[])">
        <el-table-column type="selection" width="42" reserve-selection />
        <el-table-column label="任务名称" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag size="small" :type="row.action === 'delete' ? 'warning' : 'info'" class="action-tag">
              {{ ACTION_TEXT[row.action] || row.action }}
            </el-tag>
            <span class="task-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="文档类型" width="88">
          <template #default="{ row }">{{ row.file_ext ? `.${row.file_ext}` : '-' }}</template>
        </el-table-column>
        <el-table-column label="文件大小" width="90">
          <template #default="{ row }">{{ formatFileSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="关联知识" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link v-if="row.dataset_name" type="primary" :underline="false" @click="goLibrary">
              <el-icon style="vertical-align: -2px"><CollectionIcon /></el-icon>
              {{ row.dataset_name }}
            </el-link>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="同步源" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.source_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="触发方式" width="88">
          <template #default="{ row }">
            <el-tag size="small" :type="row.trigger === 'manual' ? 'warning' : 'info'" effect="plain">
              {{ row.trigger === 'manual' ? '手动' : '自动' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="执行结果" width="100">
          <template #default="{ row }">
            <el-tooltip v-if="row.status === 'failed'" placement="top" :show-after="200">
              <template #content>
                <div style="max-width: 360px">
                  {{ row.error || '未知错误' }}
                  <div v-if="row.retry_count">已重试 {{ row.retry_count }} 次</div>
                </div>
              </template>
              <el-tag size="small" :type="STATUS_TAG[row.status]">{{ STATUS_TEXT[row.status] }}</el-tag>
            </el-tooltip>
            <el-tag v-else size="small" :type="STATUS_TAG[row.status]">{{ STATUS_TEXT[row.status] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="处理时长" width="96">
          <template #default="{ row }">{{ formatDuration(row.duration_sec, row.status) }}</template>
        </el-table-column>
        <el-table-column label="开始时间" width="140">
          <template #default="{ row }">{{ formatDate(row.started_at || row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作人" width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ row.operator || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'failed'" link type="primary" size="small" @click="retryOne(row as SyncTask)">重试</el-button>
            <el-button v-if="row.status !== 'running'" link type="danger" size="small" @click="removeOne(row as SyncTask)">清理</el-button>
            <span v-if="row.status === 'running'" class="op-none">-</span>
          </template>
        </el-table-column>
        <template #empty>
          <div class="queue-empty">
            <p>暂无任务记录</p>
            <span>队列自下一次钉钉同步运行起逐文档记录任务；失败任务可在本页重试。</span>
          </div>
        </template>
      </el-table>
      </div>

      <!-- 分页 -->
      <KgPagination :page="page" :size="size" :total="total" :sizes="[20, 50, 100]"
                    layout="total, sizes, prev, pager, next"
                    @update:page="onPageChange" @update:size="onSizeChange" />
    </el-card>
  </div>
</template>

<style scoped>
/* 卡片撑满页面剩余高度：页签/筛选/批量栏/分页固定，表格撑满（表体内部滚动、表头吸顶） */
.queue-card {
  border-radius: 12px;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.queue-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.queue-tabs {
  flex-shrink: 0;
}

.queue-tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.tab-count {
  color: var(--el-color-primary);
  font-size: 12px;
}

.filter-bar {
  margin-top: 4px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-shrink: 0;
}

.filter-fields {
  display: flex;
  flex-wrap: wrap;
  flex: 0 1 auto;
  min-width: 0;
}

.filter-fields :deep(.el-form-item) {
  margin-bottom: 10px;
}

/* 次要过滤器：收起时隐藏（display:none 不占位，查询/重置位置不动），展开时随行排布 */
.filter-bar:not(.expanded) .fi-extra {
  display: none;
}

/* 查询/重置/展开开关：固定第一行右侧（flex-start 顶部对齐），展开后位置不动 */
.filter-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0;
  padding-top: 4px;
  flex-shrink: 0;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-shrink: 0;
}

.batch-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.refresh-btn {
  margin-left: auto;
}

.action-tag {
  margin-right: 6px;
}

.task-name {
  font-weight: 600;
}

.op-none {
  color: var(--el-text-color-placeholder);
}

.queue-empty {
  padding: 28px 16px;
  color: var(--el-text-color-secondary);
}

.queue-empty p {
  margin: 0 0 6px;
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.queue-empty span {
  font-size: 12px;
}

.table-fill {
  flex: 1;
  min-height: 0;
}
</style>

<style>
/* 批量管理下拉菜单（popper teleport 到 body，须用非 scoped 样式） */
.batch-mgmt-dropdown .danger-item {
  color: var(--el-color-danger);
}
</style>
