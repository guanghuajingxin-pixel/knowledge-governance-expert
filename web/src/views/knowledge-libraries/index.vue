<script setup lang="ts">
/**
 * 知识库（检索抽象层）- RAGFlow / DIFY 知识库镜像管理
 * 仅登记 platform + dataset_id 引用（镜像），供智能体检索选库；
 * 检索策略由抽象层按平台内部决定，本页不支持导入/解析新文档。
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Edit, Delete } from '@element-plus/icons-vue'
import {
  listKnowledgeLibraries,
  createKnowledgeLibrary,
  updateKnowledgeLibrary,
  deleteKnowledgeLibrary,
  type KnowledgeLibrary,
  type LibraryPlatform,
} from '@/api/knowledge-library'
import { listDifyDatasets } from '@/api/dify'
import { listRagflowDatasets } from '@/api/ragflow'

const PLATFORM_LABEL: Record<LibraryPlatform, string> = {
  dify: 'DIFY',
  ragflow: 'RagFlow',
}
const PLATFORM_TAG: Record<LibraryPlatform, 'success' | 'warning'> = {
  dify: 'success',
  ragflow: 'warning',
}

// ===== 列表 =====
const libraries = ref<KnowledgeLibrary[]>([])
const loading = ref(false)
const filterPlatform = ref<'' | LibraryPlatform>('')

// 引擎文档数（挂载时拉取引擎库列表做镜像映射，失败降级为 —）
const docCountMap = ref<Map<string, number>>(new Map())

const filteredLibraries = computed(() =>
  filterPlatform.value
    ? libraries.value.filter((l) => l.platform === filterPlatform.value)
    : libraries.value,
)

const stats = computed(() => ({
  total: libraries.value.length,
  dify: libraries.value.filter((l) => l.platform === 'dify').length,
  ragflow: libraries.value.filter((l) => l.platform === 'ragflow').length,
  enabled: libraries.value.filter((l) => l.enabled).length,
}))

function docCount(row: KnowledgeLibrary): number | null {
  return docCountMap.value.get(`${row.platform}:${row.dataset_id}`) ?? null
}

async function loadLibraries() {
  loading.value = true
  try {
    libraries.value = await listKnowledgeLibraries()
  } catch (e: any) {
    ElMessage.error('加载知识库列表失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function loadDocCounts() {
  // 引擎库列表仅用于展示文档数；任一平台失败不影响另一平台
  const [difyRes, ragflowRes] = await Promise.allSettled([listDifyDatasets(), listRagflowDatasets()])
  const map = new Map<string, number>()
  if (difyRes.status === 'fulfilled' && difyRes.value?.items) {
    for (const d of difyRes.value.items) map.set(`dify:${d.id}`, d.document_count ?? 0)
  }
  if (ragflowRes.status === 'fulfilled' && ragflowRes.value?.items) {
    for (const d of ragflowRes.value.items) map.set(`ragflow:${d.id}`, d.document_count ?? 0)
  }
  docCountMap.value = map
}

onMounted(() => {
  loadLibraries()
  loadDocCounts()
})

// ===== 新增 / 编辑弹窗 =====
const dialogVisible = ref(false)
const isEdit = ref(false)
const currentId = ref<number | null>(null)

const form = reactive({
  name: '',
  platform: 'ragflow' as LibraryPlatform,
  dataset_id: '',
  description: '',
  enabled: true,
})

function openAddDialog() {
  isEdit.value = false
  currentId.value = null
  Object.assign(form, {
    name: '',
    platform: filterPlatform.value || 'ragflow',
    dataset_id: '',
    description: '',
    enabled: true,
  })
  dialogVisible.value = true
}

function openEditDialog(row: KnowledgeLibrary) {
  isEdit.value = true
  currentId.value = row.id
  Object.assign(form, {
    name: row.name,
    platform: row.platform,
    dataset_id: row.dataset_id,
    description: row.description || '',
    enabled: row.enabled,
  })
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.name.trim()) return ElMessage.warning('请输入知识库名称')
  if (!isEdit.value && !form.dataset_id.trim()) return ElMessage.warning('请先从平台选择知识库')
  try {
    if (isEdit.value && currentId.value) {
      await updateKnowledgeLibrary(currentId.value, { name: form.name, description: form.description })
      ElMessage.success('已保存')
    } else {
      await createKnowledgeLibrary({
        name: form.name,
        platform: form.platform,
        dataset_id: form.dataset_id,
        description: form.description,
        enabled: form.enabled,
      })
      ElMessage.success('知识库已登记')
    }
    dialogVisible.value = false
    loadLibraries()
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.message || e))
  }
}

// ===== 启用开关（单状态文案：控件与状态同行） =====
async function handleToggle(row: KnowledgeLibrary) {
  try {
    const updated = await updateKnowledgeLibrary(row.id, { enabled: !row.enabled })
    row.enabled = updated.enabled
  } catch (e: any) {
    ElMessage.error('状态更新失败：' + (e?.message || e))
  }
}

// ===== 删除 =====
async function handleDelete(row: KnowledgeLibrary) {
  try {
    await ElMessageBox.confirm(
      `确认删除知识库「${row.name}」？仅移除镜像登记，不影响 ${PLATFORM_LABEL[row.platform]} 平台上的原知识库。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteKnowledgeLibrary(row.id)
    ElMessage.success('已删除')
    loadLibraries()
  } catch {
    // 用户取消
  }
}

// ===== 引擎知识库选择弹窗（RAGFlow / DIFY 复用） =====
interface EngineItem { id: string; name: string; meta: string }
const pickerVisible = ref(false)
const pickerLoading = ref(false)
const pickerError = ref('')
const pickerKeyword = ref('')
const pickerItems = ref<EngineItem[]>([])
const registeredIds = ref<Set<string>>(new Set())

const pickerLabel = computed(() => PLATFORM_LABEL[form.platform])

const filteredPickerItems = computed(() => {
  const kw = pickerKeyword.value.trim().toLowerCase()
  if (!kw) return pickerItems.value
  return pickerItems.value.filter(
    (i) => i.name.toLowerCase().includes(kw) || i.id.toLowerCase().includes(kw),
  )
})

function isRegistered(item: EngineItem): boolean {
  return registeredIds.value.has(item.id)
}

async function openPicker() {
  pickerVisible.value = true
  pickerKeyword.value = ''
  pickerError.value = ''
  pickerItems.value = []
  pickerLoading.value = true
  try {
    // 已登记的同平台库置灰，避免重复添加（拉全量，不受页面筛选影响）
    const all = await listKnowledgeLibraries().catch(() => [] as KnowledgeLibrary[])
    registeredIds.value = new Set(
      all.filter((l) => l.platform === form.platform).map((l) => l.dataset_id),
    )
    if (form.platform === 'ragflow') {
      const res = await listRagflowDatasets()
      if (res.error) { pickerError.value = res.error; return }
      pickerItems.value = (res.items || []).map((d) => ({
        id: d.id, name: d.name, meta: `文档 ${d.document_count ?? 0} · 分块 ${d.chunk_count ?? 0}`,
      }))
    } else {
      const res = await listDifyDatasets()
      if (res.error) { pickerError.value = res.error; return }
      pickerItems.value = (res.items || []).map((d: any) => ({
        id: d.id, name: d.name, meta: `文档 ${d.document_count ?? 0}`,
      }))
    }
  } catch (e: any) {
    pickerError.value = e?.message || `获取 ${pickerLabel.value} 知识库失败`
  } finally {
    pickerLoading.value = false
  }
}

function pickItem(item: EngineItem) {
  if (isRegistered(item)) return
  form.name = item.name
  form.dataset_id = item.id
  pickerVisible.value = false
  ElMessage.success(`已选择「${item.name}」`)
}

function fmtTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="kl-page">
    <!-- 统计卡片 -->
    <div class="kl-stats">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-label">知识库总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-dify">{{ stats.dify }}</div>
        <div class="stat-label">DIFY</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-ragflow">{{ stats.ragflow }}</div>
        <div class="stat-label">RagFlow</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-enabled">{{ stats.enabled }}</div>
        <div class="stat-label">已开放检索</div>
      </div>
    </div>

    <!-- 列表 -->
    <div class="kl-content">
      <div class="page-intro">
        统一登记 RAGFlow / DIFY 知识库镜像供智能体检索；检索策略由知识库层按平台自动决定，此处不支持导入或解析新文档。
      </div>
      <div class="filter-bar">
        <span class="filter-label">平台筛选：</span>
        <el-radio-group v-model="filterPlatform">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="dify">DIFY</el-radio-button>
          <el-radio-button value="ragflow">RagFlow</el-radio-button>
        </el-radio-group>
        <div class="filter-actions">
          <el-button :icon="Refresh" :loading="loading" @click="loadLibraries">刷新</el-button>
          <el-button type="primary" :icon="Plus" @click="openAddDialog">添加知识库</el-button>
        </div>
      </div>

      <el-table
        :data="filteredLibraries"
        v-loading="loading"
        stripe
        style="width: 100%"
        empty-text="暂无知识库，点击「添加知识库」从 RAGFlow / DIFY 选择登记"
      >
        <el-table-column prop="name" label="知识库名称" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="lib-name">
              <el-tag :type="PLATFORM_TAG[row.platform as LibraryPlatform]" size="small" effect="light" class="type-tag">
                {{ PLATFORM_LABEL[row.platform as LibraryPlatform] }}
              </el-tag>
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="文档数" width="90" align="center">
          <template #default="{ row }">
            <span>{{ docCount(row as KnowledgeLibrary) ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="desc">{{ (row as KnowledgeLibrary).description || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="dataset_id" label="数据集 ID" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="dataset-id">{{ (row as KnowledgeLibrary).dataset_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="165">
          <template #default="{ row }">
            <span class="desc">{{ fmtTime((row as KnowledgeLibrary).updated_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="开放检索" width="130">
          <template #default="{ row }">
            <div class="switch-line">
              <el-switch
                :model-value="(row as KnowledgeLibrary).enabled"
                @change="handleToggle(row as KnowledgeLibrary)"
              />
              <span class="switch-text" :class="{ off: !(row as KnowledgeLibrary).enabled }">
                {{ (row as KnowledgeLibrary).enabled ? '已开放' : '已停用' }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <div class="action-btns">
              <el-button link type="primary" :icon="Edit" size="small" @click="openEditDialog(row as KnowledgeLibrary)">编辑</el-button>
              <el-button link type="danger" :icon="Delete" size="small" @click="handleDelete(row as KnowledgeLibrary)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑知识库' : '添加知识库'"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="90px" class="kl-form">
        <el-form-item label="知识库平台" required>
          <el-radio-group v-model="form.platform" :disabled="isEdit" @change="form.dataset_id = ''">
            <el-radio-button value="ragflow">RagFlow</el-radio-button>
            <el-radio-button value="dify">DIFY</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="选择知识库" required>
          <div class="picker-row">
            <el-input
              :model-value="form.dataset_id"
              :placeholder="isEdit ? '' : '点击右侧按钮从平台选择'"
              readonly
              style="flex: 1"
            />
            <el-button :disabled="isEdit" @click="openPicker">从{{ pickerLabel }}选择</el-button>
          </div>
          <div class="form-hint">仅做镜像引用，文档与解析仍在原平台维护。</div>
        </el-form-item>
        <el-form-item label="知识库名称" required>
          <el-input v-model="form.name" placeholder="选择后自动填入，可修改" maxlength="200" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选，说明该知识库的用途" />
        </el-form-item>
        <el-form-item v-if="!isEdit" label="开放检索">
          <div class="switch-line">
            <el-switch v-model="form.enabled" />
            <span class="switch-text" :class="{ off: !form.enabled }">{{ form.enabled ? '已开放' : '已停用' }}</span>
          </div>
          <div class="form-hint">停用后，企业问答将无法检索该知识库</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">{{ isEdit ? '保存修改' : '登记知识库' }}</el-button>
      </template>
    </el-dialog>

    <!-- 引擎知识库选择弹窗（RAGFlow / DIFY 复用） -->
    <el-dialog v-model="pickerVisible" :title="`从 ${pickerLabel} 选择知识库`" width="560px" :close-on-click-modal="false">
      <el-input v-model="pickerKeyword" clearable placeholder="按名称或 ID 搜索知识库" style="margin-bottom: 12px" />
      <div
        v-loading="pickerLoading"
        style="max-height: 400px; overflow: auto; border: 1px solid var(--el-border-color); border-radius: 6px"
      >
        <div v-if="pickerError" style="padding: 16px; color: var(--el-color-danger); font-size: 13px">{{ pickerError }}</div>
        <div v-else-if="filteredPickerItems.length === 0" style="padding: 24px; text-align: center; color: var(--el-text-color-secondary)">
          {{ pickerLoading ? '加载中…' : '暂无匹配的知识库' }}
        </div>
        <div v-else>
          <div
            v-for="item in filteredPickerItems"
            :key="item.id"
            class="engine-item"
            :class="{ 'engine-item-disabled': isRegistered(item) }"
            @click="pickItem(item)"
          >
            <div class="engine-name">
              {{ item.name }}
              <el-tag v-if="isRegistered(item)" size="small" type="info" effect="light" class="reg-tag">已登记</el-tag>
              <span class="engine-meta">{{ item.meta }}</span>
            </div>
            <div class="engine-id">{{ item.id }}</div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="pickerVisible = false">取消</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kl-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 16px 20px 20px;
}

/* 统计卡片 */
.kl-stats {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.stat-card {
  flex: 1;
  background: #fff;
  border-radius: 8px;
  padding: 14px 18px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}

.stat-dify { color: #67c23a; }
.stat-ragflow { color: #f56c6c; }
.stat-enabled { color: #2b6bff; }

.stat-label {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

/* 列表 */
.kl-content {
  flex: 1;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  overflow: auto;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.page-intro {
  font-size: 13px;
  color: #909399;
  margin-bottom: 12px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.filter-label {
  font-size: 13px;
  color: #666;
}

.filter-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.filter-actions .el-button + .el-button {
  margin-left: 0;
}

.lib-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

.type-tag {
  flex-shrink: 0;
}

.desc {
  color: #999;
  font-size: 13px;
}

.dataset-id {
  font-family: 'Menlo', 'Consolas', monospace;
  font-size: 12px;
  color: #666;
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
}

.switch-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.switch-text {
  font-size: 12px;
  color: var(--el-color-success);
}

.switch-text.off {
  color: var(--el-color-info);
}

.action-btns {
  display: flex;
  gap: 4px;
}

/* 表单 */
.kl-form {
  padding: 0 12px;
}

.picker-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.form-hint {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

/* 引擎知识库选择列表 */
.engine-item {
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--el-border-color-lighter);
  transition: background 0.15s;
}

.engine-item:hover {
  background: var(--el-color-primary-light-9);
}

.engine-item:last-child {
  border-bottom: none;
}

/* 已登记的知识库置灰不可选 */
.engine-item-disabled {
  cursor: not-allowed;
  background: #fafafa;
}

.engine-item-disabled:hover {
  background: #fafafa;
}

.engine-item-disabled .engine-name,
.engine-item-disabled .engine-id {
  color: var(--el-text-color-placeholder);
}

.engine-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.engine-id {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: 'Menlo', 'Consolas', monospace;
  margin-top: 2px;
}

.engine-meta {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.reg-tag {
  margin-left: 6px;
  flex-shrink: 0;
}
</style>
