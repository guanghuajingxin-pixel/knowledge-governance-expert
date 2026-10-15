<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Notebook, Plus, Search } from '@element-plus/icons-vue'
import { RefreshCw } from '@lucide/vue'
import {
  getWikiLibrary, listWikiPages, listWikiRuns, retryWikiRun, triggerWikiLint,
  latestWikiLint, updateWikiLibrary, generateWiki, type WikiLibrary, type WikiPage, type WikiRun,
} from '@/api/wiki'
import { listLibraryDocuments, downloadOriginal, deleteLibraryDocument, type LibraryDocument } from '@/api/document-library'
import AddKnowledgeDialog from '@/components/kb/AddKnowledgeDialog.vue'
import KgPagination from '@/components/common/KgPagination.vue'
import { useUserStore } from '@/stores/user'
import { useTabsStore } from '@/stores/tabs'
import { formatDateTime, formatSource } from '@/utils/format'
import { fileIcon } from '@/utils/file-icon'

const props = defineProps<{ libId: number }>()
const route = useRoute()
const router = useRouter()
const tabsStore = useTabsStore()
const canEdit = computed(() => ['super_admin', 'admin', 'editor'].includes(useUserStore().userInfo?.role || ''))

const lib = ref<WikiLibrary | null>(null)
const pages = ref<WikiPage[]>([])
const documents = ref<LibraryDocument[]>([])
const runs = ref<WikiRun[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')

const PAGE_TYPE_LABELS: Record<string, string> = { overview: '概览', topic: '主题', entity: '实体', comparison: '对比', qa: '问答' }
const PAGE_TYPE_TAG: Record<string, string> = { overview: 'info', topic: 'primary', entity: 'success', comparison: 'warning', qa: '' }
const RUN_LABELS: Record<string, string> = { PENDING: '排队中', RUNNING: '生成中', COMPLETED: '已完成', FAILED: '失败' }
const runType = (s: string) => (s === 'COMPLETED' ? 'success' : s === 'FAILED' ? 'danger' : 'warning')
const DOC_STATUS: Record<string, string> = { PENDING: '待同步', UPLOADED: '已上传', PARSING: '解析中', COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已停止', UNKNOWN: '状态未知' }

async function load() {
  loading.value = true
  try {
    lib.value = await getWikiLibrary(props.libId)
    tabsStore.updateTabTitle(route.path, lib.value.name)
    const [p, d, r] = await Promise.all([
      listWikiPages(props.libId), listLibraryDocuments(props.libId), listWikiRuns(props.libId)])
    pages.value = p
    documents.value = d
    runs.value = r
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e.message || '加载失败'
  } finally { loading.value = false }
}

// ===== 视图切换（等宽按钮组防跳动）与过滤 =====
const view = ref<'pages' | 'documents'>('pages')
const keyword = ref('')
const typeFilter = ref('')
const visiblePages = computed(() => pages.value.filter(p =>
  p.title.includes(keyword.value) && (!typeFilter.value || p.page_type === typeFilter.value)))
const pageCur = ref(1)
const pageSize = ref(20)
const pagedPages = computed(() => visiblePages.value.slice((pageCur.value - 1) * pageSize.value, pageCur.value * pageSize.value))

const docKeyword = ref('')
const visibleDocs = computed(() => documents.value.filter(d => d.name.includes(docKeyword.value)))
const docCur = ref(1)
const docSize = ref(20)
const pagedDocs = computed(() => visibleDocs.value.slice((docCur.value - 1) * docSize.value, docCur.value * docSize.value))

function openPage(page: WikiPage) {
  router.push({ path: `/apply/knowledge-libraries/${props.libId}/wiki/pages/${page.id}` })
}

// ===== 生成状态与操作 =====
const lastRun = computed(() => runs.value.find(r => r.kind === 'ingest') || null)
async function retryLastRun() {
  const run = lastRun.value
  if (!run) return
  await run0(async () => {
    await retryWikiRun(props.libId, run.id)
    ElMessage.success('已重新入队生成')
    await load()
  })
}
async function backfill() {
  await run0(async () => {
    const res = await generateWiki(props.libId)
    ElMessage.success(`已提交 ${res.document_count} 篇未消化原料的生成任务`)
    await load()
  })
}
async function run0(task: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await task() } catch (e: any) { error.value = e?.response?.data?.detail || e.message || '操作失败' }
  finally { busy.value = false }
}

// ===== 生成记录抽屉 =====
const runsVisible = ref(false)
async function retryRun(run: WikiRun) {
  await run0(async () => {
    await retryWikiRun(props.libId, run.id)
    ElMessage.success(run.kind === 'lint' ? '已重新发起健康检查' : '已重新入队生成')
    await load()
  })
}

// ===== Lint 健康检查 =====
const lintVisible = ref(false)
const lintRun = ref<WikiRun | null>(null)
const lintBusy = ref(false)
async function runLint() {
  lintBusy.value = true
  try {
    await triggerWikiLint(props.libId)
    ElMessage.success('健康检查已发起，稍后查看报告')
    await refreshLint()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '发起失败')
  } finally { lintBusy.value = false }
}
async function refreshLint() {
  lintRun.value = await latestWikiLint(props.libId).catch(() => null)
}
function openLint() {
  void refreshLint()
  lintVisible.value = true
}
const lintReport = computed(() => (lintRun.value?.report || {}) as {
  contradictions?: Array<{ page_a: string; page_b: string; description: string }>
  orphans?: Array<{ title: string; reason: string }>
  missing_topics?: Array<{ suggested_title: string; reason: string }>
  stale_pages?: Array<{ title: string; reason: string }>
  note?: string
})
function gotoPageByTitle(title: string) {
  const page = pages.value.find(p => p.title === title)
  if (page) openPage(page)
  else ElMessage.warning(`未找到页面「${title}」，可能已被删除或改名`)
}

// ===== 原料文档操作 =====
const addKnowledgeVisible = ref(false)
function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function downloadDoc(doc: LibraryDocument) {
  await run0(async () => download(await downloadOriginal(props.libId, doc.id), doc.name))
}
async function removeDoc(doc: LibraryDocument) {
  try { await ElMessageBox.confirm(`删除原料「${doc.name}」及其分段？已生成的 Wiki 页面不会自动删除。`, '删除原料', { type: 'warning' }) } catch { return }
  await run0(async () => { await deleteLibraryDocument(props.libId, doc.id); await load(); ElMessage.success('原料已删除') })
}
function docCommand(cmd: string, doc: LibraryDocument) {
  if (cmd === 'original') downloadDoc(doc)
  else if (cmd === 'remove') removeDoc(doc)
}

// ===== 库设置 =====
const settingsVisible = ref(false)
const saving = ref(false)
const form = reactive({ name: '', description: '', auto_generate: true })
function openSettings() {
  if (!lib.value) return
  Object.assign(form, { name: lib.value.name, description: lib.value.description, auto_generate: lib.value.auto_generate })
  settingsVisible.value = true
}
async function saveSettings() {
  if (!form.name.trim()) { ElMessage.warning('请输入知识库名称'); return }
  saving.value = true
  try {
    lib.value = await updateWikiLibrary(props.libId, { ...form })
    settingsVisible.value = false
    tabsStore.updateTabTitle(route.path, lib.value.name)
    ElMessage.success('设置已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { saving.value = false }
}

function goRetrievalTest() {
  router.push({ path: `/apply/knowledge-libraries/${props.libId}/retrieval-test` })
}

// ===== 轮询：生成任务/健康检查进行中 或 原料解析中 时自动刷新 =====
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
async function poll() {
  try {
    if (!busy.value && !loading.value) {
      const active = runs.value.some(r => ['PENDING', 'RUNNING'].includes(r.status))
      const parsing = documents.value.some(d => d.status === 'PARSING' || d.status === 'PENDING')
      if (active || parsing) await load()
      if (lintVisible.value && lintRun.value?.status === 'RUNNING') await refreshLint()
    }
  } catch { /* 静默：下一轮重试 */ }
  if (!disposed) timer = setTimeout(poll, 5000)
}
onMounted(async () => { await load(); timer = setTimeout(poll, 5000) })
onBeforeUnmount(() => { disposed = true; clearTimeout(timer) })
</script>
<template>
  <div class="kge-page wiki-library-detail">
    <el-alert v-if="error" :title="String(error)" type="error" show-icon @close="error = ''" />
    <div class="content" v-loading="loading">
      <!-- 库信息页头（对齐文档库详情页头） -->
      <header v-if="lib" class="lib-header">
        <div class="lib-icon"><el-icon :size="20"><Notebook /></el-icon></div>
        <div class="lib-info">
          <div class="lib-name-row">
            <span class="lib-name" :title="lib.name">{{ lib.name }}</span>
            <el-tag size="small" type="info" effect="plain">{{ lib.page_count }} 个页面</el-tag>
            <el-tag size="small" type="info" effect="plain">{{ lib.document_count }} 篇原料</el-tag>
          </div>
          <div class="lib-meta">
            <span>{{ lib.creator || '—' }}</span>
            <span class="meta-sep">|</span>
            <span class="lib-desc" :title="lib.description">{{ lib.description || '暂无描述' }}</span>
          </div>
        </div>
        <div class="lib-actions">
          <el-button type="primary" :icon="Search" @click="goRetrievalTest">检索测试</el-button>
          <el-button v-if="canEdit" @click="openSettings">设置</el-button>
        </div>
      </header>

      <!-- 生成状态条：进行中/失败时驻留提示（el-alert 分层反馈规范） -->
      <el-alert v-if="lastRun?.status === 'RUNNING'" type="info" :closable="false"
                title="正在生成 Wiki 页面：LLM 阅读原料并更新知识页面，完成后自动刷新" />
      <el-alert v-else-if="lastRun?.status === 'PENDING'" type="info" :closable="false"
                title="生成任务排队中，将按批次自动执行" />
      <el-alert v-else-if="lastRun?.status === 'FAILED'" type="error" :closable="false">
        <template #title>
          <span>最近一次生成失败：{{ lastRun.error || '未知原因' }}</span>
          <el-button v-if="canEdit" link type="primary" style="margin-left: 12px" @click="retryLastRun">重试</el-button>
        </template>
      </el-alert>

      <!-- 工具行：视图切换 + 视图内操作 -->
      <div class="toolbar">
        <el-radio-group v-model="view">
          <el-radio-button value="pages">Wiki 页面</el-radio-button>
          <el-radio-button value="documents">原料文档</el-radio-button>
        </el-radio-group>
        <template v-if="view === 'pages'">
          <el-button v-if="canEdit" :loading="lintBusy" @click="runLint">健康检查</el-button>
          <el-button @click="openLint">检查报告</el-button>
          <el-button @click="runsVisible = true">生成记录</el-button>
          <div class="spacer" />
          <el-select v-model="typeFilter" clearable placeholder="页面类型" style="width: 110px">
            <el-option v-for="(label, value) in PAGE_TYPE_LABELS" :key="value" :value="value" :label="label" />
          </el-select>
          <el-input v-model="keyword" :prefix-icon="Search" placeholder="搜索页面标题" clearable style="width: 220px" />
        </template>
        <template v-else>
          <el-button v-if="canEdit" type="primary" :icon="Plus" @click="addKnowledgeVisible = true">添加知识</el-button>
          <div class="spacer" />
          <el-input v-model="docKeyword" :prefix-icon="Search" placeholder="搜索原料名称" clearable style="width: 220px" />
        </template>
        <el-tooltip content="刷新列表" placement="top">
          <el-button :icon="RefreshCw" :loading="loading" aria-label="刷新列表" @click="load" />
        </el-tooltip>
      </div>

      <!-- Wiki 页面视图 -->
      <div v-if="view === 'pages'" class="table-fill">
        <el-table :data="pagedPages" border height="100%" empty-text="暂无页面，添加原料并解析后将自动生成">
          <el-table-column label="页面标题" min-width="300" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button link type="primary" @click="openPage(row as WikiPage)">{{ (row as WikiPage).title }}</el-button>
              <el-tag v-if="(row as WikiPage).edited_by_human" size="small" effect="plain" style="margin-left: 8px">人工修正</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="(PAGE_TYPE_TAG[(row as WikiPage).page_type] || 'info') as any">{{ PAGE_TYPE_LABELS[(row as WikiPage).page_type] || (row as WikiPage).page_type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="摘要" min-width="280" show-overflow-tooltip>
            <template #default="{ row }">{{ (row as WikiPage).summary || '—' }}</template>
          </el-table-column>
          <el-table-column label="溯源" width="70">
            <template #default="{ row }">{{ (row as WikiPage).source_refs.length }}</template>
          </el-table-column>
          <el-table-column prop="version" label="版本" width="70" />
          <el-table-column label="更新时间" width="170">
            <template #default="{ row }">{{ formatDateTime((row as WikiPage).updated_at) }}</template>
          </el-table-column>
        </el-table>
      </div>
      <KgPagination v-if="view === 'pages'"
        :page="pageCur" :size="pageSize" :total="visiblePages.length" :sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @update:page="(p: number) => pageCur = p"
        @update:size="(s: number) => { pageSize = s; pageCur = 1 }" />

      <!-- 原料文档视图 -->
      <div v-if="view === 'documents'" class="table-fill">
        <el-table :data="pagedDocs" border height="100%" empty-text="暂无原料，点击「添加知识」上传文件或引入钉钉知识">
          <el-table-column label="文档名称" min-width="380" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="doc-name-cell">
                <img class="file-ico" :src="fileIcon((row as LibraryDocument).name)" alt="" />
                <span>{{ (row as LibraryDocument).name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="任务进度" width="130">
            <template #default="{ row }">
              <el-tag :type="(row as LibraryDocument).status === 'COMPLETED' ? 'success' : (row as LibraryDocument).status === 'FAILED' ? 'danger' : 'warning'">
                {{ DOC_STATUS[(row as LibraryDocument).status] || (row as LibraryDocument).status }}
              </el-tag>
              <el-progress v-if="(row as LibraryDocument).status === 'PARSING'" :percentage="Math.round(((row as LibraryDocument).progress || 0) * 100)" />
            </template>
          </el-table-column>
          <el-table-column label="来源" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="(row as LibraryDocument).source === 'dingtalk' ? 'warning' : 'info'">{{ formatSource((row as LibraryDocument).source) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" width="170">
            <template #default="{ row }">{{ formatDateTime((row as LibraryDocument).updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <div class="ops">
                <el-button link type="primary" :disabled="(row as LibraryDocument).status === 'PENDING'" @click="downloadDoc(row as LibraryDocument)">下载原文</el-button>
                <el-dropdown trigger="click" placement="bottom-end" @command="(cmd: string) => docCommand(cmd, row as LibraryDocument)">
                  <el-button link>更多<el-icon style="margin-left: 2px"><ArrowDown /></el-icon></el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="remove" divided style="color: var(--el-color-danger)" :disabled="busy || (row as LibraryDocument).status === 'PARSING'">删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <KgPagination v-if="view === 'documents'"
        :page="docCur" :size="docSize" :total="visibleDocs.length" :sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @update:page="(p: number) => docCur = p"
        @update:size="(s: number) => { docSize = s; docCur = 1 }" />
    </div>

    <!-- 生成记录抽屉 -->
    <el-drawer v-model="runsVisible" title="生成记录" direction="rtl" size="720px">
      <div class="drawer-toolbar">
        <span class="hint">原料解析完成后自动入队；失败可重试，未消化原料可补生成</span>
        <div class="spacer" />
        <el-button v-if="canEdit" size="small" :loading="busy" @click="backfill">补生成未消化原料</el-button>
      </div>
      <el-table :data="runs" border size="small" empty-text="暂无生成记录">
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ formatDateTime((row as WikiRun).created_at) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="80">
          <template #default="{ row }">{{ (row as WikiRun).kind === 'lint' ? '健康检查' : '生成' }}</template>
        </el-table-column>
        <el-table-column label="触发" width="90">
          <template #default="{ row }">{{ (row as WikiRun).triggered_by === 'auto' ? '自动' : (row as WikiRun).triggered_by || '手动' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="85">
          <template #default="{ row }"><el-tag size="small" :type="runType((row as WikiRun).status)">{{ RUN_LABELS[(row as WikiRun).status] || (row as WikiRun).status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="结果" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="(row as WikiRun).kind === 'ingest'">新建 {{ (row as WikiRun).pages_created }} · 更新 {{ (row as WikiRun).pages_updated }} · 原料 {{ (row as WikiRun).document_ids.length }} 篇</span>
            <span v-else>检查报告 {{ (row as WikiRun).status === 'COMPLETED' ? '已生成' : '待完成' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="70">
          <template #default="{ row }">
            <el-button v-if="canEdit && ((row as WikiRun).status === 'FAILED' || ((row as WikiRun).kind === 'lint' && (row as WikiRun).status === 'COMPLETED'))"
                       link type="primary" size="small" @click="retryRun(row as WikiRun)">重试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>

    <!-- Lint 报告弹窗 -->
    <el-dialog v-model="lintVisible" title="健康检查报告" width="min(680px, 94vw)">
      <template v-if="lintRun?.status === 'RUNNING'">
        <el-alert type="info" :closable="false" title="健康检查进行中，完成后自动展示报告" />
      </template>
      <template v-else-if="lintRun?.status === 'FAILED'">
        <el-alert type="error" :closable="false" :title="`检查失败：${lintRun.error || '未知原因'}`" />
      </template>
      <template v-else-if="lintReport.note">
        <el-empty :description="lintReport.note" />
      </template>
      <template v-else>
        <div v-for="group in [
            { key: 'contradictions', label: '页面矛盾' },
            { key: 'orphans', label: '孤立页面' },
            { key: 'missing_topics', label: '缺失主题' },
            { key: 'stale_pages', label: '疑似过期' }]" :key="group.key">
          <div class="lint-group-title">{{ group.label }}（{{ (lintReport as any)[group.key]?.length || 0 }}）</div>
          <div v-if="!(lintReport as any)[group.key]?.length" class="lint-empty">无</div>
          <div v-for="(item, i) in (lintReport as any)[group.key]" :key="i" class="lint-item">
            <template v-if="group.key === 'contradictions'">
              <el-button link type="primary" @click="gotoPageByTitle(item.page_a)">{{ item.page_a }}</el-button>
              <span class="lint-sep">↔</span>
              <el-button link type="primary" @click="gotoPageByTitle(item.page_b)">{{ item.page_b }}</el-button>
              <span class="lint-desc">{{ item.description }}</span>
            </template>
            <template v-else>
              <el-button link type="primary" @click="gotoPageByTitle(item.title || item.suggested_title)">{{ item.title || item.suggested_title }}</el-button>
              <span class="lint-desc">{{ item.reason }}</span>
            </template>
          </div>
        </div>
        <div class="hint" style="margin-top: 12px">报告只读不改页：矛盾与过期可通过页面「重新生成」或人工编辑修复</div>
      </template>
    </el-dialog>

    <!-- 库设置弹窗（与列表页一致） -->
    <el-dialog v-model="settingsVisible" title="Wiki 库设置" width="min(560px, 94vw)" :close-on-click-modal="false">
      <el-form label-width="110px">
        <el-form-item label="知识库名称" required>
          <el-input v-model="form.name" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
        <el-form-item label="自动生成">
          <div class="switch-line">
            <el-switch v-model="form.auto_generate" aria-label="解析完成后自动生成 Wiki 页面" />
            <span>{{ form.auto_generate ? '解析完成后自动生成' : '仅手动触发生成' }}</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="settingsVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveSettings">保存设置</el-button>
      </template>
    </el-dialog>

    <AddKnowledgeDialog v-model="addKnowledgeVisible" :library-id="libId" :library-name="lib?.name" @success="load" />
  </div>
</template>
<style scoped>
.wiki-library-detail { padding: 24px; }
.content { background: white; padding: 20px; border-radius: 8px; flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; gap: 14px; }
.lib-header, .toolbar { flex-shrink: 0; }
.content > .table-fill { flex: 1; min-height: 0; }
.content > .kg-pagination { flex-shrink: 0; }
.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.spacer { flex: 1; min-width: 12px; }
.lib-header { display: flex; align-items: center; gap: 12px; padding-bottom: 14px; border-bottom: 1px solid var(--el-border-color-lighter); }
.lib-icon { flex: none; width: 40px; height: 40px; border-radius: 8px; background: #f4effe; color: #9a5cf5; display: flex; align-items: center; justify-content: center; }
.lib-info { flex: 1; min-width: 0; }
.lib-name-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.lib-name { font-size: 16px; font-weight: 600; color: #303133; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lib-meta { margin-top: 2px; display: flex; align-items: center; gap: 8px; font-size: 12px; color: #909399; min-width: 0; }
.meta-sep { color: var(--el-border-color); }
.lib-desc { max-width: 460px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lib-actions { flex: none; }
.switch-line { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.doc-name-cell { display: flex; align-items: center; gap: 8px; min-width: 0; }
.file-ico { width: 22px; height: 22px; flex: none; object-fit: contain; }
.ops { display: flex; align-items: center; gap: 12px; }
.ops .el-button + .el-button { margin-left: 0; }
.ops .el-dropdown { vertical-align: middle; }
.drawer-toolbar { display: flex; align-items: center; margin-bottom: 12px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.lint-group-title { font-size: 14px; font-weight: 600; color: #303133; margin: 14px 0 8px; }
.lint-empty { font-size: 13px; color: var(--el-text-color-secondary); }
.lint-item { display: flex; align-items: baseline; gap: 6px; padding: 6px 0; font-size: 13px; border-bottom: 1px dashed var(--el-border-color-lighter); }
.lint-sep { color: var(--el-text-color-secondary); }
.lint-desc { color: var(--el-text-color-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
