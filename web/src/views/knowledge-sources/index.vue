<script setup lang="ts">
/**
 * 知识源管理 - 企业知识库注册表
 * 统一登记钉钉知识库、Dify 数据集、业务系统等知识库。
 * 系统内所有「选择知识库」的地方均从此处取数。
 * 其它模块可通过知识库 ID 获取其下的目录与文档。
 */
import { ref, onMounted, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Edit, Delete, Connection } from '@element-plus/icons-vue'
import {
  listKnowledgeSources,
  createKnowledgeSource,
  updateKnowledgeSource,
  deleteKnowledgeSource,
  fetchDingTalkWorkspaces,
} from '@/api/knowledge-center'
import { getDingtalkRefreshStatus } from '@/api/governance'
import type { KnowledgeSource, KnowledgeSourcePayload, DingTalkWorkspace } from '@/types/knowledge-center'

// 知识库类型配置
const SOURCE_TYPE_OPTIONS: Array<{ value: KnowledgeSource['source_type']; label: string }> = [
  { value: 'dingtalk_workspace', label: '钉钉知识库' },
  { value: 'dify_dataset', label: 'Dify 知识库' },
  { value: 'business_system', label: '业务系统' },
]

function getTypeLabel(type: string): string {
  return SOURCE_TYPE_OPTIONS.find((t) => t.value === type)?.label || type
}

function getTypeTagType(type: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  const map: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    dingtalk_workspace: 'primary',
    dify_dataset: 'success',
    business_system: 'warning',
  }
  return map[type] || 'info'
}

// 列表
const sources = ref<KnowledgeSource[]>([])
const loading = ref(false)
const filterType = ref<string>('')

// 弹窗
const dialogVisible = ref(false)
const isEdit = ref(false)
const currentId = ref<number | null>(null)
const formRef = ref()

const form = reactive<KnowledgeSourcePayload>({
  name: '',
  source_type: 'dingtalk_workspace',
  external_id: '',
  description: '',
  config: null,
  enabled: true,
})

// 钉钉知识库选择弹窗
const wsDialogVisible = ref(false)
const wsLoading = ref(false)
const dingtalkWorkspaces = ref<DingTalkWorkspace[]>([])
const wsKeyword = ref('')
const wsError = ref('')

async function openWorkspacePicker() {
  wsDialogVisible.value = true
  wsKeyword.value = ''
  wsError.value = ''
  dingtalkWorkspaces.value = []
  wsLoading.value = true
  try {
    const res = await fetchDingTalkWorkspaces()
    if (res.error) {
      wsError.value = res.error
      return
    }
    dingtalkWorkspaces.value = res.items || []
  } catch (e: any) {
    wsError.value = e?.message || '获取钉钉知识库失败'
  } finally {
    wsLoading.value = false
  }
}

const filteredWorkspaces = computed(() => {
  const kw = wsKeyword.value.trim().toLowerCase()
  if (!kw) return dingtalkWorkspaces.value
  return dingtalkWorkspaces.value.filter((w) => w.name.toLowerCase().includes(kw))
})

function pickWorkspace(ws: DingTalkWorkspace) {
  form.name = ws.name
  form.external_id = ws.id
  form.config = { root_node_id: ws.root_node_id }
  wsDialogVisible.value = false
  ElMessage.success(`已选择「${ws.name}」`)
}

const isDingtalk = computed(() => form.source_type === 'dingtalk_workspace')

async function loadSources() {
  loading.value = true
  try {
    sources.value = await listKnowledgeSources(
      filterType.value ? { source_type: filterType.value } : undefined,
    )
  } catch (e: any) {
    ElMessage.error('加载知识库列表失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function openAddDialog() {
  isEdit.value = false
  currentId.value = null
  Object.assign(form, {
    name: '',
    source_type: 'dingtalk_workspace',
    external_id: '',
    description: '',
    config: null,
    enabled: true,
  })
  dialogVisible.value = true
}

function openEditDialog(source: KnowledgeSource) {
  isEdit.value = true
  currentId.value = source.id
  Object.assign(form, {
    name: source.name,
    source_type: source.source_type,
    external_id: source.external_id,
    description: source.description || '',
    config: source.config,
    enabled: source.enabled,
  })
  dialogVisible.value = true
}

function closeDialog() {
  dialogVisible.value = false
}

async function handleSave() {
  if (!form.name.trim()) return ElMessage.warning('请输入知识库名称')
  if (!form.external_id.trim()) return ElMessage.warning('请输入知识库 ID')
  try {
    if (isEdit.value && currentId.value) {
      await updateKnowledgeSource(currentId.value, form)
      ElMessage.success('更新成功')
    } else {
      await createKnowledgeSource(form)
      ElMessage.success('创建成功')
      // 钉钉知识库：登记后后端自动触发目录快照刷新，这里跟踪并在列表中展示进度
      if (form.source_type === 'dingtalk_workspace' && form.enabled) {
        trackFolderRefresh(form.external_id, form.name)
      }
    }
    dialogVisible.value = false
    loadSources()
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.message || e))
  }
}

// ===== 钉钉知识库目录快照刷新进度（登记后自动预热）=====
const refreshingIds = ref<Set<string>>(new Set())

function trackFolderRefresh(externalId: string, name: string) {
  refreshingIds.value.add(externalId)
  ElMessage.info(`「${name}」目录获取已启动，完成后可在知识治理-知识缺口中查看`)
  const timer = window.setInterval(async () => {
    try {
      const st = await getDingtalkRefreshStatus(externalId)
      if (!st.running) {
        window.clearInterval(timer)
        refreshingIds.value.delete(externalId)
        if (st.error) ElMessage.error(`「${name}」目录获取失败：${st.error}`)
        else ElMessage.success(`「${name}」目录获取完成（${st.folder_count} 个文件夹）`)
      }
    } catch {
      window.clearInterval(timer)
      refreshingIds.value.delete(externalId)
    }
  }, 3000)
}

function isRefreshing(row: KnowledgeSource): boolean {
  return refreshingIds.value.has(row.external_id)
}

async function handleDelete(source: KnowledgeSource) {
  try {
    await ElMessageBox.confirm(
      `确认删除知识库「${source.name}」？删除后引用该知识库的同步源等将无法正常工作。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteKnowledgeSource(source.id)
    ElMessage.success('已删除')
    loadSources()
  } catch {
    // 用户取消
  }
}

async function handleToggle(source: KnowledgeSource) {
  try {
    await updateKnowledgeSource(source.id, { enabled: !source.enabled })
    source.enabled = !source.enabled
  } catch (e: any) {
    ElMessage.error('状态更新失败：' + (e?.message || e))
  }
}

// 统计
const stats = computed(() => ({
  total: sources.value.length,
  dingtalk: sources.value.filter((s) => s.source_type === 'dingtalk_workspace').length,
  dify: sources.value.filter((s) => s.source_type === 'dify_dataset').length,
  business: sources.value.filter((s) => s.source_type === 'business_system').length,
  enabled: sources.value.filter((s) => s.enabled).length,
}))

onMounted(() => {
  loadSources()
})
</script>

<template>
  <div class="ks-page">
    <!-- 顶部栏 -->
    <div class="ks-header">
      <div class="ks-header-left">
        <h2 class="ks-title">
          <el-icon :size="20"><Connection /></el-icon>
          知识源管理
        </h2>
        <span class="ks-subtitle">企业知识库注册表：统一登记钉钉知识库、Dify 知识库、业务系统等。所有知识库选择均从此处取数。</span>
      </div>
      <div class="ks-header-right">
        <el-button :icon="Refresh" :loading="loading" @click="loadSources">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openAddDialog">新增知识库</el-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="ks-stats">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-label">知识库总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-dingtalk">{{ stats.dingtalk }}</div>
        <div class="stat-label">钉钉知识库</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-dify">{{ stats.dify }}</div>
        <div class="stat-label">Dify 数据集</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-business">{{ stats.business }}</div>
        <div class="stat-label">业务系统</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-enabled">{{ stats.enabled }}</div>
        <div class="stat-label">已启用</div>
      </div>
    </div>

    <!-- 列表 -->
    <div class="ks-content">
      <div class="filter-bar">
        <span class="filter-label">类型筛选：</span>
        <el-radio-group v-model="filterType" @change="loadSources">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button v-for="opt in SOURCE_TYPE_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </el-radio-button>
        </el-radio-group>
      </div>

      <el-table :data="sources" v-loading="loading" stripe style="width: 100%" empty-text="暂无知识库登记，点击右上角新增">
        <el-table-column prop="name" label="知识库名称" min-width="180">
          <template #default="{ row }">
            <div class="source-name">
              <el-tag :type="getTypeTagType(row.source_type)" size="small" effect="light" class="type-tag">
                {{ getTypeLabel(row.source_type) }}
              </el-tag>
              <span>{{ row.name }}</span>
              <!-- 钉钉知识库目录快照获取中 -->
              <el-tag v-if="isRefreshing(row as KnowledgeSource)" size="small" type="warning" class="type-tag">
                目录获取中…
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="external_id" label="知识库 ID" min-width="200">
          <template #default="{ row }">
            <span class="external-id">{{ row.external_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="200">
          <template #default="{ row }">
            <span class="desc">{{ row.description || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="配置" min-width="160">
          <template #default="{ row }">
            <span v-if="row.config && Object.keys(row.config).length" class="config-info">
              {{ Object.entries(row.config).map(([k, v]) => `${k}: ${v}`).join(' | ') }}
            </span>
            <span v-else class="desc">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="handleToggle(row as KnowledgeSource)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <div class="action-btns">
              <el-button link type="primary" :icon="Edit" size="small" @click="openEditDialog(row as KnowledgeSource)">编辑</el-button>
              <el-button link type="danger" :icon="Delete" size="small" @click="handleDelete(row as KnowledgeSource)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑知识库' : '新增知识库'"
      width="560px"
      :close-on-click-modal="false"
      @close="closeDialog"
    >
      <el-form ref="formRef" :model="form" label-width="100px" class="ks-form">
        <el-form-item label="知识库名称" required>
          <el-input v-model="form.name" placeholder="如：品质流程IT部" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="知识库类型" required>
          <el-select v-model="form.source_type" style="width: 100%">
            <el-option
              v-for="opt in SOURCE_TYPE_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="知识库 ID" required>
          <div style="display: flex; gap: 8px; width: 100%">
            <el-input v-model="form.external_id" placeholder="钉钉 workspace_id / Dify dataset_id / 业务系统标识" style="flex: 1" />
            <el-button v-if="isDingtalk" @click="openWorkspacePicker">从钉钉选择</el-button>
          </div>
          <div class="form-hint">
            外部系统中的知识库唯一标识。钉钉知识库建议点击「从钉钉选择」自动填入，避免重名混淆。
          </div>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选，描述该知识库的用途" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
          <span class="form-hint">停用后，其它模块将无法选择该知识库</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="closeDialog">取消</el-button>
        <el-button type="primary" @click="handleSave">{{ isEdit ? '保存修改' : '创建知识库' }}</el-button>
      </template>
    </el-dialog>

    <!-- 钉钉知识库选择弹窗 -->
    <el-dialog v-model="wsDialogVisible" title="选择钉钉知识库" width="560px" :close-on-click-modal="false">
      <el-input
        v-model="wsKeyword"
        clearable
        placeholder="按名称搜索知识库"
        style="margin-bottom: 12px"
      />
      <div v-loading="wsLoading" style="max-height: 400px; overflow: auto; border: 1px solid var(--el-border-color); border-radius: 6px">
        <div v-if="wsError" style="padding: 16px; color: var(--el-color-danger); font-size: 13px">{{ wsError }}</div>
        <div v-else-if="filteredWorkspaces.length === 0" style="padding: 24px; text-align: center; color: var(--el-text-color-secondary)">
          {{ wsLoading ? '加载中…' : '暂无匹配的知识库' }}
        </div>
        <div v-else>
          <div
            v-for="ws in filteredWorkspaces"
            :key="ws.id"
            class="ws-item"
            @click="pickWorkspace(ws)"
          >
            <div class="ws-name">{{ ws.name }}</div>
            <div class="ws-id">{{ ws.id }}</div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="wsDialogVisible = false">取消</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ks-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 20px;
  background: #fafbfc;
}

.ks-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.ks-header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ks-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 20px;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
}

.ks-subtitle {
  font-size: 13px;
  color: #888;
}

.ks-header-right {
  display: flex;
  gap: 8px;
}

/* 统计卡片 */
.ks-stats {
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

.stat-dingtalk { color: #2b6bff; }
.stat-dify { color: #67c23a; }
.stat-business { color: #e6a23c; }
.stat-enabled { color: #2b6bff; }

.stat-label {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

/* 列表 */
.ks-content {
  flex: 1;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  overflow: auto;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
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

.source-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

.type-tag {
  flex-shrink: 0;
}

.external-id {
  font-family: 'Menlo', 'Consolas', monospace;
  font-size: 12px;
  color: #666;
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
}

.desc {
  color: #999;
  font-size: 13px;
}

.config-info {
  font-size: 12px;
  color: #666;
  font-family: 'Menlo', 'Consolas', monospace;
}

.action-btns {
  display: flex;
  gap: 4px;
}

/* 表单 */
.ks-form {
  padding: 0 12px;
}

.form-hint {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

/* 钉钉知识库选择列表 */
.ws-item {
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--el-border-color-lighter);
  transition: background 0.15s;
}

.ws-item:hover {
  background: var(--el-color-primary-light-9);
}

.ws-item:last-child {
  border-bottom: none;
}

.ws-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.ws-id {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: 'Menlo', 'Consolas', monospace;
  margin-top: 2px;
}
</style>
