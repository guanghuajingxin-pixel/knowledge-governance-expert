<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { RefreshCw } from '@lucide/vue'
import KbCreateDialog from '@/components/kb/KbCreateDialog.vue'
import KgPagination from '@/components/common/KgPagination.vue'
import { listFaqKbs, updateFaqKb } from '@/api/faq'
import { deleteKnowledgeBase } from '@/api/knowledge-base'
import type { FaqKb } from '@/types/faq'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const libraries = ref<FaqKb[]>([])
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const createVisible = ref(false)

// 问答库列表前端分页（接口一次返回全量，这里按页切片展示）
const page = ref(1)
const size = ref(20)
const visibleLibraries = computed(() => libraries.value.filter(l => l.name.includes(keyword.value)))
const pagedLibraries = computed(() => {
  const start = (page.value - 1) * size.value
  return visibleLibraries.value.slice(start, start + size.value)
})
watch(() => keyword.value, () => { page.value = 1 })

async function load() {
  loading.value = true
  error.value = ''
  try {
    libraries.value = await listFaqKbs()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

// 点击问答库：以独立页签打开问答明细页，问答库列表页签保持不动
function openDetail(kb: FaqKb) {
  router.push(`/faq/${kb.id}`)
}

// 编辑问答库（名称/描述）
const editVisible = ref(false)
const editSaving = ref(false)
const editFormRef = ref<FormInstance>()
const editForm = reactive({ id: '', name: '', description: '' })
const editRules: FormRules = {
  name: [{ required: true, message: '请输入问答库名称', trigger: 'blur' }],
}

function openEdit(kb: FaqKb) {
  editForm.id = kb.id
  editForm.name = kb.name
  editForm.description = kb.description || ''
  editVisible.value = true
}

async function handleEditSave() {
  if (!editFormRef.value) return
  await editFormRef.value.validate(async (valid) => {
    if (!valid) return
    editSaving.value = true
    try {
      await updateFaqKb(editForm.id, { name: editForm.name.trim(), description: editForm.description.trim() || null })
      ElMessage.success('问答库已更新')
      editVisible.value = false
      await load()
    } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail || '更新失败')
    } finally {
      editSaving.value = false
    }
  })
}

async function handleDelete(kb: FaqKb) {
  try {
    await ElMessageBox.confirm(`删除问答库「${kb.name}」及其全部问答？删除后不可恢复。`, '删除问答库', { type: 'warning' })
  } catch { return }
  try {
    await deleteKnowledgeBase(kb.id)
    ElMessage.success('问答库已删除')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="faq-libraries">
    <el-alert v-if="error" :title="String(error)" type="error" show-icon @close="error = ''" />
    <div class="toolbar">
      <el-button type="primary" :icon="Plus" @click="createVisible = true">创建问答库</el-button>
      <div class="toolbar-spacer" />
      <el-input v-model="keyword" :prefix-icon="Search" placeholder="搜索问答库名称" clearable style="width: 240px" />
      <el-tooltip content="刷新列表" placement="top">
        <el-button :icon="RefreshCw" :loading="loading" aria-label="刷新列表" @click="load" />
      </el-tooltip>
    </div>
    <div class="table-fill">
      <el-table :data="pagedLibraries" v-loading="loading" border height="100%" empty-text="暂无问答库，点击创建问答库开始">
        <el-table-column label="问答库名称" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row as FaqKb)">{{ row.name }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '暂无描述' }}</template>
        </el-table-column>
        <el-table-column prop="entry_count" label="问答数" width="90" />
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row as FaqKb)">编辑</el-button>
            <el-button link type="danger" size="small" @click="handleDelete(row as FaqKb)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <KgPagination
      :page="page"
      :size="size"
      :total="visibleLibraries.length"
      :sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      @update:page="(p: number) => page = p"
      @update:size="(s: number) => { size = s; page = 1 }"
    />
  </div>
  <KbCreateDialog v-model="createVisible" fixed-type="FAQ" @success="load" />
  <el-dialog v-model="editVisible" title="编辑问答库" width="480px">
    <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="80px">
      <el-form-item label="名称" prop="name">
        <el-input v-model="editForm.name" placeholder="请输入问答库名称" maxlength="100" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="editForm.description" type="textarea" :rows="3" placeholder="可选" maxlength="500" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editVisible = false">取消</el-button>
      <el-button type="primary" :loading="editSaving" @click="handleEditSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.faq-libraries { padding: 20px; background: white; height: 100%; min-height: 0; display: flex; flex-direction: column; overflow: hidden; box-sizing: border-box; }
.el-alert { margin-bottom: 16px; flex-shrink: 0; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-shrink: 0; flex-wrap: wrap; }
.toolbar-spacer { flex: 1; min-width: 12px; }
.table-fill { flex: 1; min-height: 0; }
.faq-libraries > :deep(.kg-pagination) { flex-shrink: 0; margin-top: 12px; }
</style>
