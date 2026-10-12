<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Upload, ArrowLeft } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import PageContainer from '@/components/common/PageContainer.vue'
import KgPagination from '@/components/common/KgPagination.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import FaqEntryDialog from '@/components/faq/FaqEntryDialog.vue'
import FaqImportDialog from '@/components/faq/FaqImportDialog.vue'
import { getKnowledgeBase } from '@/api/knowledge-base'
import { listFaqEntries, deleteFaqEntry } from '@/api/faq'
import type { KnowledgeBase } from '@/types/knowledge-base'
import type { FaqEntry } from '@/types/faq'
import { formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const kbId = route.params.id as string

const kb = ref<KnowledgeBase | null>(null)
const entries = ref<FaqEntry[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const keyword = ref('')
const dialogVisible = ref(false)
const importVisible = ref(false)
const editingEntry = ref<FaqEntry | null>(null)

async function fetchKb() {
  kb.value = await getKnowledgeBase(kbId)
}

async function fetchEntries() {
  loading.value = true
  try {
    const res = await listFaqEntries(kbId, { page: page.value, size: size.value, keyword: keyword.value || undefined })
    entries.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  fetchEntries()
}

function handleAdd() {
  editingEntry.value = null
  dialogVisible.value = true
}

function handleEdit(row: FaqEntry) {
  editingEntry.value = row
  dialogVisible.value = true
}

async function handleDelete(id: string) {
  await ElMessageBox.confirm('确认删除该问答？', '警告', { type: 'warning' })
  await deleteFaqEntry(id)
  ElMessage.success('删除成功')
  fetchEntries()
}

function handlePageChange(p: number) {
  page.value = p
  fetchEntries()
}

function handleSizeChange(s: number) {
  size.value = s
  page.value = 1
  fetchEntries()
}

onMounted(() => {
  fetchKb()
  fetchEntries()
})
</script>

<template>
  <PageContainer :title="kb?.name || '问答明细'">
    <template #actions>
      <el-button :icon="ArrowLeft" @click="router.push('/faq')">返回</el-button>
      <el-button :icon="Upload" @click="importVisible = true">批量导入</el-button>
      <el-button type="primary" :icon="Plus" @click="handleAdd">新增问答</el-button>
    </template>
    <div class="search-bar" style="margin-bottom: 16px;">
      <el-input v-model="keyword" placeholder="搜索问题或答案" style="width: 300px;" clearable @keyup.enter="handleSearch" @clear="handleSearch" />
      <el-button type="primary" @click="handleSearch" style="margin-left: 8px;">搜索</el-button>
    </div>
    <div class="table-fill">
    <el-table :data="entries" v-loading="loading" height="100%" style="width: 100%">
      <el-table-column type="index" label="#" width="50" />
      <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
      <el-table-column prop="answer" label="答案" min-width="300" show-overflow-tooltip />
      <el-table-column label="关键词" width="180">
        <template #default="{ row }">
          <el-tag v-for="k in row.keywords" :key="k" size="small" style="margin: 2px;">{{ k }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><StatusTag :status="row.status" /></template>
      </el-table-column>
      <el-table-column prop="view_count" label="浏览" width="70" />
      <el-table-column label="更新时间" width="150">
        <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="handleEdit(row as FaqEntry)">编辑</el-button>
          <el-button link type="danger" size="small" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    </div>
    <KgPagination
      :page="page"
      :size="size"
      :total="total"
      :sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      @update:page="handlePageChange"
      @update:size="handleSizeChange"
    />
  </PageContainer>
  <FaqEntryDialog v-model="dialogVisible" :kb-id="kbId" :editing-entry="editingEntry" @success="fetchEntries" />
  <FaqImportDialog v-model="importVisible" :kb-id="kbId" @success="fetchEntries" />
</template>

<style scoped>
/* 表格撑满剩余高度（表体内部滚动、表头吸顶），搜索栏与分页固定 */
.page-container :deep(.page-content) { display: flex; flex-direction: column; }
.search-bar { flex-shrink: 0; }
.table-fill { flex: 1; min-height: 0; }
</style>
