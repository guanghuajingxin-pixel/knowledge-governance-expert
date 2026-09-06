<script setup lang="ts">
/**
 * 知识中心 - 钉钉/本地上传知识 文件列表
 * 平铺展示跨知识库文档，支持按知识库、创建人过滤，手动刷新
 */
import { ref, watch, onMounted, computed } from 'vue'
import { Search, Refresh, Delete } from '@element-plus/icons-vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { fetchDocuments, fetchUploaders } from '@/api/knowledge-center'
import { listKnowledgeBases } from '@/api/knowledge-base'
import { formatDate, formatFileSize } from '@/utils/format'
import type { KnowledgeCenterDocument, TaskQueueStats, UploaderOption } from '@/types/knowledge-center'
import type { KnowledgeBase } from '@/types/knowledge-base'

const props = defineProps<{
  scopeTab: string
  stats: TaskQueueStats
}>()

const emit = defineEmits<{
  (e: 'recycle'): void
  (e: 'detail', docId: string): void
}>()

// 数据
const documents = ref<KnowledgeCenterDocument[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const size = ref(20)

// 筛选
const searchKeyword = ref('')
const kbFilter = ref<string[]>([])
const uploaderFilter = ref<string[]>([])
const kbOptions = ref<KnowledgeBase[]>([])
const uploaderOptions = ref<UploaderOption[]>([])

// 选中
const selectedIds = ref<string[]>([])
const isBatchMode = computed(() => selectedIds.value.length > 0)

async function loadDocs() {
  loading.value = true
  try {
    const params: any = {
      page: page.value,
      size: size.value,
      kb_type: props.scopeTab,
    }
    if (searchKeyword.value) params.search = searchKeyword.value
    if (kbFilter.value.length) params.kb_id = kbFilter.value.join(',')
    if (uploaderFilter.value.length) params.uploader_id = uploaderFilter.value.join(',')

    const res = await fetchDocuments(params)
    documents.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadKbOptions() {
  try {
    const res = await listKnowledgeBases({ size: 100, kb_type: props.scopeTab } as any)
    kbOptions.value = (res.items || []).filter((kb: KnowledgeBase) => kb.kb_type === props.scopeTab)
  } catch {
    // ignore
  }
}

async function loadUploaderOptions() {
  try {
    uploaderOptions.value = await fetchUploaders(props.scopeTab)
  } catch {
    // ignore
  }
}

function handleSearch() {
  page.value = 1
  loadDocs()
}

function handleReset() {
  searchKeyword.value = ''
  kbFilter.value = []
  uploaderFilter.value = []
  page.value = 1
  loadDocs()
}

function handleRefresh() {
  loadDocs()
  loadKbOptions()
  loadUploaderOptions()
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

function handleDetail(row: KnowledgeCenterDocument) {
  emit('detail', row.id)
}

function handleSelectionChange(rows: any[]) {
  selectedIds.value = rows.map((r) => r.id)
}

// 切换知识范围时重置并重新加载
watch(
  () => props.scopeTab,
  () => {
    page.value = 1
    searchKeyword.value = ''
    kbFilter.value = []
    uploaderFilter.value = []
    loadKbOptions()
    loadUploaderOptions()
    loadDocs()
  },
)

onMounted(() => {
  loadKbOptions()
  loadUploaderOptions()
  loadDocs()
})
</script>

<template>
  <div class="kc-manage">
    <!-- 顶部操作栏 -->
    <div class="action-bar">
      <div class="action-left">
        <el-button type="primary" @click="emit('recycle')">
          <el-icon :size="16"><Delete /></el-icon>
          回收站
        </el-button>
        <el-button :disabled="!isBatchMode">批量管理</el-button>
        <el-button :disabled="!isBatchMode">下载</el-button>
        <span class="action-hint">仅下载普通文件，不包含FAQ</span>
      </div>
      <div class="action-right">
        <span class="total-hint">共 {{ total }} 条</span>
        <el-button :icon="Refresh" :loading="loading" @click="handleRefresh">刷新</el-button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-input
        v-model="searchKeyword"
        placeholder="搜索文档标题"
        clearable
        style="width: 220px"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-select
        v-model="kbFilter"
        placeholder="按知识库过滤"
        multiple
        collapse-tags
        collapse-tags-tooltip
        clearable
        style="width: 220px"
        @change="handleSearch"
      >
        <el-option
          v-for="kb in kbOptions"
          :key="kb.id"
          :label="kb.name"
          :value="kb.id"
        />
      </el-select>
      <el-select
        v-model="uploaderFilter"
        placeholder="按创建人过滤"
        multiple
        collapse-tags
        collapse-tags-tooltip
        clearable
        style="width: 200px"
        @change="handleSearch"
      >
        <el-option
          v-for="up in uploaderOptions"
          :key="up.id"
          :label="up.name"
          :value="up.id"
        />
      </el-select>
      <el-button type="primary" @click="handleSearch">查询</el-button>
      <el-button @click="handleReset">重置</el-button>
    </div>

    <!-- 任务队列状态栏 -->
    <div class="task-queue-bar">
      <span class="queue-item">全部({{ stats.total }})</span>
      <span class="queue-item">执行中({{ stats.executing }})</span>
      <span class="queue-item">已完成({{ stats.completed }})</span>
      <span class="queue-item">失败({{ stats.failed }})</span>
    </div>

    <!-- 表格 -->
    <el-table
      :data="documents"
      v-loading="loading"
      style="width: 100%"
      stripe
      @selection-change="handleSelectionChange"
    >
      <el-table-column type="selection" width="40" />
      <el-table-column label="文档标题" min-width="220" prop="original_filename" show-overflow-tooltip>
        <template #default="scope: any">
          <el-link type="primary" :underline="false" @click="handleDetail(scope.row)">
            {{ scope.row.original_filename }}
          </el-link>
        </template>
      </el-table-column>
      <el-table-column label="来源知识库" width="150" prop="kb_name" show-overflow-tooltip>
        <template #default="scope: any">
          {{ scope.row.kb_name || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="知识分类" width="110" prop="directory_name">
        <template #default="scope: any">
          <span class="col-muted">{{ scope.row.directory_name || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="文件类型" width="90" prop="file_type">
        <template #default="scope: any">
          <el-tag v-if="scope.row.file_type" size="small" effect="plain">
            {{ scope.row.file_type.toUpperCase() }}
          </el-tag>
          <span v-else class="col-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="文件大小" width="110" prop="file_size">
        <template #default="scope: any">
          {{ scope.row.file_size ? formatFileSize(scope.row.file_size) : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="分块数" width="80" prop="chunk_count">
        <template #default="scope: any">
          {{ scope.row.chunk_count ?? 0 }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="scope: any">
          <StatusTag :status="scope.row.status" />
        </template>
      </el-table-column>
      <el-table-column label="创建人" width="110" prop="uploader_name">
        <template #default="scope: any">
          {{ scope.row.uploader_name || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170" prop="created_at">
        <template #default="scope: any">
          {{ formatDate(scope.row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="scope: any">
          <el-button link type="primary" size="small" @click="handleDetail(scope.row)">
            详情
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
.kc-manage {
  flex: 1;
  background: #fff;
  padding: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

/* 操作栏 */
.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.action-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.action-hint {
  font-size: 12px;
  color: #909399;
}

.action-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  flex-shrink: 0;
}

/* 任务队列状态栏 */
.task-queue-bar {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 4px;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.queue-item {
  font-size: 13px;
  color: #606266;
  cursor: default;
}

/* 表格容器 */
:deep(.el-table) {
  flex: 1;
}

/* 分页 */
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

.col-muted {
  color: #909399;
}
</style>
