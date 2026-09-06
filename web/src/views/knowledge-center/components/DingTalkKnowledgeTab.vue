<script setup lang="ts">
/**
 * 知识中心 - 钉钉知识
 * 实时拉取钉钉开放平台知识库文件，支持按知识库 / 创建人 / 目录过滤，手动刷新
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { Search, Refresh, Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { fetchDingTalkDocuments } from '@/api/knowledge-center'
import { formatDate, formatFileSize } from '@/utils/format'
import type { DingTalkFile, DingTalkOption } from '@/types/knowledge-center'

// 数据
const documents = ref<DingTalkFile[]>([])
const total = ref(0)
const loading = ref(false)        // 首次同步（无数据）时的全屏遮罩
const refreshing = ref(false)     // 后台遍历中（手动刷新按钮态）
const page = ref(1)
const size = ref(20)

// 后台遍历耗时较长时，按此间隔轮询
const POLL_INTERVAL = 12000
let pollTimer: ReturnType<typeof setTimeout> | null = null

// 过滤条件
const searchKeyword = ref('')
const directoryKeyword = ref('')
const wsFilter = ref<string[]>([])
const creatorFilter = ref<string[]>([])

// 下拉选项（来自后端聚合的完整集合）
const wsOptions = ref<DingTalkOption[]>([])
const creatorOptions = ref<DingTalkOption[]>([])

// 钉钉未配置等错误
const errorMsg = ref('')

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

async function loadDocs(forceRefresh = false, fromPoll = false) {
  if (!fromPoll) {
    errorMsg.value = ''
    if (documents.value.length === 0) loading.value = true
    if (forceRefresh) refreshing.value = true
  }
  try {
    const params: any = {
      page: page.value,
      size: size.value,
      refresh: forceRefresh || undefined,
    }
    if (searchKeyword.value) params.search = searchKeyword.value
    if (directoryKeyword.value) params.directory = directoryKeyword.value
    if (wsFilter.value.length) params.workspace_id = wsFilter.value.join(',')
    if (creatorFilter.value.length) params.creator_id = creatorFilter.value.join(',')

    const res = await fetchDingTalkDocuments(params)
    documents.value = res.items
    total.value = res.total
    wsOptions.value = res.workspaces || []
    creatorOptions.value = res.creators || []
    errorMsg.value = res.error || ''

    if (res.loading) {
      // 后台遍历中：无数据时保持遮罩，有数据时保持刷新按钮态，稍后轮询
      loading.value = documents.value.length === 0
      refreshing.value = true
      stopPolling()
      pollTimer = setTimeout(() => loadDocs(false, true), POLL_INTERVAL)
      return
    }

    // 后台遍历完成
    stopPolling()
    const wasRefreshing = refreshing.value
    loading.value = false
    refreshing.value = false
    if (forceRefresh || (wasRefreshing && fromPoll)) {
      ElMessage.success('钉钉知识库已刷新')
    }
  } catch (e: any) {
    stopPolling()
    loading.value = false
    refreshing.value = false
    errorMsg.value = e?.message || '钉钉数据拉取失败'
  }
}

function handleSearch() {
  page.value = 1
  loadDocs()
}

function handleReset() {
  searchKeyword.value = ''
  directoryKeyword.value = ''
  wsFilter.value = []
  creatorFilter.value = []
  page.value = 1
  loadDocs()
}

function handleRefresh() {
  page.value = 1
  loadDocs(true)
}

function handlePageChange(p: number) {
  page.value = p
  loadDocs()
}

function handleSizeChange(s: number) {
  size.value = s
  page.value = 1
  loadDocs()
}

function openDoc(row: DingTalkFile) {
  if (row.url) {
    window.open(row.url, '_blank')
  }
}

function fileTypeText(row: DingTalkFile): string {
  if (row.extension) return row.extension.toUpperCase()
  if (row.category) return row.category
  return '-'
}

onMounted(() => {
  loadDocs()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="dt-manage" v-loading="loading" element-loading-text="正在从钉钉知识库同步数据，请稍候…">
    <!-- 顶部操作栏 -->
    <div class="action-bar">
      <div class="action-left">
        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          type="warning"
          :closable="false"
          show-icon
          class="dt-alert"
        />
      </div>
      <div class="action-right">
        <span class="total-hint">共 {{ total }} 个文件</span>
        <span v-if="refreshing" class="sync-hint">后台同步中…</span>
        <el-button :icon="Refresh" :loading="refreshing" @click="handleRefresh">刷新</el-button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-input
        v-model="searchKeyword"
        placeholder="搜索文件名称"
        clearable
        style="width: 200px"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-select
        v-model="wsFilter"
        placeholder="按知识库过滤"
        multiple
        collapse-tags
        collapse-tags-tooltip
        clearable
        style="width: 220px"
        @change="handleSearch"
      >
        <el-option
          v-for="ws in wsOptions"
          :key="ws.id"
          :label="ws.name"
          :value="ws.id"
        />
      </el-select>
      <el-select
        v-model="creatorFilter"
        placeholder="按创建人过滤"
        multiple
        collapse-tags
        collapse-tags-tooltip
        clearable
        style="width: 180px"
        @change="handleSearch"
      >
        <el-option
          v-for="c in creatorOptions"
          :key="c.id"
          :label="c.name"
          :value="c.id"
        />
      </el-select>
      <el-input
        v-model="directoryKeyword"
        placeholder="上级目录（如 /新人导航）"
        clearable
        style="width: 200px"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-button type="primary" @click="handleSearch">查询</el-button>
      <el-button @click="handleReset">重置</el-button>
    </div>

    <!-- 表格 -->
    <el-table :data="documents" style="width: 100%" stripe>
      <el-table-column label="文件名称" min-width="240" prop="name" show-overflow-tooltip>
        <template #default="scope: any">
          <el-link type="primary" :underline="false" :href="scope.row.url" target="_blank" :disabled="!scope.row.url">
            <el-icon class="file-icon"><Document /></el-icon>
            {{ scope.row.name }}
          </el-link>
        </template>
      </el-table-column>
      <el-table-column label="来源知识库" width="160" prop="workspace_name" show-overflow-tooltip>
        <template #default="scope: any">
          {{ scope.row.workspace_name || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="上级目录" min-width="200" prop="directory_path" show-overflow-tooltip>
        <template #default="scope: any">
          <span class="dir-path" :title="scope.row.directory_path">{{ scope.row.directory_path }}</span>
        </template>
      </el-table-column>
      <el-table-column label="文件类型" width="100">
        <template #default="scope: any">
          <el-tag size="small" effect="plain">{{ fileTypeText(scope.row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="文件大小" width="110">
        <template #default="scope: any">
          <span class="col-muted">{{ scope.row.size ? formatFileSize(scope.row.size) : '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="创建人" width="110" prop="creator_name">
        <template #default="scope: any">
          {{ scope.row.creator_name || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170">
        <template #default="scope: any">
          {{ formatDate(scope.row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="最近更新" width="170">
        <template #default="scope: any">
          {{ formatDate(scope.row.modified_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="scope: any">
          <el-button link type="primary" size="small" :disabled="!scope.row.url" @click="openDoc(scope.row)">
            打开
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-wrap">
      <el-pagination
        v-if="total > size"
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>
  </div>
</template>

<style scoped>
.dt-manage {
  flex: 1;
  background: #fff;
  padding: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-shrink: 0;
  gap: 12px;
}

.action-left {
  flex: 1;
  min-width: 0;
}

.dt-alert {
  padding: 4px 12px;
}

.action-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.file-icon {
  margin-right: 4px;
  vertical-align: -2px;
}

.dir-path {
  color: #606266;
  font-size: 13px;
}

:deep(.el-table) {
  flex: 1;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  margin-top: 12px;
  flex-shrink: 0;
}

.total-hint {
  font-size: 13px;
  color: #909399;
}

.sync-hint {
  font-size: 13px;
  color: #409eff;
}

.col-muted {
  color: #909399;
}
</style>
