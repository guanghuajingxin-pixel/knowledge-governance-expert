<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, QuestionFilled, Search } from '@element-plus/icons-vue'
import { RefreshCw } from '@lucide/vue'
import {
  createWikiLibrary, deleteWikiLibrary, listWikiLibraries, updateWikiLibrary,
  type WikiLibrary,
} from '@/api/wiki'
import { updateKnowledgeLibrary } from '@/api/knowledge-library'
import KgPagination from '@/components/common/KgPagination.vue'
import { useUserStore } from '@/stores/user'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const canEdit = computed(() => ['super_admin', 'admin', 'editor'].includes(useUserStore().userInfo?.role || ''))
const canAdmin = computed(() => ['super_admin', 'admin'].includes(useUserStore().userInfo?.role || ''))

const libraries = ref<WikiLibrary[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const keyword = ref('')
const visible = computed(() => libraries.value.filter(l => l.name.includes(keyword.value)))
const page = ref(1)
const size = ref(20)
const paged = computed(() => visible.value.slice((page.value - 1) * size.value, page.value * size.value))

const runLabels: Record<string, string> = { PENDING: '排队中', RUNNING: '生成中', COMPLETED: '已完成', FAILED: '失败' }
const runType = (s: string) => (s === 'COMPLETED' ? 'success' : s === 'FAILED' ? 'danger' : 'warning')

async function load() {
  loading.value = true
  try { libraries.value = await listWikiLibraries() }
  catch (e: any) { error.value = e?.response?.data?.detail || e.message || '加载失败' }
  finally { loading.value = false }
}

function openLibrary(lib: WikiLibrary) {
  router.push({ path: `/apply/knowledge-libraries/${lib.id}/wiki` })
}

async function toggle(lib: WikiLibrary) {
  await run(async () => {
    await updateKnowledgeLibrary(lib.id, { enabled: !lib.enabled })
    lib.enabled = !lib.enabled
  })
}

async function run<T>(task: () => Promise<T>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await task() } catch (e: any) { error.value = e?.response?.data?.detail || e.message || '操作失败，请重试' }
  finally { busy.value = false }
}

async function removeLibrary(lib: WikiLibrary) {
  const detail = `将删除「${lib.name}」及库内 ${lib.page_count} 个 Wiki 页面、${lib.document_count} 篇原料文档（含分段），删除后不可恢复。是否继续？`
  try { await ElMessageBox.confirm(detail, '删除 Wiki 库', { type: 'warning' }) } catch { return }
  await run(async () => { await deleteWikiLibrary(lib.id); await load(); ElMessage.success('Wiki 库已删除') })
}

// 创建/设置弹窗：名称 + 描述 + 自动生成开关（原料解析与检索均用系统默认配置）
const dialog = ref(false)
const editingId = ref<number>()
const saving = ref(false)
const form = ref({ name: '', description: '', auto_generate: true })

function openCreate(lib?: WikiLibrary) {
  editingId.value = lib?.id
  form.value = { name: lib?.name || '', description: lib?.description || '', auto_generate: lib?.auto_generate ?? true }
  dialog.value = true
}

async function save() {
  if (!form.value.name.trim()) { ElMessage.warning('请输入知识库名称'); return }
  saving.value = true
  try {
    if (editingId.value) {
      await updateWikiLibrary(editingId.value, form.value)
      ElMessage.success('设置已保存')
    } else {
      await createWikiLibrary(form.value)
      ElMessage.success('Wiki 库已创建，添加原料并解析后将自动生成知识页面')
    }
    dialog.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { saving.value = false }
}

// 有排队/生成中任务时轮询刷新（5s，同文档库解析轮询节奏）
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
async function poll() {
  try {
    if (!busy.value && libraries.value.some(l => ['PENDING', 'RUNNING'].includes(l.last_run?.status || ''))) {
      libraries.value = await listWikiLibraries()
    }
  } catch { /* 静默：下一轮重试 */ }
  if (!disposed) timer = setTimeout(poll, 5000)
}
onMounted(async () => { await load(); timer = setTimeout(poll, 5000) })
onBeforeUnmount(() => { disposed = true; clearTimeout(timer) })
</script>
<template>
  <div class="kge-page wiki-libraries">
    <el-alert v-if="error" :title="String(error)" type="error" show-icon @close="error = ''" />
    <div class="content" v-loading="loading">
      <div class="toolbar">
        <el-input v-model="keyword" :prefix-icon="Search" placeholder="搜索 Wiki 库名称" clearable style="max-width: 320px" />
        <div class="spacer" />
        <el-tooltip content="刷新列表" placement="top">
          <el-button :icon="RefreshCw" :loading="loading" aria-label="刷新列表" @click="load" />
        </el-tooltip>
        <el-button v-if="canEdit" type="primary" :icon="Plus" @click="openCreate()">创建 Wiki 库</el-button>
      </div>
      <div class="table-fill">
        <el-table :data="paged" border height="100%" empty-text="暂无 Wiki 库，点击创建开始沉淀结构化知识">
          <el-table-column label="知识库名称" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button link type="primary" @click="openLibrary(row as WikiLibrary)">{{ (row as WikiLibrary).name }}</el-button>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
          <el-table-column prop="page_count" label="页面数" width="85" />
          <el-table-column prop="document_count" label="原料数" width="85" />
          <el-table-column label="最近生成" width="170">
            <template #default="{ row }">
              <template v-if="(row as WikiLibrary).last_run">
                <el-tag size="small" :type="runType((row as WikiLibrary).last_run!.status)">{{ runLabels[(row as WikiLibrary).last_run!.status] || (row as WikiLibrary).last_run!.status }}</el-tag>
                <span class="run-time">{{ formatDateTime((row as WikiLibrary).last_run!.finished_at || (row as WikiLibrary).last_run!.created_at) }}</span>
              </template>
              <template v-else>-</template>
            </template>
          </el-table-column>
          <el-table-column label="创建人" width="100" show-overflow-tooltip>
            <template #default="{ row }">{{ (row as WikiLibrary).creator || '-' }}</template>
          </el-table-column>
          <el-table-column label="开放检索" width="130">
            <template #default="{ row }">
              <div class="switch-line">
                <el-switch :model-value="(row as WikiLibrary).enabled" :disabled="busy || !canAdmin" :aria-label="`${(row as WikiLibrary).name}开放检索`" @change="toggle(row as WikiLibrary)" />
                <span>{{ (row as WikiLibrary).enabled ? '已开放' : '已停用' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="145">
            <template #default="{ row }">
              <el-button v-if="canEdit" link type="primary" @click="openCreate(row as WikiLibrary)">设置</el-button>
              <el-tooltip v-if="canAdmin" content="先停用后可删除；页面与原料随库级联删除">
                <el-button link type="danger" :disabled="busy || (row as WikiLibrary).enabled" @click="removeLibrary(row as WikiLibrary)">删除</el-button>
              </el-tooltip>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <KgPagination
        :page="page"
        :size="size"
        :total="visible.length"
        :sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @update:page="(p: number) => page = p"
        @update:size="(s: number) => { size = s; page = 1 }"
      />
    </div>
    <el-dialog v-model="dialog" :title="editingId ? 'Wiki 库设置' : '创建 Wiki 库'" width="min(560px, 94vw)" :close-on-click-modal="false">
      <el-form label-width="110px">
        <el-form-item label="知识库名称" required>
          <el-input v-model="form.name" maxlength="200" show-word-limit placeholder="请输入知识库名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
        <el-form-item label="自动生成">
          <div class="switch-line">
            <el-switch v-model="form.auto_generate" aria-label="解析完成后自动生成 Wiki 页面" />
            <span>{{ form.auto_generate ? '解析完成后自动生成' : '仅手动触发生成' }}</span>
            <el-tooltip content="开启后原料文档解析完成即自动调用 LLM 生成/更新知识页面；关闭后通过生成记录页手动触发" placement="top">
              <el-icon class="tip-icon"><QuestionFilled /></el-icon>
            </el-tooltip>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ editingId ? '保存设置' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<style scoped>
.wiki-libraries { padding: 24px; }
.content { background: white; padding: 20px; border-radius: 8px; flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; flex-shrink: 0; }
.spacer { flex: 1; min-width: 12px; }
.content > .table-fill { flex: 1; min-height: 0; }
.content > .kg-pagination { flex-shrink: 0; margin-top: 12px; }
.switch-line { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.run-time { margin-left: 6px; font-size: 12px; color: var(--el-text-color-secondary); }
.tip-icon { color: #c0c4cc; font-size: 14px; cursor: help; }
</style>
