<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Delete, Setting, ArrowDown, List, Grid } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import KbCard from '@/components/kb/KbCard.vue'
import KbCreateDialog from '@/components/kb/KbCreateDialog.vue'
import { listKnowledgeBases, deleteKnowledgeBase } from '@/api/knowledge-base'
import type { KnowledgeBase } from '@/types/knowledge-base'
import { formatDate } from '@/utils/format'

const router = useRouter()

// State
const list = ref<KnowledgeBase[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const searchKeyword = ref('')
const sortBy = ref('created_at')
const sortOrder = ref<'desc' | 'asc'>('desc')
const page = ref(1)
const size = ref(20)
const total = ref(0)
const viewMode = ref<'card' | 'table'>('card')

// Debounce timer
let debounceTimer: ReturnType<typeof setTimeout> | null = null

const sortOptions = [
  { label: '最新更新', value: 'created_at', order: 'desc' as const },
  { label: '最早创建', value: 'created_at', order: 'asc' as const },
]

function currentSort() {
  return sortOptions.find((o) => o.value === sortBy.value && o.order === sortOrder.value) || sortOptions[0]
}

// Fetch data
async function fetchData() {
  loading.value = true
  try {
    const res = await listKnowledgeBases({
      search: searchKeyword.value || undefined,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
      page: page.value,
      size: size.value,
    })
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

// Search handlers
function onSearchInput() {
  if (debounceTimer) clearTimeout(debounceTimer)
  const kw = searchKeyword.value.trim()
  if (kw.length >= 2) {
    debounceTimer = setTimeout(() => {
      page.value = 1
      fetchData()
    }, 300)
  } else if (kw.length === 0) {
    page.value = 1
    debounceTimer = setTimeout(fetchData, 100)
  }
}

function onSearch() {
  if (debounceTimer) clearTimeout(debounceTimer)
  page.value = 1
  fetchData()
}

// Sort handler
function onSortChange(opt: (typeof sortOptions)[number]) {
  sortBy.value = opt.value
  sortOrder.value = opt.order
  page.value = 1
  fetchData()
}

// Pagination
function onPageChange(p: number) {
  page.value = p
  fetchData()
}

function onSizeChange(s: number) {
  size.value = s
  page.value = 1
  fetchData()
}

// Navigation
function openDetail(kb: KnowledgeBase) {
  if (kb.kb_type === 'FAQ') {
    router.push(`/faq/${kb.id}`)
  } else {
    router.push(`/knowledge-bases/${kb.id}`)
  }
}

function openSettings(kb: KnowledgeBase) {
  if (kb.kb_type === 'FAQ') {
    router.push(`/faq/${kb.id}`)
  } else {
    router.push(`/knowledge-bases/${kb.id}`)
  }
}

// Delete
async function handleDelete(kb: KnowledgeBase) {
  try {
    await ElMessageBox.confirm(
      `删除「${kb.name}」将同时删除其所有文档和索引，确认删除？`,
      '警告',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
    await deleteKnowledgeBase(kb.id)
    ElMessage.success('删除成功')
    fetchData()
  } catch {
    // cancelled
  }
}

// Status tag
function getStatusType(status?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (!status || status === '正常') return 'success'
  if (status.includes('处理') || status.includes('索引') || status.includes('PARSING') || status.includes('INDEXING')) return 'warning'
  if (status.includes('失败') || status.includes('FAILED')) return 'danger'
  return 'info'
}

onMounted(fetchData)
</script>

<template>
  <PageContainer>
    <!-- Search Bar -->
    <div class="search-wrap">
      <el-input
        v-model="searchKeyword"
        placeholder="搜索常见问题、使用指南、功能说明..."
        clearable
        size="large"
        :prefix-icon="Search"
        class="search-input"
        @input="onSearchInput"
        @keyup.enter="onSearch"
        @clear="onSearch"
      >
        <template #append>
          <el-button :icon="Search" @click="onSearch">搜索</el-button>
        </template>
      </el-input>
    </div>

    <!-- Toolbar -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" :icon="Plus" @click="dialogVisible = true">添加知识库</el-button>
        <el-dropdown trigger="click" @command="(opt: any) => onSortChange(opt)">
          <span class="sort-trigger">
            排序: {{ currentSort().label }} <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="opt in sortOptions"
                :key="opt.label"
                :command="opt"
              >
                {{ opt.label }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <div class="toolbar-right">
        <span class="total-hint">共 {{ total }} 条</span>
        <el-button-group class="view-toggle">
          <el-button
            :type="viewMode === 'card' ? 'primary' : 'default'"
            :icon="Grid"
            size="small"
            @click="viewMode = 'card'"
          />
          <el-button
            :type="viewMode === 'table' ? 'primary' : 'default'"
            :icon="List"
            size="small"
            @click="viewMode = 'table'"
          />
        </el-button-group>
      </div>
    </div>

    <!-- Card View -->
    <div v-if="viewMode === 'card'" v-loading="loading">
      <el-row v-if="list.length" :gutter="20">
        <el-col
          v-for="kb in list"
          :key="kb.id"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
          style="margin-bottom: 20px"
        >
          <KbCard :kb="kb" @delete="handleDelete(kb)" />
        </el-col>
      </el-row>
      <el-empty v-else description="暂无知识库" />
    </div>

    <!-- Table View -->
    <el-table
      v-else
      v-loading="loading"
      :data="list"
      stripe
      style="width: 100%"
      empty-text="暂无知识库"
    >
      <el-table-column label="知识库名称" min-width="180" prop="name">
        <template #default="{ row }: any">
          <el-link type="primary" @click="openDetail(row)">{{ row.name }}</el-link>
        </template>
      </el-table-column>
      <el-table-column label="描述" min-width="220" prop="description" show-overflow-tooltip>
        <template #default="{ row }: any">
          <span class="desc-text">{{ row.description || '暂无描述' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90" prop="status">
        <template #default="{ row }: any">
          <el-tag :type="getStatusType(row.status)" size="small">{{ row.status || '正常' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="知识数量" width="100" prop="document_count">
        <template #default="{ row }: any">
          {{ row.document_count ?? 0 }}
        </template>
      </el-table-column>
      <el-table-column label="创建人" width="110" prop="owner_name">
        <template #default="{ row }: any">
          {{ row.owner_name || row.owner_id?.slice(0, 8) || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170" prop="created_at">
        <template #default="{ row }: any">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }: any">
          <el-button type="primary" link :icon="Setting" size="small" @click="openSettings(row)">
            设置
          </el-button>
          <el-button type="danger" link :icon="Delete" size="small" @click="handleDelete(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Pagination -->
    <div v-if="total > size" class="pagination-wrap">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </PageContainer>

  <KbCreateDialog v-model="dialogVisible" @success="fetchData" />
</template>

<style scoped>
.search-wrap {
  display: flex;
  justify-content: center;
  margin-bottom: 16px;
}

.search-input {
  width: 600px;
  max-width: 100%;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sort-trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #606266;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.15s;
}

.sort-trigger:hover {
  background: #f5f7fa;
}

.total-hint {
  font-size: 13px;
  color: #909399;
}

.view-toggle {
  flex-shrink: 0;
}

.desc-text {
  color: #909399;
  font-size: 13px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
