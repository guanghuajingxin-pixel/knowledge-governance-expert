<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { ArrowLeft, ArrowDown } from '@element-plus/icons-vue'
import {
  getWikiPage, listWikiPages, editWikiPage, deleteWikiPage, regenerateWikiPage,
  type WikiPage,
} from '@/api/wiki'
import { useUserStore } from '@/stores/user'
import { useTabsStore } from '@/stores/tabs'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ libId: number; pageId: string }>()
const route = useRoute()
const router = useRouter()
const tabsStore = useTabsStore()
const canEdit = computed(() => ['super_admin', 'admin', 'editor'].includes(useUserStore().userInfo?.role || ''))

const PAGE_TYPE_LABELS: Record<string, string> = { overview: '概览', topic: '主题', entity: '实体', comparison: '对比', qa: '问答' }

const page = ref<WikiPage | null>(null)
const siblings = ref<WikiPage[]>([])
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  try {
    const [p, all] = await Promise.all([getWikiPage(props.libId, props.pageId), listWikiPages(props.libId)])
    page.value = p
    siblings.value = all
    tabsStore.updateTabTitle(route.path, p.title)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e.message || '加载失败'
  } finally { loading.value = false }
}

const pageTitles = computed(() => new Set(siblings.value.map(p => p.title)))

// Wiki 语法渲染：[[页面标题]] 互链 + ^[来源:文档名] 溯源标记（marked 前置替换，DOMPurify 消毒）
function renderContent(md: string): string {
  let text = (md || '').replace(/\[\[([^\]]+)\]\]/g, (_m, t: string) => {
    const exists = pageTitles.value.has(t)
    return `<a class="wiki-link${exists ? '' : ' missing'}" data-wiki="${t}" href="javascript:void(0)">${t}</a>`
  })
  text = text.replace(/\^\[来源[:：]([^\]]+)\]/g, (_m, n: string) =>
    `<span class="wiki-src">来源：${n}</span>`)
  const html = marked.parse(text, { async: false }) as string
  return DOMPurify.sanitize(html, { FORBID_TAGS: ['iframe', 'video', 'audio'], ADD_ATTR: ['data-wiki'] })
}
const rendered = computed(() => (page.value ? renderContent(page.value.content || '') : ''))

function onContentClick(e: MouseEvent) {
  const target = (e.target as HTMLElement).closest('a.wiki-link') as HTMLElement | null
  if (!target) return
  e.preventDefault()
  const title = target.dataset.wiki || ''
  const target2 = siblings.value.find(p => p.title === title)
  if (target2) {
    router.push({ path: `/apply/knowledge-libraries/${props.libId}/wiki/pages/${target2.id}` })
  } else {
    ElMessage.info(`页面「${title}」尚未创建`)
  }
}

// 溯源：原料文档跳分段详情；qa 页展示来源问题
function gotoSource(ref: { document_id?: string; document_name?: string }) {
  if (!ref.document_id) return
  router.push({
    name: 'LibraryDocumentSegments',
    params: { libId: props.libId, docId: ref.document_id },
    query: { name: ref.document_name || '' },
  })
}
function back() {
  router.push({ path: `/apply/knowledge-libraries/${props.libId}/wiki` })
}

// ===== 人工编辑：markdown 源码 + 预览切换 =====
const editVisible = ref(false)
const editPreview = ref(false)
const editSaving = ref(false)
const editForm = ref({ title: '', content: '' })
function openEdit() {
  if (!page.value) return
  editForm.value = { title: page.value.title, content: page.value.content || '' }
  editPreview.value = false
  editVisible.value = true
}
async function saveEdit() {
  if (!editForm.value.title.trim()) { ElMessage.warning('请输入页面标题'); return }
  if (!editForm.value.content.trim()) { ElMessage.warning('页面内容不能为空'); return }
  editSaving.value = true
  try {
    page.value = await editWikiPage(props.libId, props.pageId, { ...editForm.value })
    editVisible.value = false
    tabsStore.updateTabTitle(route.path, page.value.title)
    ElMessage.success('已保存并标记人工修正（后续自动生成将跳过本页）')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { editSaving.value = false }
}

// ===== 重新生成 / 删除 =====
const regenLoading = ref(false)
async function regenerate() {
  if (!page.value) return
  try {
    await ElMessageBox.confirm('将按本页溯源原料重新生成，覆盖当前内容（含人工修正）。是否继续？', '重新生成', { type: 'warning' })
  } catch { return }
  regenLoading.value = true
  try {
    page.value = await regenerateWikiPage(props.libId, props.pageId)
    ElMessage.success('页面已重新生成')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '重新生成失败')
  } finally { regenLoading.value = false }
}
async function remove() {
  if (!page.value) return
  try { await ElMessageBox.confirm(`删除页面「${page.value.title}」？`, '删除页面', { type: 'warning' }) } catch { return }
  try {
    await deleteWikiPage(props.libId, props.pageId)
    ElMessage.success('页面已删除')
    back()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}
function pageCommand(cmd: string) {
  if (cmd === 'remove') remove()
}

onMounted(load)
</script>
<template>
  <div class="kge-page wiki-page-view">
    <el-alert v-if="error" :title="String(error)" type="error" show-icon @close="error = ''" />
    <div class="content" v-loading="loading">
      <template v-if="page">
        <!-- 页头：标题 + 元信息 + 操作 -->
        <header class="page-header">
          <el-button :icon="ArrowLeft" aria-label="返回 Wiki 库" @click="back" />
          <div class="page-info">
            <div class="page-title-row">
              <span class="page-title" :title="page.title">{{ page.title }}</span>
              <el-tag size="small" effect="plain">{{ PAGE_TYPE_LABELS[page.page_type] || page.page_type }}</el-tag>
              <el-tag v-if="page.edited_by_human" size="small" type="warning" effect="plain">人工修正</el-tag>
            </div>
            <div class="page-meta">
              <span>版本 v{{ page.version }}</span>
              <span class="meta-sep">|</span>
              <span>更新于 {{ formatDateTime(page.updated_at) }}</span>
              <template v-if="page.generated_model">
                <span class="meta-sep">|</span>
                <span>生成模型 {{ page.generated_model }}</span>
              </template>
            </div>
          </div>
          <div class="page-actions">
            <el-button v-if="canEdit && !['overview', 'qa'].includes(page.page_type)" :loading="regenLoading" @click="regenerate">重新生成</el-button>
            <el-button v-if="canEdit && page.page_type !== 'overview'" @click="openEdit">编辑</el-button>
            <el-dropdown v-if="canEdit" trigger="click" placement="bottom-end" @command="pageCommand">
              <el-button link>更多<el-icon style="margin-left: 2px"><ArrowDown /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="remove" divided style="color: var(--el-color-danger)">删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </header>

        <!-- 正文：markdown 渲染 + wikilink 跳转 -->
        <div class="page-body md-body" @click="onContentClick" v-html="rendered" />

        <!-- 溯源区 -->
        <div v-if="page.source_refs.length" class="source-panel">
          <div class="source-title">{{ page.page_type === 'qa' ? '来源问题' : '溯源原料' }}</div>
          <div class="source-chips">
            <template v-for="(ref, i) in page.source_refs" :key="i">
              <el-button v-if="ref.document_id" link type="primary" @click="gotoSource(ref)">{{ ref.document_name || ref.document_id }}</el-button>
              <span v-else-if="ref.question" class="source-question" :title="ref.question">{{ ref.question }}</span>
              <span v-else-if="ref.document_name" class="source-question">{{ ref.document_name }}</span>
            </template>
          </div>
        </div>
      </template>
      <el-empty v-else-if="!loading && !error" description="页面不存在或已被删除" />
    </div>

    <!-- 编辑弹窗：markdown 源码 + 预览切换 -->
    <el-dialog v-model="editVisible" title="编辑页面" width="min(860px, 94vw)" :close-on-click-modal="false" class="wiki-edit-dialog">
      <el-form label-width="80px">
        <el-form-item label="页面标题" required>
          <el-input v-model="editForm.title" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="内容">
          <div class="editor-wrap">
            <div class="editor-toolbar">
              <el-radio-group v-model="editPreview" size="small">
                <el-radio-button :value="false">编辑</el-radio-button>
                <el-radio-button :value="true">预览</el-radio-button>
              </el-radio-group>
              <span class="hint">支持 [[页面标题]] 互链与 ^[来源:文档名] 溯源标记</span>
            </div>
            <el-input v-if="!editPreview" v-model="editForm.content" type="textarea" :rows="18"
                      placeholder="输入 markdown 内容" class="editor-area" />
            <div v-else class="page-body md-body preview" v-html="renderContent(editForm.content)" @click="onContentClick" />
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<style scoped>
.wiki-page-view { padding: 24px; }
.content { background: white; padding: 20px 28px; border-radius: 8px; flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.page-header { display: flex; align-items: center; gap: 14px; padding-bottom: 14px; border-bottom: 1px solid var(--el-border-color-lighter); flex-shrink: 0; }
.page-info { flex: 1; min-width: 0; }
.page-title-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.page-title { font-size: 18px; font-weight: 600; color: #303133; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.page-meta { margin-top: 4px; display: flex; align-items: center; gap: 8px; font-size: 12px; color: #909399; }
.meta-sep { color: var(--el-border-color); }
.page-actions { flex: none; display: flex; align-items: center; gap: 4px; }
.page-body { flex: 1; min-height: 0; overflow-y: auto; padding: 18px 4px; line-height: 1.75; font-size: 14px; color: #303133; }
.source-panel { flex-shrink: 0; border-top: 1px solid var(--el-border-color-lighter); padding-top: 12px; }
.source-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.source-chips { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.source-question { font-size: 13px; color: var(--el-text-color-secondary); }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.editor-wrap { width: 100%; }
.editor-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.editor-area :deep(textarea) { font-family: 'JetBrains Mono', Menlo, Consolas, monospace; font-size: 13px; }
.preview { max-height: 420px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 12px 16px; }
/* wiki 互链与溯源标记（v-html 内容需 :deep） */
.page-body :deep(a.wiki-link) { color: var(--el-color-primary); text-decoration: none; border-bottom: 1px dashed var(--el-color-primary); margin: 0 1px; }
.page-body :deep(a.wiki-link.missing) { color: var(--el-text-color-secondary); border-bottom-color: var(--el-text-color-secondary); }
.page-body :deep(.wiki-src) { display: inline-block; font-size: 11px; color: var(--el-text-color-secondary); background: var(--el-fill-color-light); border-radius: 4px; padding: 0 6px; margin-left: 4px; line-height: 18px; vertical-align: 1px; }
</style>
