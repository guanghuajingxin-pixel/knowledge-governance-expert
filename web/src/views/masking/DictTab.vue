<script setup lang="ts">
/**
 * 敏感词典：脱敏策略的词典识别来源（复用 sensitive_items）。
 * 在策略里勾选「敏感词典」类型后，命中此处的词条会被识别为对应实体类型并按策略动作脱敏。
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Edit, Delete, Search } from '@element-plus/icons-vue'
import {
  listSensitiveItems,
  createSensitiveItem,
  updateSensitiveItem,
  deleteSensitiveItem,
  type SensitiveItem,
  type SensitiveType,
} from '@/api/sensitive'
import { ENTITY_TYPES, ENTITY_LABEL } from './constants'

const items = ref<SensitiveItem[]>([])
const loading = ref(false)
const filterType = ref<'' | SensitiveType>('')
const keyword = ref('')

const filteredItems = computed(() => {
  let list = items.value
  if (filterType.value) list = list.filter((i) => i.type === filterType.value)
  const kw = keyword.value.trim().toLowerCase()
  if (kw) list = list.filter((i) => i.content.toLowerCase().includes(kw))
  return list
})

async function loadItems() {
  loading.value = true
  try {
    items.value = await listSensitiveItems()
  } catch (e: any) {
    ElMessage.error('加载词典失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

onMounted(loadItems)

// ===== 新增 / 编辑 =====
const dialogVisible = ref(false)
const isEdit = ref(false)
const currentId = ref<number | null>(null)
const saving = ref(false)

const form = reactive({
  content: '',
  type: 'custom' as SensitiveType,
  description: '',
  enabled: true,
})

function openAddDialog() {
  isEdit.value = false
  currentId.value = null
  Object.assign(form, {
    content: '',
    type: filterType.value || 'custom',
    description: '',
    enabled: true,
  })
  dialogVisible.value = true
}

function openEditDialog(row: SensitiveItem) {
  isEdit.value = true
  currentId.value = row.id
  Object.assign(form, {
    content: row.content,
    type: row.type,
    description: row.description || '',
    enabled: row.enabled,
  })
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.content.trim()) return ElMessage.warning('请输入敏感词条内容')
  saving.value = true
  try {
    if (isEdit.value && currentId.value) {
      await updateSensitiveItem(currentId.value, {
        content: form.content,
        type: form.type,
        description: form.description,
        enabled: form.enabled,
      })
      ElMessage.success('已保存')
    } else {
      await createSensitiveItem({
        content: form.content,
        type: form.type,
        description: form.description,
        enabled: form.enabled,
      })
      ElMessage.success('词条已登记')
    }
    dialogVisible.value = false
    loadItems()
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    saving.value = false
  }
}

async function handleToggle(row: SensitiveItem) {
  try {
    const updated = await updateSensitiveItem(row.id, { enabled: !row.enabled })
    row.enabled = updated.enabled
  } catch (e: any) {
    ElMessage.error('状态更新失败：' + (e?.message || e))
  }
}

async function handleDelete(row: SensitiveItem) {
  try {
    await ElMessageBox.confirm(
      `确认删除词条「${row.content}」？删除后不再参与词典识别。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteSensitiveItem(row.id)
    ElMessage.success('已删除')
    loadItems()
  } catch {
    // 用户取消
  }
}

function fmtTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="dt-wrap">
    <div class="tab-intro">
      登记企业敏感词条（客户名、项目代号、内部编号等），作为策略「敏感词典」识别方式的来源；
      条目仅在此维护，是否脱敏、如何脱敏由策略页控制。
    </div>
    <div class="tab-toolbar">
      <span class="filter-label">类型：</span>
      <el-radio-group v-model="filterType" size="small">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button v-for="t in ENTITY_TYPES" :key="t" :value="t">{{ ENTITY_LABEL[t] }}</el-radio-button>
      </el-radio-group>
      <el-input
        v-model="keyword"
        :prefix-icon="Search"
        placeholder="搜索词条"
        clearable
        class="keyword-input"
      />
      <div class="toolbar-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadItems">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openAddDialog">添加词条</el-button>
      </div>
    </div>

    <el-table
      :data="filteredItems"
      v-loading="loading"
      stripe
      style="width: 100%"
      empty-text="暂无词条，点击「添加词条」登记"
    >
      <el-table-column prop="content" label="词条内容" min-width="260" show-overflow-tooltip>
        <template #default="{ row }">
          <div class="item-content">
            <el-tag size="small" effect="light" class="type-tag">
              {{ ENTITY_LABEL[row.type as SensitiveType] }}
            </el-tag>
            <span class="content-text">{{ row.content }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="备注" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="muted">{{ row.description || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="添加时间" width="165">
        <template #default="{ row }">
          <span class="muted">{{ fmtTime(row.created_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <div class="switch-line">
            <el-switch :model-value="row.enabled" @change="handleToggle(row as SensitiveItem)" />
            <span class="switch-text" :class="{ off: !row.enabled }">{{ row.enabled ? '参与识别' : '已停用' }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <div class="action-btns">
            <el-button link type="primary" :icon="Edit" size="small" @click="openEditDialog(row as SensitiveItem)">编辑</el-button>
            <el-button link type="danger" :icon="Delete" size="small" @click="handleDelete(row as SensitiveItem)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑词条' : '添加词条'"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="100px" class="dt-form">
        <el-form-item label="词条内容" required>
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="2"
            maxlength="500"
            show-word-limit
            placeholder="输入需要识别的敏感内容，如客户名、项目代号、内部编号"
          />
        </el-form-item>
        <el-form-item label="实体类型" required>
          <el-radio-group v-model="form.type">
            <el-radio-button v-for="t in ENTITY_TYPES" :key="t" :value="t">{{ ENTITY_LABEL[t] }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选，说明该词条的用途或来源" />
        </el-form-item>
        <el-form-item label="状态">
          <div class="switch-line">
            <el-switch v-model="form.enabled" />
            <span class="switch-text" :class="{ off: !form.enabled }">{{ form.enabled ? '参与识别' : '已停用' }}</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">{{ isEdit ? '保存修改' : '登记' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dt-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tab-intro {
  font-size: 13px;
  color: #909399;
  line-height: 1.6;
}

.tab-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-label {
  font-size: 13px;
  color: #666;
}

.keyword-input {
  width: 200px;
}

.toolbar-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.toolbar-actions .el-button + .el-button {
  margin-left: 0;
}

.item-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

.type-tag {
  flex-shrink: 0;
}

.content-text {
  font-family: 'Menlo', 'Consolas', monospace;
  font-size: 13px;
  color: #303133;
}

.muted {
  color: #909399;
  font-size: 13px;
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

.dt-form {
  padding: 0 12px;
}
</style>
