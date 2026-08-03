<script setup lang="ts">
/**
 * 知识管理 Tab - 文档列表 + 筛选 + 操作栏
 */
import { ref, watch, onMounted, computed } from 'vue'
import { Search, Refresh, Delete } from '@element-plus/icons-vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { fetchDocuments } from '@/api/knowledge-center'
import { listKnowledgeBases } from '@/api/knowledge-base'
import { formatDate } from '@/utils/format'
import type { KnowledgeCenterDocument } from '@/types/knowledge-center'
import type { KnowledgeBase } from '@/types/knowledge-base'

const props = defineProps<{
  selectedDirectory: { id: string; kb_id: string } | null
  scopeTab: string
  statusFilter: string
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
const dateFrom = ref('')
const dateTo = ref('')
const kbFilter = ref<string[]>([])
const kbOptions = ref<KnowledgeBase[]>([])

// 选中
const selectedIds = ref<string[]>([])

// 批量管理状态
const isBatchMode = computed(() => selectedIds.value.length > 0)

async function loadDocs() {
  loading.value = true
  try {
    const params: any = {
      page: page.value,
      size: size.value,
      kb_type: props.scopeTab,
    }
    if (props.selectedDirectory) {
      if (props.selectedDirectory.id === props.selectedDirectory.kb_id) {
        params.kb_id = props.selectedDirectory.kb_id
      } else {
        params.directory_id = props.selectedDirectory.id
      }
    }
    if (searchKeyword.value) params.search = searchKeyword.value
    if (dateFrom.value) params.date_from = dateFrom.value
    if (dateTo.value) params.date_to = dateTo.value
    if (kbFilter.value.length) params.kb_id = kbFilter.value.join(',')
    if (props.statusFilter) params.status = props.statusFilter

    const res = await fetchDocuments(params)
    documents.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadKbOptions() {
  try {
    const res = await listKnowledgeBases({ size: 100 })
    kbOptions.value = res.items
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
  dateFrom.value = ''
  dateTo.value = ''
  kbFilter.value = []
  page.value = 1
  loadDocs()
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

// 监听选中目录变化
watch(
  () => props.selectedDirectory,
  () => {
    page.value = 1
    if (props.selectedDirectory !== null) {
      loadDocs()
    }
  },
)

// 监听状态筛选
watch(
  () => props.statusFilter,
  () => {
    page.value = 1
    loadDocs()
  },
)

watch(
  () => props.scopeTab,
  () => {
    page.value = 1
    loadDocs()
    loadKbOptions()
  },
)

onMounted(() => {
  loadKbOptions()
})
</script>

<template>
  <div class="kc-manage">
    <!-- 未选中目录时的空状态 -->
    <div v-if="!selectedDirectory" class="kc-empty">
      <el-empty :image-size="160" description="即将开始您的知识之旅">
        <template #image>
          <div class="empty-illustration">
            <el-icon :size="80" color="#c0c4cc"><svg viewBox="0 0 1024 1024" width="1em" height="1em"><path d="M512 64C264.6 64 64 264.6 64 512s200.6 448 448 448 448-200.6 448-448S759.4 64 512 64zm0 820c-205.4 0-372-166.6-372-372s166.6-372 372-372 372 166.6 372 372-166.6 372-372 372z" fill="currentColor"/><path d="M464 688a48 48 0 1096 0 48 48 0 10-96 0zm24-112h48c4.4 0 8-3.6 8-8V296c0-4.4-3.6-8-8-8h-48c-4.4 0-8 3.6-8 8v272c0 4.4 3.6 8 8 8z" fill="currentColor"/></svg></el-icon>
            <div class="empty-title">知识之旅</div>
            <div class="empty-sub">请从左侧目录树选择目录查看知识</div>
          </div>
        </template>
      </el-empty>
    </div>

    <!-- 选中目录后的内容 -->
    <template v-else>
      <!-- 操作栏 -->
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
          <el-button :icon="Refresh" @click="loadDocs">刷新</el-button>
        </div>
      </div>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索知识标题或ID/格式"
          clearable
          style="width: 220px"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-date-picker
          v-model="dateFrom"
          type="date"
          placeholder="上传开始时间"
          style="width: 150px"
          value-format="YYYY-MM-DD"
        />
        <el-date-picker
          v-model="dateTo"
          type="date"
          placeholder="上传结束时间"
          style="width: 150px"
          value-format="YYYY-MM-DD"
        />
        <el-select
          v-model="kbFilter"
          placeholder="来源知识库"
          multiple
          collapse-tags
          collapse-tags-tooltip
          style="width: 200px"
        >
          <el-option
            v-for="kb in kbOptions"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          />
        </el-select>
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
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
        <el-table-column label="知识标题" min-width="200" prop="original_filename" show-overflow-tooltip>
          <template #default="scope: any">
            <el-link type="primary" :underline="false" @click="handleDetail(scope.row)">
              {{ scope.row.original_filename }}
            </el-link>
          </template>
        </el-table-column>
        <el-table-column label="知识分类" width="120" prop="directory_name">
          <template #default="scope: any">
            <span class="col-muted">{{ scope.row.directory_name || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="来源团队" width="100">
          <template #default>
            <span class="col-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="来源知识库" width="140" prop="kb_name" show-overflow-tooltip>
          <template #default="scope: any">
            {{ scope.row.kb_name || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="上传人" width="100">
          <template #default>
            <span class="col-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="160" prop="created_at">
          <template #default="scope: any">
            {{ formatDate(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="scope: any">
            <StatusTag :status="scope.row.status" />
          </template>
        </el-table-column>
        <el-table-column label="过期时间" width="110">
          <template #default>
            <span class="col-muted">永久有效</span>
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
    </template>
  </div>
</template>

<style scoped>
.kc-manage {
  flex: 1;
  background: #fff;
  border-radius: 4px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.kc-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-illustration {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.empty-sub {
  font-size: 13px;
  color: #909399;
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

/* 表格容器 */
:deep(.el-table) {
  flex: 1;
}

/* 分页 */
.pagination-wrap {
  display: flex;
  justify-content: space-between;
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
