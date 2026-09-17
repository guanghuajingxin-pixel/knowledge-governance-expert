<script setup lang="ts">
/**
 * 知识加工 · 二级页【结构化处理】
 *
 * 把文档解析后的结构化 JSON 生成可写库的行数据，并一键写入共享 PG（structured schema）：
 *  1. 上传文档 + 选择 MinerU 解析引擎（本地 mineru-kit V1 / MinerU 云 API）触发异步解析；
 *  2. 设计数据库表结构：选择解析结果 JSON 内指定层级的字段映射到表字段（行源 + 列映射）；
 *  3. 数据预览：验证解析结果是否正确填充到字段；
 *  4. 【写入数据库】：动态建表（已存在则补列追加）并插入，留写入历史。
 *
 * 后端：kb-api /api/v1/structured/*（services/kb-api/app/routes/structured_route.py）。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadInstance } from 'element-plus'
import {
  Delete,
  DocumentAdd,
  Plus,
  Pointer,
  Refresh,
  Upload,
  UploadFilled,
  View,
} from '@element-plus/icons-vue'
import {
  createStructuredSchema,
  createStructuredTask,
  deleteStructuredSchema,
  deleteStructuredTask,
  getStructuredEngines,
  getStructuredTaskContent,
  getStructuredTarget,
  listStructuredSchemas,
  listStructuredTables,
  listStructuredTasks,
  listStructuredWriteLogs,
  previewStructured,
  testStructuredTarget,
  updateStructuredSchema,
  writeStructured,
  type StructuredColumn,
  type StructuredContent,
  type StructuredEngines,
  type StructuredPreview,
  type StructuredSchema,
  type StructuredTableInfo,
  type StructuredTask,
  type StructuredWriteLog,
} from '@/api/structured'
import { setSetting } from '@/api/settings'

// ============================================================
// 1 · 解析任务
// ============================================================
const engines = ref<StructuredEngines | null>(null)
const tasks = ref<StructuredTask[]>([])
const tasksLoading = ref(false)
const currentTaskId = ref('')
const submitting = ref(false)
const uploadRef = ref<UploadInstance>()
const selectedFile = ref<File | null>(null)

const parseForm = reactive({
  engine: 'kit_v1' as 'kit_v1' | 'cloud_v4',
  tier: 'standard',
  ocr_mode: 'auto',
})

const TIER_OPTIONS = [
  { value: 'flash', label: 'flash（快）' },
  { value: 'basic', label: 'basic' },
  { value: 'standard', label: 'standard（高）' },
  { value: 'advanced', label: 'advanced（最高）' },
]

const currentTask = computed(() => tasks.value.find((t) => t.id === currentTaskId.value) || null)

async function loadEngines() {
  try {
    engines.value = await getStructuredEngines()
  } catch {
    engines.value = null
  }
}

async function loadTasks() {
  tasksLoading.value = true
  try {
    const res = await listStructuredTasks(50)
    tasks.value = res.items || []
    if (!currentTaskId.value) {
      const done = tasks.value.find((t) => t.status === 'completed')
      if (done) currentTaskId.value = done.id
    }
  } catch (e: any) {
    ElMessage.error('加载解析任务失败：' + (e?.message || e))
  } finally {
    tasksLoading.value = false
  }
}

function engineLabel(t: StructuredTask): string {
  return t.engine === 'kit_v1' ? '本地 mineru-kit' : 'MinerU 云'
}

function taskTagType(st: string): 'info' | 'primary' | 'success' | 'danger' | 'warning' {
  if (st === 'completed') return 'success'
  if (st === 'failed') return 'danger'
  if (st === 'parsing' || st === 'pending') return 'warning'
  return 'info'
}

function handleFilePick(file: File | undefined | null) {
  if (!file) return
  selectedFile.value = file
}

async function submitParse() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择要解析的文档')
    return
  }
  const eng = engines.value
  if (parseForm.engine === 'kit_v1' && eng && !eng.kit_v1.available) {
    ElMessage.error('本地 mineru-kit V1 服务不可达，请改选 MinerU 云 API 或先启动本地引擎')
    return
  }
  if (parseForm.engine === 'cloud_v4' && eng && !eng.cloud_v4.available) {
    ElMessage.error('未配置 MINERU_API_KEY，无法使用 MinerU 云 API 通道')
    return
  }
  submitting.value = true
  const fd = new FormData()
  fd.append('file', selectedFile.value)
  fd.append('engine', parseForm.engine)
  fd.append('tier', parseForm.tier)
  fd.append('ocr_mode', parseForm.ocr_mode)
  try {
    const res = await createStructuredTask(fd)
    ElMessage.success('已提交解析任务，正在排队/解析中')
    currentTaskId.value = res.id
    selectedFile.value = null
    uploadRef.value?.clearFiles()
    await loadTasks()
  } catch (e: any) {
    ElMessage.error('提交解析失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    submitting.value = false
  }
}

async function handleDeleteTask(row: StructuredTask) {
  try {
    await ElMessageBox.confirm(`删除解析任务「${row.file_name}」？解析结果将一并移除。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteStructuredTask(row.id)
    if (currentTaskId.value === row.id) currentTaskId.value = ''
    ElMessage.success('已删除')
    loadTasks()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}

function selectTask(row: StructuredTask) {
  currentTaskId.value = row.id
  taskContent.value = null
  ElMessage.success(`已选择任务「${row.file_name}」用于映射与预览`)
}

// 轮询未终态任务
let pollTimer: number | null = null
function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(() => {
    if (tasks.value.some((t) => t.status === 'pending' || t.status === 'parsing')) {
      loadTasks()
    }
  }, 4000)
}
function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

// ============================================================
// 2 · 表结构 + 字段映射
// ============================================================
const schemas = ref<StructuredSchema[]>([])
const currentSchemaId = ref('')
const schemaForm = reactive({
  name: '',
  target_table: '',
  row_source: 'content',
  description: '',
  columns: [] as StructuredColumn[],
})

const COLUMN_TYPES = [
  { value: 'text', label: 'text 文本' },
  { value: 'integer', label: 'integer 整数' },
  { value: 'bigint', label: 'bigint 长整数' },
  { value: 'numeric', label: 'numeric 小数' },
  { value: 'boolean', label: 'boolean 布尔' },
  { value: 'date', label: 'date 日期' },
  { value: 'timestamp', label: 'timestamp 时间' },
  { value: 'jsonb', label: 'jsonb 原样JSON' },
]

const ROW_SOURCE_PRESETS = [
  { value: 'content', label: 'content（每个解析块一行，默认）' },
  { value: '$', label: '整篇文档一行（根对象）' },
]

async function loadSchemas() {
  try {
    const res = await listStructuredSchemas()
    schemas.value = res.items || []
  } catch {
    schemas.value = []
  }
}

function resetSchemaForm() {
  currentSchemaId.value = ''
  schemaForm.name = ''
  schemaForm.target_table = ''
  schemaForm.row_source = 'content'
  schemaForm.description = ''
  schemaForm.columns = [
    { name: 'block_type', type: 'text', path: 'type' },
    { name: 'block_text', type: 'text', path: 'text' },
    { name: 'page_no', type: 'integer', path: 'page_idx' },
  ]
}

function pickSchema(id: string) {
  const sc = schemas.value.find((x) => x.id === id)
  if (!sc) return
  currentSchemaId.value = sc.id
  schemaForm.name = sc.name
  schemaForm.target_table = sc.target_table
  schemaForm.row_source = sc.row_source || 'content'
  schemaForm.description = sc.description || ''
  schemaForm.columns = (sc.columns || []).map((c) => ({ ...c }))
  preview.value = null
}

function addColumn() {
  schemaForm.columns.push({ name: '', type: 'text', path: '' })
}

function removeColumn(idx: number) {
  schemaForm.columns.splice(idx, 1)
}

async function saveSchema() {
  if (!schemaForm.name.trim()) {
    ElMessage.warning('请填写方案名称')
    return
  }
  if (!schemaForm.target_table.trim()) {
    ElMessage.warning('请填写目标表名（小写字母/数字/下划线）')
    return
  }
  const validCols = schemaForm.columns.filter((c) => c.name.trim())
  if (!validCols.length) {
    ElMessage.warning('至少配置一列映射')
    return
  }
  const payload = {
    name: schemaForm.name.trim(),
    target_table: schemaForm.target_table.trim(),
    row_source: schemaForm.row_source.trim() || 'content',
    columns: validCols,
    description: schemaForm.description,
  }
  try {
    if (currentSchemaId.value) {
      await updateStructuredSchema(currentSchemaId.value, payload)
      ElMessage.success('方案已更新')
    } else {
      const created = await createStructuredSchema(payload)
      currentSchemaId.value = created.id
      ElMessage.success('方案已保存')
    }
    await loadSchemas()
  } catch (e: any) {
    ElMessage.error('保存方案失败：' + (e?.response?.data?.detail || e?.message || e))
  }
}

async function handleDeleteSchema() {
  if (!currentSchemaId.value) return
  try {
    await ElMessageBox.confirm('删除该映射方案？已写入的目标表数据不受影响。', '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteStructuredSchema(currentSchemaId.value)
    ElMessage.success('已删除')
    resetSchemaForm()
    loadSchemas()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}

// ---- JSON 字段路径快选 ----
const taskContent = ref<StructuredContent | null>(null)
const contentLoading = ref(false)
const pickerVisible = ref(false)
const pickingIndex = ref(-1)
const pickerPaths = ref<{ path: string; preview: string }[]>([])

async function ensureContent() {
  if (!currentTaskId.value) {
    ElMessage.warning('请先在「1 · 解析任务」中选择一条已完成的任务')
    return false
  }
  if (taskContent.value && taskContent.value.id === currentTaskId.value) return true
  contentLoading.value = true
  try {
    taskContent.value = await getStructuredTaskContent(currentTaskId.value)
    return true
  } catch (e: any) {
    ElMessage.error('加载解析结果失败：' + (e?.message || e))
    return false
  } finally {
    contentLoading.value = false
  }
}

function flattenPaths(obj: unknown, prefix: string, depth: number, out: { path: string; preview: string }[]) {
  if (depth > 3 || obj == null) return
  if (Array.isArray(obj)) {
    if (obj.length) flattenPaths(obj[0], `${prefix}[0]`, depth + 1, out)
    return
  }
  if (typeof obj === 'object') {
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      const p = prefix ? `${prefix}.${k}` : k
      if (v != null && typeof v !== 'object') {
        out.push({ path: p, preview: String(v).slice(0, 60) })
      } else {
        flattenPaths(v, p, depth + 1, out)
      }
    }
  }
}

async function openPathPicker(idx: number) {
  const ok = await ensureContent()
  if (!ok) return
  pickingIndex.value = idx
  const root: Record<string, unknown> = { content: taskContent.value?.content || [] }
  // 行源首元素作为路径根（与后端 build_rows 一致）
  let sample: unknown = root
  const rs = schemaForm.row_source.trim() || 'content'
  if (rs !== '$' && rs !== 'root') {
    sample = (taskContent.value?.content || [])[0] || {}
  }
  const out: { path: string; preview: string }[] = []
  flattenPaths(sample, '', 0, out)
  pickerPaths.value = out
  pickerVisible.value = true
}

function applyPickedPath(p: string) {
  if (pickingIndex.value >= 0 && schemaForm.columns[pickingIndex.value]) {
    schemaForm.columns[pickingIndex.value].path = p
    schemaForm.columns[pickingIndex.value].const = null
  }
  pickerVisible.value = false
}

// ============================================================
// 3 · 数据预览
// ============================================================
const preview = ref<StructuredPreview | null>(null)
const previewLoading = ref(false)

async function runPreview() {
  if (!currentTaskId.value) {
    ElMessage.warning('请先选择一条已完成的解析任务')
    return
  }
  previewLoading.value = true
  try {
    preview.value = await previewStructured(
      currentSchemaId.value
        ? { task_id: currentTaskId.value, schema_id: currentSchemaId.value }
        : {
            task_id: currentTaskId.value,
            row_source: schemaForm.row_source,
            columns: schemaForm.columns.filter((c) => c.name.trim()),
          },
      50,
    )
    if (preview.value.warnings?.length) {
      ElMessage.warning(preview.value.warnings.join('；'))
    } else {
      ElMessage.success(`预览生成 ${preview.value.total} 行`)
    }
  } catch (e: any) {
    ElMessage.error('预览失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    previewLoading.value = false
  }
}

// ============================================================
// 4 · 写入数据库
// ============================================================
const writeLogs = ref<StructuredWriteLog[]>([])
const tables = ref<StructuredTableInfo[]>([])
const writing = ref(false)

// ---- 写入目标库连接配置（settings 表 structured_db_url；留空=跟随系统数据库） ----
const target = ref<{ url_masked: string; source: string } | null>(null)
const targetInput = ref('')
const targetTesting = ref(false)
const targetSaving = ref(false)

async function loadTarget() {
  try {
    target.value = await getStructuredTarget()
  } catch {
    target.value = null
  }
}

async function handleTestTarget() {
  targetTesting.value = true
  try {
    const res = await testStructuredTarget(targetInput.value.trim())
    if (res.ok) {
      ElMessage.success(`连接成功：${res.message}`)
    } else {
      ElMessage.error(`连接失败：${res.message}`)
    }
  } catch (e: any) {
    ElMessage.error('测试失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    targetTesting.value = false
  }
}

async function handleSaveTarget(followSystem = false) {
  targetSaving.value = true
  try {
    await setSetting({ key: 'structured_db_url', value: followSystem ? '' : targetInput.value.trim() })
    ElMessage.success(followSystem ? '已改为跟随系统数据库' : '写入目标库配置已保存')
    targetInput.value = ''
    await Promise.all([loadTarget(), loadTables()])
  } catch (e: any) {
    ElMessage.error('保存配置失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    targetSaving.value = false
  }
}

async function loadWriteLogs() {
  try {
    const res = await listStructuredWriteLogs(50)
    writeLogs.value = res.items || []
  } catch {
    writeLogs.value = []
  }
}

async function loadTables() {
  try {
    const res = await listStructuredTables()
    tables.value = res.items || []
  } catch {
    tables.value = []
  }
}

async function handleWrite() {
  if (!currentTaskId.value) {
    ElMessage.warning('请先选择一条已完成的解析任务')
    return
  }
  if (!currentSchemaId.value) {
    ElMessage.warning('写入需先保存映射方案（点「保存方案」）')
    return
  }
  const target = schemaForm.target_table || '（未命名）'
  const rowCount = preview.value?.total
  try {
    await ElMessageBox.confirm(
      `确认把解析结果写入数据库表 structured.${target}？` +
        (rowCount != null ? `预计 ${rowCount} 行。` : '') +
        '表不存在将自动创建；已存在则补列后追加。',
      '写入确认',
      { type: 'warning', confirmButtonText: '写入数据库', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  writing.value = true
  try {
    const res = await writeStructured({ task_id: currentTaskId.value, schema_id: currentSchemaId.value })
    ElMessage.success(`写入成功：${res.target_table} 共 ${res.rows_written} 行`)
    await Promise.all([loadWriteLogs(), loadTables()])
  } catch (e: any) {
    ElMessage.error('写入失败：' + (e?.response?.data?.detail || e?.message || e))
    await loadWriteLogs()
  } finally {
    writing.value = false
  }
}

function fmtTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

function formatCell(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'object') return JSON.stringify(v, null, 0)
  return String(v)
}

onMounted(async () => {
  resetSchemaForm()
  await Promise.all([loadEngines(), loadTasks(), loadSchemas(), loadWriteLogs(), loadTables(), loadTarget()])
  startPolling()
})

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="structured-page">
    <!-- 1 · 解析任务 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span>1 · 上传与解析</span>
          <div class="header-actions">
            <el-tag v-if="engines" size="small" :type="engines.kit_v1.available ? 'success' : 'info'" effect="plain">
              本地 mineru-kit：{{ engines.kit_v1.available ? '可用' : '不可达' }}
            </el-tag>
            <el-tag v-if="engines" size="small" :type="engines.cloud_v4.available ? 'success' : 'info'" effect="plain">
              MinerU 云：{{ engines.cloud_v4.available ? '已配 Key' : '未配 Key' }}
            </el-tag>
            <el-button link type="primary" size="small" :icon="Refresh" @click="loadTasks">刷新</el-button>
          </div>
        </div>
      </template>

      <el-row :gutter="16">
        <el-col :xs="24" :md="10">
          <el-upload
            ref="uploadRef"
            drag
            :auto-upload="false"
            :show-file-list="false"
            :on-change="(file: any) => handleFilePick(file?.raw as File)"
            class="dropzone"
          >
            <el-icon class="drop-icon"><UploadFilled /></el-icon>
            <div class="drop-text">拖拽文档到此处，或 <em>点击选择</em></div>
            <div class="drop-hint">支持 PDF / PNG / JPG / DOCX / PPTX / XLSX 等 MinerU 可解析格式</div>
          </el-upload>
          <div v-if="selectedFile" class="file-info">
            <span class="file-name">{{ selectedFile.name }}</span>
            <el-button link type="danger" size="small" @click="selectedFile = null">移除</el-button>
          </div>

          <el-form label-position="top" class="opts-form">
            <el-form-item label="MinerU 解析引擎">
              <el-select v-model="parseForm.engine" style="width: 100%">
                <el-option label="本地 mineru-kit V1（不出内网）" value="kit_v1" />
                <el-option label="MinerU 云 API（需 Key）" value="cloud_v4" />
              </el-select>
            </el-form-item>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="解析等级 tier">
                  <el-select v-model="parseForm.tier" style="width: 100%">
                    <el-option v-for="t in TIER_OPTIONS" :key="t.value" :label="t.label" :value="t.value" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="OCR 模式">
                  <el-select v-model="parseForm.ocr_mode" style="width: 100%">
                    <el-option label="auto 自动" value="auto" />
                    <el-option label="txt 原生文本" value="txt" />
                    <el-option label="ocr 强制OCR" value="ocr" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-button type="primary" :icon="Upload" :loading="submitting" class="submit-btn" @click="submitParse">
              触发解析
            </el-button>
          </el-form>
        </el-col>

        <el-col :xs="24" :md="14">
          <el-table
            v-loading="tasksLoading"
            :data="tasks"
            size="small"
            max-height="360"
            empty-text="暂无解析任务：左侧上传文档并触发解析"
            highlight-current-row
          >
            <el-table-column label="文档" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <div class="mono small">{{ (row as StructuredTask).file_name }}</div>
                <div class="muted small">{{ engineLabel(row as StructuredTask) }} · {{ (row as StructuredTask).tier }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="taskTagType((row as StructuredTask).status)" size="small" effect="light">
                  {{ (row as StructuredTask).status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="块数" width="70">
              <template #default="{ row }">
                <span class="small">{{ (row as StructuredTask).block_count }}</span>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="160">
              <template #default="{ row }">
                <span class="small muted">{{ fmtTime((row as StructuredTask).created_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button
                  link
                  type="primary"
                  size="small"
                  :icon="Pointer"
                  :disabled="(row as StructuredTask).status !== 'completed'"
                  @click="selectTask(row as StructuredTask)"
                >选用</el-button>
                <el-button link type="danger" size="small" :icon="Delete" @click="handleDeleteTask(row as StructuredTask)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="currentTask" class="hint current-task">
            当前任务：<b>{{ currentTask.file_name }}</b>（{{ currentTask.block_count }} 块）
            <template v-if="currentTask.error"> · 错误：{{ currentTask.error }}</template>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 2 · 表结构 + 字段映射 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span>2 · 表结构与字段映射</span>
          <div class="header-actions">
            <el-select
              :model-value="currentSchemaId"
              placeholder="已保存方案（可选）"
              clearable
              size="small"
              style="width: 220px"
              @change="(v: string) => (v ? pickSchema(v) : resetSchemaForm())"
            >
              <el-option v-for="s in schemas" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
            <el-button link type="primary" size="small" :icon="DocumentAdd" @click="saveSchema">保存方案</el-button>
            <el-button
              link
              type="danger"
              size="small"
              :icon="Delete"
              :disabled="!currentSchemaId"
              @click="handleDeleteSchema"
            >删除方案</el-button>
          </div>
        </div>
      </template>

      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :xs="24" :md="8">
            <el-form-item label="方案名称">
              <el-input v-model="schemaForm.name" placeholder="如：年报-财务指标表" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-form-item label="目标表名（structured schema 下）">
              <el-input v-model="schemaForm.target_table" placeholder="如：annual_finance">
                <template #prepend>structured.</template>
              </el-input>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-form-item label="行源（JSON 内指定层级的数组）">
              <el-select v-model="schemaForm.row_source" filterable allow-create style="width: 100%">
                <el-option v-for="p in ROW_SOURCE_PRESETS" :key="p.value" :label="p.label" :value="p.value" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <el-table :data="schemaForm.columns" size="small" empty-text="暂无列：点「添加列」开始设计表结构">
        <el-table-column label="列名" width="180">
          <template #default="{ $index }">
            <el-input v-model="schemaForm.columns[$index].name" placeholder="列名（小写下划线）" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="类型" width="150">
          <template #default="{ $index }">
            <el-select v-model="schemaForm.columns[$index].type" size="small" style="width: 100%">
              <el-option v-for="t in COLUMN_TYPES" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="JSON 字段路径（行内相对）" min-width="240">
          <template #default="{ $index }">
            <div class="path-cell">
              <el-input
                v-model="schemaForm.columns[$index].path"
                placeholder="如：text / page_idx / table_body"
                size="small"
                :disabled="schemaForm.columns[$index].const != null && schemaForm.columns[$index].const !== ''"
              />
              <el-button link type="primary" size="small" :icon="View" @click="openPathPicker($index)">选</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="常量值（可选，支持 {file_name} 等占位）" min-width="220">
          <template #default="{ $index }">
            <el-input
              v-model="schemaForm.columns[$index].const"
              placeholder="留空=取 JSON 路径"
              size="small"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="70" fixed="right">
          <template #default="{ $index }">
            <el-button link type="danger" size="small" :icon="Delete" @click="removeColumn($index)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="mapping-footer">
        <el-button size="small" plain :icon="Plus" @click="addColumn">添加列</el-button>
        <span class="hint">
          路径语法：<code>text</code>、<code>page_idx</code>、<code>bbox[0]</code>；行源为数组时每个元素一行。
          常量列支持占位符 <code>{file_name}</code> <code>{task_id}</code> <code>{engine}</code> <code>{parsed_at}</code>。
        </span>
      </div>
    </el-card>

    <!-- 3 · 数据预览 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span>3 · 数据预览</span>
          <div class="header-actions">
            <el-button type="primary" size="small" plain :icon="View" :loading="previewLoading" @click="runPreview">
              生成预览
            </el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-for="(w, i) in preview?.warnings || []"
        :key="'w' + i"
        type="warning"
        :title="w"
        show-icon
        :closable="false"
        class="preview-warn"
      />
      <div v-if="preview" class="preview-meta hint">
        共 {{ preview.total }} 行（展示前 {{ preview.rows.length }} 行）
      </div>
      <el-table
        v-if="preview"
        :data="preview.rows"
        size="small"
        max-height="360"
        border
        empty-text="预览无数据：请检查行源与字段路径"
      >
        <el-table-column type="index" label="#" width="50" />
        <el-table-column
          v-for="col in preview.columns"
          :key="col"
          :prop="col"
          :label="col"
          min-width="160"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <span class="small">{{ formatCell((row as Record<string, unknown>)[col]) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="点「生成预览」验证解析结果是否正确填充到字段" :image-size="70" />
    </el-card>

    <!-- 4 · 写入数据库 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span>4 · 写入数据库</span>
          <div class="header-actions">
            <el-button link type="primary" size="small" :icon="Refresh" @click="() => { loadWriteLogs(); loadTables() }">
              刷新
            </el-button>
            <el-button type="primary" size="small" :icon="Upload" :loading="writing" @click="handleWrite">
              写入数据库
            </el-button>
          </div>
        </div>
      </template>

      <div class="target-bar">
        <div class="target-current">
          <span class="label">当前写入目标库：</span>
          <code class="mono small">{{ target?.url_masked || '—' }}</code>
          <el-tag size="small" type="info" effect="plain">{{ target?.source || '未知' }}</el-tag>
        </div>
        <div class="target-edit">
          <el-input
            v-model="targetInput"
            placeholder="postgresql://user:pass@host:port/db（留空=跟随系统数据库）"
            style="width: 420px"
            clearable
          />
          <el-button plain :loading="targetTesting" @click="handleTestTarget">测试连接</el-button>
          <el-button type="primary" plain :loading="targetSaving" @click="handleSaveTarget(false)">
            保存配置
          </el-button>
          <el-button plain :loading="targetSaving" @click="handleSaveTarget(true)">跟随系统库</el-button>
        </div>
      </div>

      <el-row :gutter="16">
        <el-col :xs="24" :md="14">
          <div class="sub-title">写入历史</div>
          <el-table :data="writeLogs" size="small" max-height="280" empty-text="暂无写入记录">
            <el-table-column label="目标表" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="mono small">structured.{{ (row as StructuredWriteLog).target_table }}</span>
              </template>
            </el-table-column>
            <el-table-column label="行数" width="80">
              <template #default="{ row }">
                <span class="small">{{ (row as StructuredWriteLog).rows_written }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag
                  :type="(row as StructuredWriteLog).status === 'success' ? 'success' : 'danger'"
                  size="small"
                  effect="light"
                >{{ (row as StructuredWriteLog).status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="时间" width="160">
              <template #default="{ row }">
                <span class="small muted">{{ fmtTime((row as StructuredWriteLog).created_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="错误" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="small muted">{{ (row as StructuredWriteLog).error || '—' }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-col>
        <el-col :xs="24" :md="10">
          <div class="sub-title">structured schema 下的表</div>
          <el-table :data="tables" size="small" max-height="280" empty-text="尚未创建任何目标表">
            <el-table-column label="表名" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="mono small">{{ (row as StructuredTableInfo).table }}</span>
              </template>
            </el-table-column>
            <el-table-column label="行数" width="100">
              <template #default="{ row }">
                <span class="small">{{ (row as StructuredTableInfo).rows }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="hint write-hint">
            写入目标为上方配置的目标库（默认跟随系统共享 PostgreSQL）；表建在其 structured schema 下，不存在自动创建，已存在补列后追加。
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- JSON 字段路径快选弹窗 -->
    <el-dialog v-model="pickerVisible" title="选择 JSON 字段路径" width="560px">
      <div class="hint picker-hint">
        以下为当前任务行源首元素的可映射字段（点选即填入该列路径）：
      </div>
      <div v-loading="contentLoading" class="picker-list">
        <div
          v-for="p in pickerPaths"
          :key="p.path"
          class="picker-item"
          @click="applyPickedPath(p.path)"
        >
          <code class="picker-path">{{ p.path }}</code>
          <span class="picker-preview muted">{{ p.preview }}</span>
        </div>
        <el-empty v-if="!pickerPaths.length && !contentLoading" description="无可映射字段" :image-size="60" />
      </div>
    </el-dialog>
  </div>
</template>

<script lang="ts">
export default {
  name: 'StructuredProcess',
}
</script>

<style scoped>
.structured-page {
  padding: 12px 16px 24px;
  min-height: 100%;
  background: #f5f7fa;
}
.section-card {
  margin-bottom: 14px;
  border-radius: 10px;
}
.section-card :deep(.el-card__header) {
  padding: 10px 14px;
  background: #eaf2fb;
  border-bottom: 1px solid #d7e1ec;
}
.section-card :deep(.el-card__body) { padding: 14px; }
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 14px;
  font-weight: 600;
  color: #1f3864;
  flex-wrap: wrap;
}
.card-header .header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 400;
  flex-wrap: wrap;
}
.hint { color: #909399; font-size: 12px; line-height: 1.7; font-weight: 400; }
.small { font-size: 12px; }
.muted { color: #909399; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

/* 上传 */
.dropzone :deep(.el-upload-dragger) {
  background: #eaf2fb;
  border: 2px dashed #4a90d9;
  border-radius: 8px;
  padding: 18px 12px;
}
.dropzone :deep(.el-upload-dragger:hover) {
  background: #dceaf8;
  border-color: #2f6da8;
}
.drop-icon { font-size: 36px; color: #4a90d9; margin-bottom: 4px; }
.drop-text { color: #5a6b7b; font-size: 13px; }
.drop-text em { color: #1f3864; font-weight: 600; font-style: normal; }
.drop-hint { margin-top: 4px; font-size: 12px; color: #909399; }
.file-info {
  margin-top: 8px;
  padding: 6px 10px;
  background: #f0f7ff;
  border: 1px solid #d7e1ec;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12.5px;
}
.file-info .file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.opts-form { margin-top: 10px; }
.opts-form :deep(.el-form-item) { margin-bottom: 12px; }
.opts-form :deep(.el-form-item__label) { font-size: 12px; color: #6b7280; padding-bottom: 4px; }
.submit-btn { width: 100%; }
.current-task { margin-top: 8px; }

/* 映射 */
.path-cell { display: flex; align-items: center; gap: 4px; }
.mapping-footer {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.mapping-footer code {
  background: #f4f4f5;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11.5px;
}

/* 预览 */
.preview-warn { margin-bottom: 8px; }
.preview-meta { margin-bottom: 8px; }

/* 写入 */
.sub-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.write-hint { margin-top: 8px; }
.target-bar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px 12px;
  background: #fafcff;
  border: 1px solid #e5e8ee;
  border-radius: 8px;
}
.target-current {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.target-current .label {
  font-size: 12.5px;
  color: #606266;
  white-space: nowrap;
}
.target-edit {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* 路径快选 */
.picker-hint { margin-bottom: 8px; }
.picker-list { max-height: 380px; overflow: auto; }
.picker-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
}
.picker-item:hover { background: #ecf5ff; }
.picker-path {
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 12.5px;
  color: #1f3864;
  min-width: 140px;
}
.picker-preview {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
