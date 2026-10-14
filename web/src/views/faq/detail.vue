<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowDown, ChatDotRound, Plus, Search, Upload } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import KgPagination from '@/components/common/KgPagination.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import FaqEntryDialog from '@/components/faq/FaqEntryDialog.vue'
import FaqImportDialog from '@/components/faq/FaqImportDialog.vue'
import { listFaqKbs, listFaqEntries, deleteFaqEntry } from '@/api/faq'
import type { FaqEntry, FaqKb } from '@/types/faq'
import { useTabsStore } from '@/stores/tabs'
import { formatDateTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const tabsStore = useTabsStore()
const kbId = route.params.id as string

const kb = ref<FaqKb | null>(null)
const entries = ref<FaqEntry[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const dialogVisible = ref(false)
const importVisible = ref(false)
const editingEntry = ref<FaqEntry | null>(null)

// 相似问归属主问题：列表中仅一条数据，列上仅显示数量，完整内容在编辑弹窗维护
const similarText = (row: FaqEntry) =>
  row.similar_questions.length ? `${row.similar_questions.length} 条` : '-'
const similarTooltip = (row: FaqEntry) => row.similar_questions.join('；')

async function fetchKb() {
  const kbs = await listFaqKbs()
  kb.value = kbs.find(k => k.id === kbId) || null
  // 页签标题显示问答库名称（与文档库详情页签同构）
  if (kb.value) tabsStore.updateTabTitle(route.path, kb.value.name)
}

async function fetchEntries() {
  loading.value = true
  error.value = ''
  try {
    const res = await listFaqEntries(kbId, {
      page: page.value, size: size.value,
      keyword: keyword.value || undefined,
    })
    entries.value = res.items
    total.value = res.total
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e.message || '加载失败'
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

async function handleDelete(row: FaqEntry) {
  try {
    await ElMessageBox.confirm(`删除问答「${row.question}」及其相似问？`, '删除问答', { type: 'warning' })
  } catch { return }
  try {
    await deleteFaqEntry(row.id)
    ElMessage.success('删除成功')
    fetchEntries()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
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
  <PageContainer>
    <template #actions>
      <el-button :icon="ArrowLeft" @click="router.push('/apply/knowledge-libraries?type=faq')">返回</el-button>
    </template>
    <div class="faq-detail">
      <el-alert v-if="error" :title="String(error)" type="error" show-icon @close="error = ''" />
      <!-- 库信息页头：图标 + 名称/元信息（对齐文档库详情页头） -->
      <header class="lib-header">
        <div class="lib-icon"><el-icon :size="20"><ChatDotRound /></el-icon></div>
        <div class="lib-info">
          <div class="lib-name-row">
            <span class="lib-name" :title="kb?.name">{{ kb?.name || '问答明细' }}</span>
            <el-tag size="small" type="info" effect="plain">{{ total }} 条问答</el-tag>
          </div>
          <div class="lib-meta">
            <span class="lib-desc" :title="kb?.description || ''">{{ kb?.description || '暂无描述' }}</span>
          </div>
        </div>
      </header>
      <!-- 工具行：左侧新增/导入，右侧搜索 -->
      <div class="doc-toolbar">
        <el-button type="primary" :icon="Plus" @click="handleAdd">新增问答</el-button>
        <el-button :icon="Upload" @click="importVisible = true">批量导入</el-button>
        <div class="toolbar-spacer" />
        <el-input
          v-model="keyword"
          :prefix-icon="Search"
          placeholder="搜索问题、答案或相似问"
          clearable
          style="width: 280px"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
      </div>
      <div class="table-fill">
        <el-table :data="entries" v-loading="loading" border height="100%" empty-text="暂无问答，点击新增问答或批量导入开始">
          <el-table-column label="问题" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="question-text">{{ row.question }}</span>
            </template>
          </el-table-column>
          <el-table-column label="相似问" width="90">
            <template #default="{ row }">
              <el-tooltip v-if="(row as FaqEntry).similar_questions.length" :content="similarTooltip(row as FaqEntry)" placement="top" :show-after="300">
                <span class="similar-count">{{ similarText(row as FaqEntry) }}</span>
              </el-tooltip>
              <span v-else class="similar-empty">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="answer" label="答案" min-width="280" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }"><StatusTag :status="row.status" /></template>
          </el-table-column>
          <el-table-column label="更新时间" width="170">
            <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <div class="ops">
                <el-button link type="primary" size="small" @click="handleEdit(row as FaqEntry)">编辑</el-button>
                <el-dropdown trigger="click" placement="bottom-end" @command="(cmd: string) => cmd === 'delete' && handleDelete(row as FaqEntry)">
                  <el-button link size="small">更多<el-icon style="margin-left: 2px"><ArrowDown /></el-icon></el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="delete" style="color: var(--el-color-danger)">删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
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
    </div>
  </PageContainer>
  <FaqEntryDialog v-model="dialogVisible" :kb-id="kbId" :editing-entry="editingEntry" @success="fetchEntries" />
  <FaqImportDialog v-model="importVisible" :kb-id="kbId" @success="fetchEntries" />
</template>

<style scoped>
.faq-detail { height: 100%; min-height: 0; display: flex; flex-direction: column; }
.el-alert { margin-bottom: 16px; flex-shrink: 0; }
/* 库信息页头（对齐文档库详情页） */
.lib-header { display: flex; align-items: center; gap: 12px; padding-bottom: 14px; border-bottom: 1px solid var(--el-border-color-lighter); margin-bottom: 14px; flex-shrink: 0; }
.lib-icon { flex: none; width: 40px; height: 40px; border-radius: 8px; background: var(--el-color-success-light-9, #f0f9eb); color: var(--el-color-success); display: flex; align-items: center; justify-content: center; }
.lib-info { flex: 1; min-width: 0; }
.lib-name-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.lib-name { font-size: 16px; font-weight: 600; color: #303133; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lib-meta { margin-top: 2px; display: flex; align-items: center; font-size: 12px; color: #909399; min-width: 0; }
.lib-desc { max-width: 460px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 工具行 */
.doc-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-shrink: 0; flex-wrap: wrap; }
.toolbar-spacer { flex: 1; min-width: 12px; }
.table-fill { flex: 1; min-height: 0; }
.faq-detail > :deep(.kg-pagination) { flex-shrink: 0; margin-top: 12px; }
/* 问题列：标准问句 */
.question-text { color: #303133; }
/* 相似问数量：次要信息灰字 */
.similar-count { color: #909399; cursor: default; }
.similar-empty { color: #c0c4cc; }
.ops { display: flex; align-items: center; gap: 12px; }
.ops .el-dropdown { vertical-align: middle; }
.ops .el-button + .el-button { margin-left: 0; }
</style>
