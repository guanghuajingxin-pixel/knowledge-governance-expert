<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Delete, Setting, StarFilled, Star, Grid, List } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import KbCard from '@/components/kb/KbCard.vue'
import KbCreateDialog from '@/components/kb/KbCreateDialog.vue'
import { listKnowledgeBases, deleteKnowledgeBase, favoriteKnowledgeBase, unfavoriteKnowledgeBase } from '@/api/knowledge-base'
import type { KnowledgeBase, KbType } from '@/types/knowledge-base'
import { formatDate } from '@/utils/format'

const router = useRouter()

// State
const list = ref<KnowledgeBase[]>([])
const loading = ref(false)
const dialogVisible = ref(false)

// Filters
const filterType = ref<KbType | ''>('')
const filterOwner = ref<string>('')
const filterStatus = ref<string>('')
const filterFavorite = ref(false)
const searchKeyword = ref('')
const viewMode = ref<'card' | 'table'>('card')
const page = ref(1)
const size = ref(20)
const total = ref(0)

const typeOptions = [
  { label: '全部', value: '' },
  { label: '文档', value: 'DOCUMENT' },
  { label: 'FAQ', value: 'FAQ' },
]

const ownerOptions = [
  { label: '所有人', value: '' },
  { label: '由我创建', value: 'me' },
]

const statusOptions = [
  { label: '全部', value: '' },
  { label: '发布中', value: 'PUBLISHING' },
  { label: '完全发布', value: 'FULLY_PUBLISHED' },
  { label: '部分失败', value: 'PARTIALLY_FAILED' },
]

// Debounce timer
let debounceTimer: ReturnType<typeof setTimeout> | null = null

// Fetch data
async function fetchData() {
  loading.value = true
  try {
    const params: any = {
      search: searchKeyword.value || undefined,
      kb_type: filterType.value || undefined,
      owner_id: filterOwner.value || undefined,
      status: filterStatus.value || undefined,
      is_favorite: filterFavorite.value || undefined,
      sort_by: 'created_at',
      sort_order: 'desc',
      page: page.value,
      size: size.value,
    }
    const res = await listKnowledgeBases(params)
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

// Filter change → reset page + refetch
function onFilterChange() {
  page.value = 1
  fetchData()
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

function onSearchClear() {
  searchKeyword.value = ''
  page.value = 1
  fetchData()
}

// Toggle favorite
async function toggleFavorite(kb: KnowledgeBase, event: Event) {
  event.stopPropagation()
  try {
    if (kb.is_favorite) {
      await unfavoriteKnowledgeBase(kb.id)
      kb.is_favorite = false
      ElMessage.success('已取消收藏')
    } else {
      await favoriteKnowledgeBase(kb.id)
      kb.is_favorite = true
      ElMessage.success('已收藏')
    }
  } catch {
    ElMessage.error('操作失败')
  }
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
function getStatusType(status?: string): '' | 'success' | 'warning' | 'danger' | 'info' {
  if (!status || status === 'FULLY_PUBLISHED') return 'success'
  if (status === 'PUBLISHING') return 'warning'
  if (status === 'PARTIALLY_FAILED') return 'danger'
  return 'info'
}

function getStatusLabel(status?: string): string {
  const map: Record<string, string> = {
    PUBLISHING: '发布中',
    FULLY_PUBLISHED: '完全发布',
    PARTIALLY_FAILED: '部分失败',
  }
  return map[status || ''] || status || '正常'
}

onMounted(fetchData)
</script>

<template>
  <PageContainer>
    <!-- Filter Bar -->
    <div class="filter-bar">
      <div class="filter-left">
        <el-button type="primary" :icon="Plus" @click="dialogVisible = true">添加知识库</el-button>
        <el-checkbox v-model="filterFavorite" label="仅展示收藏" @change="onFilterChange" />
        <el-select
          v-model="filterType"
          placeholder="知识库类型"
          style="width: 140px"
          clearable
          @change="onFilterChange"
        >
          <el-option v-for="opt in typeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select
          v-model="filterOwner"
          placeholder="归属人"
          style="width: 140px"
          clearable
          @change="onFilterChange"
        >
          <el-option v-for="opt in ownerOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select
          v-model="filterStatus"
          placeholder="状态"
          style="width: 140px"
          clearable
          @change="onFilterChange"
        >
          <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
      </div>
      <div class="filter-right">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索知识库名称"
          style="width: 220px"
          clearable
          :prefix-icon="Search"
          @input="onSearchInput"
          @clear="onSearchClear"
        />
        <el-radio-group v-model="viewMode" class="view-toggle-radio">
          <el-radio-button value="card">
            <el-icon><Grid /></el-icon>
          </el-radio-button>
          <el-radio-button value="table">
            <el-icon><List /></el-icon>
          </el-radio-button>
        </el-radio-group>
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
          <KbCard :kb="kb" @delete="handleDelete(kb)" @toggle-favorite="toggleFavorite(kb, $event)" />
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
      <el-table-column label="状态" width="110" prop="status">
        <template #default="{ row }: any">
          <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusLabel(row.status) }}</el-tag>
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
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }: any">
          <el-button
            :type="row.is_favorite ? 'warning' : 'default'"
            :icon="row.is_favorite ? StarFilled : Star"
            link
            size="small"
            @click="toggleFavorite(row, $event)"
          >
            {{ row.is_favorite ? '已收藏' : '收藏' }}
          </el-button>
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
.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.filter-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.view-toggle-radio {
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
