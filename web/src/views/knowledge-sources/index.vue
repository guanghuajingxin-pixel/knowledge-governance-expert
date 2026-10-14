<script setup lang="ts">
/**
 * 知识源管理 - 企业知识库注册表（纯表格列表，参考美云智数字段）
 * 统一登记钉钉知识库、业务系统与本地上传（内置渠道）。
 * 系统内所有「选择知识库」的地方均从此处取数。
 */
import { ref, onMounted, reactive, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { KeyRound, Copy, FileText, MoreHorizontal, Pencil, Trash2, Plus, RefreshCw, Search, ExternalLink, Eye, EyeOff } from '@lucide/vue'
import KgPagination from '@/components/common/KgPagination.vue'
import { formatDateTime } from '@/utils/format'
import {
  listKnowledgeSources,
  createKnowledgeSource,
  updateKnowledgeSource,
  deleteKnowledgeSource,
  fetchDingTalkWorkspaces,
  issueBusinessCredential,
  updateBusinessCredentialLibraries,
  revokeBusinessCredential,
  revealBusinessSecret,
} from '@/api/knowledge-center'
import { listDocumentLibraries } from '@/api/document-library'
import { getDingtalkRefreshStatus } from '@/api/governance'
import type {
  KnowledgeSource, KnowledgeSourcePayload, DingTalkWorkspace,
  BusinessCredentialIssued,
} from '@/types/knowledge-center'

// 知识库类型配置（含内置本地上传渠道；新增弹窗仅开放前两类）
const SOURCE_TYPE_OPTIONS: Array<{ value: KnowledgeSource['source_type']; label: string }> = [
  { value: 'dingtalk_workspace', label: '钉钉知识库' },
  { value: 'business_system', label: '业务系统' },
  { value: 'local_upload', label: '本地上传' },
]

// 可手动创建的类型（本地上传为迁移内置的单条渠道记录，禁止手动创建）
const CREATABLE_TYPE_OPTIONS = SOURCE_TYPE_OPTIONS.filter((t) => t.value !== 'local_upload')

function getTypeLabel(type: string): string {
  return SOURCE_TYPE_OPTIONS.find((t) => t.value === type)?.label || type
}

function getTypeTagType(type: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  const map: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    dingtalk_workspace: 'primary',
    business_system: 'warning',
    local_upload: 'success',
  }
  return map[type] || 'info'
}

// 列表
const sources = ref<KnowledgeSource[]>([])
const loading = ref(false)
const statusFilter = ref<'' | 'enabled' | 'disabled'>('')
const keyword = ref('')
// 列表前端过滤 + 分页（接口一次返回全量，按优先级升序，这里按状态/关键词过滤后按页切片展示）
const page = ref(1)
const pageSize = ref(20)
const filteredSources = computed(() => {
  return sources.value.filter((s) => {
    if (statusFilter.value === 'enabled' && !s.enabled) return false
    if (statusFilter.value === 'disabled' && s.enabled) return false
    const kw = keyword.value.trim().toLowerCase()
    if (kw && !s.name.toLowerCase().includes(kw) && !(s.code || '').toLowerCase().includes(kw)) return false
    return true
  })
})
const pagedSources = computed(() => filteredSources.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
// 筛选/搜索变化时回到第 1 页
watch([statusFilter, keyword], () => { page.value = 1 })

/** 构造跳转到原始知识库的 URL；构造不出返回空串 */
function resolveSourceUrl(src: KnowledgeSource): string {
  switch (src.source_type) {
    case 'dingtalk_workspace': {
      // 钉钉知识库入口 = 根节点链接（config.root_node_id 登记时已存）；
      // 缺 root_node_id（早期登记/配置丢失）时不跳转，避免打开错误页面
      const rootNodeId = src.config?.root_node_id
      return rootNodeId
        ? `https://alidocs.dingtalk.com/i/nodes/${encodeURIComponent(rootNodeId)}?utm_scene=team_space`
        : ''
    }
    default:
      return ''
  }
}

function openSource(src: KnowledgeSource) {
  const url = resolveSourceUrl(src)
  if (!url) {
    ElMessage.info('该类型暂不支持跳转到原知识库')
    return
  }
  window.open(url, '_blank', 'noopener')
}

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
  code: '',
  priority: 99,
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
    const [res, registered] = await Promise.all([
      fetchDingTalkWorkspaces(),
      listKnowledgeSources({ source_type: 'dingtalk_workspace' }).catch(
        () => [] as KnowledgeSource[],
      ),
    ])
    registeredIds.value = new Set(registered.map((s) => s.external_id))
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

// 已登记的钉钉知识库 ID（避免重复添加；打开弹窗时拉全量，不受页面类型筛选影响）
const registeredIds = ref<Set<string>>(new Set())

function isRegistered(ws: DingTalkWorkspace): boolean {
  return registeredIds.value.has(ws.id)
}

function pickWorkspace(ws: DingTalkWorkspace) {
  if (isRegistered(ws)) return
  form.name = ws.name
  form.external_id = ws.id
  form.config = { root_node_id: ws.root_node_id }
  wsDialogVisible.value = false
  ElMessage.success(`已选择「${ws.name}」`)
}

const isDingtalk = computed(() => form.source_type === 'dingtalk_workspace')
const isBusiness = computed(() => form.source_type === 'business_system')
const isLocal = computed(() => form.source_type === 'local_upload')

// 弹窗类型选项：编辑内置「本地上传」行时含该类型以正确回显标签；其余场景不提供（禁止手动创建）
const dialogTypeOptions = computed(() =>
  isLocal.value ? SOURCE_TYPE_OPTIONS : CREATABLE_TYPE_OPTIONS,
)

// ===== 业务系统：授权文档库多选与密钥管理 =====
const businessLibraryIds = ref<number[]>([])
const libraryOptions = ref<Array<{ id: number; name: string; enabled: boolean }>>([])

// 编辑弹窗内的凭证详情（AK 常显；SK 掩码，按需 reveal 解密查看）
const editSource = ref<KnowledgeSource | null>(null)
const revealedSecret = ref('')
const revealing = ref(false)

async function toggleRevealSecret() {
  if (revealedSecret.value) {
    revealedSecret.value = ''
    return
  }
  if (!currentId.value) return
  revealing.value = true
  try {
    const res = await revealBusinessSecret(currentId.value)
    revealedSecret.value = res.secret_key
  } catch (e: any) {
    ElMessage.error('获取 SecretKey 失败：' + (e?.message || e))
  } finally {
    revealing.value = false
  }
}

async function loadLibraryOptions() {
  try {
    const libs = await listDocumentLibraries()
    libraryOptions.value = libs.map((l) => ({ id: l.id, name: l.name, enabled: l.enabled }))
  } catch {
    libraryOptions.value = []
  }
}

/** 密钥颁发成功弹窗（SK 只显一次） */
const secretDialogVisible = ref(false)
const issuedCredential = ref<BusinessCredentialIssued | null>(null)

function showSecretDialog(cred: BusinessCredentialIssued) {
  issuedCredential.value = cred
  secretDialogVisible.value = true
}

/** 轮换密钥：旧 AK 立即失效，返回新 AK/SK（SK 只显一次） */
async function handleRotateCredential(src: KnowledgeSource) {
  try {
    await ElMessageBox.confirm(
      `确认轮换「${src.name}」的推送密钥？旧 AccessKeyId 将立即失效，业务系统需更新为新密钥后才能继续推送。`,
      '轮换密钥',
      { type: 'warning', confirmButtonText: '轮换', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const cred = await issueBusinessCredential(src.id, src.credential?.library_ids || [])
    showSecretDialog(cred)
    ElMessage.success('密钥已轮换')
    loadSources()
  } catch (e: any) {
    ElMessage.error('轮换失败：' + (e?.message || e))
  }
}

/** 吊销密钥 */
async function handleRevokeCredential(src: KnowledgeSource) {
  try {
    await ElMessageBox.confirm(
      `确认吊销「${src.name}」的推送密钥？吊销后该业务系统将无法推送，可随时重新颁发。`,
      '吊销密钥',
      { type: 'warning', confirmButtonText: '吊销', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await revokeBusinessCredential(src.id)
    ElMessage.success('密钥已吊销')
    loadSources()
  } catch (e: any) {
    ElMessage.error('吊销失败：' + (e?.message || e))
  }
}

/** 接入说明弹窗（签名规范 + curl 示例） */
const guideDialogVisible = ref(false)
const guideSource = ref<KnowledgeSource | null>(null)

function openGuide(src: KnowledgeSource) {
  guideSource.value = src
  guideDialogVisible.value = true
}

function guideCurlExample(): string {
  const base = window.location.origin
  const lines = [
    '# 1) 计算签名（bash）：对「方法\\n路径\\n时间戳\\nnonce\\n正文sha256」做 HMAC-SHA256',
    'BODY=$(cat 文档.txt)',
    'PATH_URL="/api/v1/ingest/{library_id}/documents"',
    'TS=$(date +%s); NONCE=$(openssl rand -hex 16)',
    "BODY_SHA=$(printf '%s' \"$BODY\" | openssl dgst -sha256 | awk '{print $NF}')",
    "SIGN=$(printf 'POST\\n%s\\n%s\\n%s\\n%s' \"$PATH_URL\" \"$TS\" \"$NONCE\" \"$BODY_SHA\" \\",
    "  | openssl dgst -sha256 -hmac \"$SECRET_KEY\" -hex | awk '{print $NF}')",
    '',
    '# 2) 推送文档（multipart，携带四个签名头）',
    `curl -X POST "${base}\${PATH_URL}" \\`,
    '  -H "X-AK-Id: $ACCESS_KEY_ID" -H "X-Timestamp: $TS" \\',
    '  -H "X-Nonce: $NONCE" -H "X-Signature: $SIGN" \\',
    '  -F "file=@文档.txt" -F "title=文档.txt"',
  ]
  return lines.join('\n')
}

async function copyText(text: string, tip = '已复制') {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(tip)
  } catch {
    ElMessage.error('复制失败，请手动选择复制')
  }
}

async function loadSources() {
  loading.value = true
  try {
    sources.value = await listKnowledgeSources()
  } catch (e: any) {
    ElMessage.error('加载知识源列表失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function openAddDialog() {
  isEdit.value = false
  currentId.value = null
  editSource.value = null
  revealedSecret.value = ''
  Object.assign(form, {
    name: '',
    source_type: 'dingtalk_workspace',
    external_id: '',
    description: '',
    config: null,
    enabled: true,
    code: '',
    priority: 99,
  })
  businessLibraryIds.value = []
  loadLibraryOptions()
  dialogVisible.value = true
}

function openEditDialog(source: KnowledgeSource) {
  isEdit.value = true
  currentId.value = source.id
  editSource.value = source
  revealedSecret.value = ''
  Object.assign(form, {
    name: source.name,
    source_type: source.source_type,
    external_id: source.external_id,
    description: source.description || '',
    config: source.config,
    enabled: source.enabled,
    code: source.code || '',
    priority: source.priority ?? 99,
  })
  businessLibraryIds.value = source.credential ? [...source.credential.library_ids] : []
  if (source.source_type === 'business_system') loadLibraryOptions()
  dialogVisible.value = true
}

function closeDialog() {
  dialogVisible.value = false
}

/** 业务系统 external_id 自动生成（登记后无需用户填写） */
function genBusinessExternalId(): string {
  return `bs-${crypto.randomUUID().replace(/-/g, '').slice(0, 8)}`
}

async function handleSave() {
  if (!form.name.trim()) return ElMessage.warning('请输入知识源名称')
  if (isBusiness.value) {
    // 业务系统：编码必填（用户输入系统编码）；external_id 自动生成；必须先选授权库
    if (!form.code?.trim()) return ElMessage.warning('请输入系统编码')
    if (!form.external_id.trim()) form.external_id = genBusinessExternalId()
    if (!businessLibraryIds.value.length) return ElMessage.warning('请选择该业务系统可推送的文档库')
  } else if (isDingtalk.value && !form.external_id.trim()) {
    return ElMessage.warning('请输入知识库 ID')
  }
  try {
    if (isEdit.value && currentId.value) {
      await updateKnowledgeSource(currentId.value, form)
      // 业务系统：授权库变化同步到凭证白名单（不动 AK/SK）
      if (isBusiness.value && currentId.value) {
        const prevSource = sources.value.find((s) => s.id === currentId.value)
        const prev = prevSource?.credential?.library_ids || []
        const cur = [...businessLibraryIds.value].sort()
        if (!prevSource?.credential) {
          // 尚未颁发（如新增时颁发失败/历史数据）：保存时自动补颁发，SK 仅本次展示
          const cred = await issueBusinessCredential(currentId.value, businessLibraryIds.value)
          dialogVisible.value = false
          showSecretDialog(cred)
          ElMessage.success('已保存并颁发推送密钥')
          loadSources()
          return
        }
        if (JSON.stringify(prev) !== JSON.stringify(cur)) {
          await updateBusinessCredentialLibraries(currentId.value, businessLibraryIds.value)
        }
      }
      ElMessage.success('更新成功')
    } else {
      const created = await createKnowledgeSource(form)
      ElMessage.success('创建成功')
      // 业务系统：创建后立即颁发推送密钥（SK 只显一次）
      if (isBusiness.value) {
        try {
          const cred = await issueBusinessCredential(created.id, businessLibraryIds.value)
          dialogVisible.value = false
          showSecretDialog(cred)
          loadSources()
          return
        } catch (e: any) {
          ElMessage.error('密钥颁发失败（可在行内「更多」中重试轮换）：' + (e?.message || e))
        }
      }
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
      `确认删除知识源「${source.name}」？删除后引用该知识源的同步源等将无法正常工作。`,
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

/** 行内「更多」下拉命令 */
function onRowCommand(cmd: string, src: KnowledgeSource) {
  if (cmd === 'edit') {
    openEditDialog(src)
  } else if (cmd === 'open') {
    openSource(src)
  } else if (cmd === 'toggle') {
    handleToggle(src)
  } else if (cmd === 'delete') {
    handleDelete(src)
  } else if (cmd === 'rotate') {
    handleRotateCredential(src)
  } else if (cmd === 'revoke') {
    handleRevokeCredential(src)
  } else if (cmd === 'guide') {
    openGuide(src)
  }
}

onMounted(() => {
  loadSources()
})
</script>

<template>
  <div class="ks-page">
    <!-- 列表（四段式：工具栏 / 表格 / 分页；参考美云智数知识源管理） -->
    <div class="ks-content">
      <div class="filter-bar">
        <el-button type="primary" :icon="Plus" @click="openAddDialog">新增知识源</el-button>
        <div class="filter-actions">
          <el-select v-model="statusFilter" style="width: 120px" aria-label="状态筛选">
            <el-option label="全部状态" value="" />
            <el-option label="已启用" value="enabled" />
            <el-option label="已停用" value="disabled" />
          </el-select>
          <el-input
            v-model="keyword"
            clearable
            placeholder="搜索名称或编码"
            style="width: 220px"
            :prefix-icon="Search"
          />
          <el-tooltip content="刷新列表" placement="top">
            <el-button :icon="RefreshCw" :loading="loading" aria-label="刷新列表" @click="loadSources" />
          </el-tooltip>
        </div>
      </div>

      <div class="table-fill">
        <el-table
          :data="pagedSources"
          v-loading="loading"
          size="small"
          border
          row-key="id"
          style="width: 100%"
          height="100%"
          empty-text="暂无知识源登记，点击「新增知识源」新增"
        >
          <el-table-column prop="name" label="知识源名称" min-width="240">
            <template #default="{ row }">
              <div class="source-name">
                <el-tag :type="getTypeTagType(row.source_type)" size="small" effect="light" class="type-tag">
                  {{ getTypeLabel(row.source_type) }}
                </el-tag>
                <span class="name-text" :title="row.name">{{ row.name }}</span>
                <!-- 钉钉知识库目录快照获取中 -->
                <el-tag v-if="isRefreshing(row as KnowledgeSource)" size="small" type="warning" class="type-tag">
                  目录获取中…
                </el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="code" label="编码" min-width="190" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="external-id">{{ row.code || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="priority" label="优先级" width="90" align="center" />
          <el-table-column prop="updated_at" label="更新时间" width="170">
            <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column prop="updated_by" label="更新人" width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ row.updated_by || '—' }}</template>
          </el-table-column>
          <el-table-column label="启用" width="80" align="center">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" aria-label="启停知识源" @change="handleToggle(row as KnowledgeSource)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <div class="action-btns">
                <el-button link type="primary" :icon="Pencil" size="small" @click="openEditDialog(row as KnowledgeSource)">编辑</el-button>
                <!-- 内置「本地上传」渠道仅可编辑，无更多操作 -->
                <el-dropdown
                  v-if="row.source_type !== 'local_upload'"
                  trigger="click"
                  placement="bottom-end"
                  @command="(cmd: string) => onRowCommand(cmd, row as KnowledgeSource)"
                >
                  <el-button link type="primary" size="small" aria-label="更多操作">
                    <el-icon :size="14"><MoreHorizontal /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item
                        v-if="row.source_type === 'dingtalk_workspace' && resolveSourceUrl(row as KnowledgeSource)"
                        command="open" :icon="ExternalLink">打开原知识库</el-dropdown-item>
                      <el-dropdown-item v-if="row.source_type === 'business_system'" command="guide" :icon="FileText">接入说明</el-dropdown-item>
                      <el-dropdown-item v-if="row.source_type === 'business_system'" command="rotate" :icon="KeyRound">轮换密钥</el-dropdown-item>
                      <el-dropdown-item v-if="row.source_type === 'business_system' && row.credential?.status === 'active'" command="revoke">吊销密钥</el-dropdown-item>
                      <el-dropdown-item command="toggle" divided>
                        {{ row.enabled ? '停用' : '启用' }}
                      </el-dropdown-item>
                      <el-dropdown-item command="delete" divided :icon="Trash2" style="color: var(--el-color-danger)">删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 分页 -->
      <KgPagination :page="page" :size="pageSize" :total="filteredSources.length" :sizes="[20, 50, 100]"
                    layout="total, sizes, prev, pager, next"
                    @update:page="(p: number) => (page = p)"
                    @update:size="(s: number) => { pageSize = s; page = 1 }" />
    </div>

    <!-- 新增/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑知识源' : '新增知识源'"
      width="560px"
      :close-on-click-modal="false"
      @close="closeDialog"
    >
      <el-form ref="formRef" :model="form" label-width="100px" class="ks-form">
        <el-form-item label="知识源名称" required>
          <el-input v-model="form.name" placeholder="如：品质流程IT部" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="知识源类型" required>
          <el-select v-model="form.source_type" style="width: 100%" :disabled="isEdit">
            <el-option
              v-for="opt in dialogTypeOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="编码" :required="isBusiness">
          <el-input
            v-model="form.code"
            :disabled="isLocal"
            :placeholder="isBusiness ? '请输入系统编码' : '留空自动生成'"
            maxlength="64"
          />
          <div v-if="!isLocal" class="form-hint">
            {{ isBusiness ? '全局唯一，用于标识该业务系统。' : '全局唯一；留空保存时自动生成（KD + 时间戳）。' }}
          </div>
        </el-form-item>
        <el-form-item label="优先级">
          <div class="priority-row">
            <el-input-number v-model="form.priority" :min="1" :max="99" :step="1" step-strictly />
            <span class="form-hint priority-hint">数字越小优先级越高</span>
          </div>
        </el-form-item>
        <!-- 钉钉知识库：workspace ID + 从钉钉选择 -->
        <el-form-item v-if="isDingtalk" label="知识库 ID" required>
          <div style="display: flex; gap: 8px; width: 100%">
            <el-input v-model="form.external_id" placeholder="钉钉 workspace_id" style="flex: 1" />
            <el-button @click="openWorkspacePicker">从钉钉选择</el-button>
          </div>
          <div class="form-hint">
            外部系统中的知识库唯一标识。建议点击「从钉钉选择」实时拉取并自动填入，避免手填错 ID 或重名混淆。
          </div>
        </el-form-item>
        <!-- 业务系统：授权可推送的文档库（密钥绑定白名单）+ 推送密钥详情 -->
        <template v-if="isBusiness">
          <el-form-item label="可推送文档库" required>
            <el-select
              v-model="businessLibraryIds"
              multiple
              filterable
              placeholder="选择该业务系统可推送的文档库"
              style="width: 100%"
            >
              <el-option
                v-for="lib in libraryOptions"
                :key="lib.id"
                :label="lib.name"
                :value="lib.id"
              />
            </el-select>
            <div class="form-hint">
              保存后将颁发推送密钥（AccessKeyId + SecretKey），该密钥只能向以上文档库推送知识。
            </div>
          </el-form-item>
          <!-- 推送密钥详情：编辑时展示（AK 常显 + SK 掩码按需查看） -->
          <el-form-item v-if="isEdit && editSource?.credential" label="推送密钥">
            <div class="cred-box" style="width: 100%">
              <div class="cred-box-row">
                <span class="cred-box-label">AccessKeyId</span>
                <code class="cred-box-value">{{ editSource.credential.access_key_id }}</code>
                <el-button link type="primary" size="small" :icon="Copy"
                           @click="copyText(editSource.credential!.access_key_id, 'AccessKeyId 已复制')">复制</el-button>
              </div>
              <div class="cred-box-row">
                <span class="cred-box-label">SecretKey</span>
                <code class="cred-box-value">{{ revealedSecret || '••••••••••••••••••••••••' }}</code>
                <el-button link type="primary" size="small" :icon="revealedSecret ? EyeOff : Eye"
                           :loading="revealing" @click="toggleRevealSecret">
                  {{ revealedSecret ? '隐藏' : '查看' }}
                </el-button>
                <el-button v-if="revealedSecret" link type="primary" size="small" :icon="Copy"
                           @click="copyText(revealedSecret, 'SecretKey 已复制')">复制</el-button>
              </div>
              <div class="cred-box-row">
                <span class="cred-box-label">密钥状态</span>
                <el-tag size="small" :type="editSource.credential.status === 'active' ? 'success' : 'info'" effect="light">
                  {{ editSource.credential.status === 'active' ? '生效中' : '已吊销' }}
                </el-tag>
                <el-button link type="primary" size="small" :icon="FileText"
                           @click="editSource && openGuide(editSource)">接入说明</el-button>
              </div>
            </div>
            <div class="form-hint">SecretKey 加密存储，点击「查看」按需解密显示；泄露请及时在「更多」中轮换密钥。</div>
          </el-form-item>
          <el-form-item v-else-if="isEdit" label="推送密钥">
            <span class="desc">未颁发——修改授权库保存后将自动颁发（SK 仅颁发时展示一次）。</span>
          </el-form-item>
          <el-form-item v-if="isEdit && form.config === null && form.external_id" label="系统标识">
            <el-input :model-value="form.external_id" disabled />
          </el-form-item>
        </template>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选，描述该知识源的用途" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
          <span class="form-hint">{{ isBusiness ? '停用后推送密钥立即失效，业务系统无法推送' : '停用后，其它模块将无法选择该知识源' }}</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="closeDialog">取消</el-button>
        <el-button type="primary" @click="handleSave">{{ isEdit ? '保存修改' : '创建知识源' }}</el-button>
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
            :class="{ 'ws-item-disabled': isRegistered(ws) }"
            @click="pickWorkspace(ws)"
          >
            <div class="ws-name">
              {{ ws.name }}
              <el-tag v-if="isRegistered(ws)" size="small" type="info" effect="light" class="ws-reg-tag">已登记</el-tag>
            </div>
            <div class="ws-id">{{ ws.id }}</div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="wsDialogVisible = false">取消</el-button>
      </template>
    </el-dialog>

    <!-- 密钥颁发成功弹窗（SK 只显一次） -->
    <el-dialog v-model="secretDialogVisible" title="推送密钥已颁发" width="620px"
               :close-on-click-modal="false" :show-close="false">
      <template v-if="issuedCredential">
        <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 14px">
          SecretKey 仅本次展示一次，关闭弹窗后无法再次查看；请立即复制并妥善保管（泄露将导致未授权推送）。
        </el-alert>
        <div class="cred-box">
          <div class="cred-box-row">
            <span class="cred-box-label">AccessKeyId</span>
            <code class="cred-box-value">{{ issuedCredential.access_key_id }}</code>
            <el-button link type="primary" size="small" :icon="Copy"
                       @click="copyText(issuedCredential.access_key_id, 'AccessKeyId 已复制')">复制</el-button>
          </div>
          <div class="cred-box-row">
            <span class="cred-box-label">SecretKey</span>
            <code class="cred-box-value">{{ issuedCredential.secret_key }}</code>
            <el-button link type="primary" size="small" :icon="Copy"
                       @click="copyText(issuedCredential.secret_key, 'SecretKey 已复制')">复制</el-button>
          </div>
          <div class="cred-box-row">
            <span class="cred-box-label">可推送库</span>
            <span class="cred-box-value">{{ issuedCredential.library_ids.length }} 个文档库</span>
          </div>
        </div>
        <div class="form-hint" style="margin-top: 10px">
          接入方式见卡片菜单「接入说明」：业务系统每次请求用 SecretKey 对「方法 + 路径 + 时间戳 + 随机数 + 正文摘要」做 HMAC-SHA256 签名，密钥本身不会在网络上传输。
        </div>
      </template>
      <template #footer>
        <el-button type="primary" @click="secretDialogVisible = false">我已妥善保管，关闭</el-button>
      </template>
    </el-dialog>

    <!-- 接入说明弹窗（签名规范 + curl 示例） -->
    <el-dialog v-model="guideDialogVisible" title="业务系统接入说明" width="720px">
      <template v-if="guideSource">
        <div v-if="guideSource.credential" class="guide-ak">
          AccessKeyId：<code>{{ guideSource.credential.access_key_id }}</code>
          <el-button link type="primary" size="small" :icon="Copy"
                     @click="copyText(guideSource.credential!.access_key_id, 'AccessKeyId 已复制')">复制</el-button>
          <el-tag size="small" :type="guideSource.credential.status === 'active' ? 'success' : 'info'" effect="light" style="margin-left: 8px">
            {{ guideSource.credential.status === 'active' ? '生效中' : '已吊销' }}
          </el-tag>
        </div>
        <el-alert v-else type="info" :closable="false" show-icon style="margin-bottom: 12px">
          尚未颁发密钥，请先在卡片菜单「轮换密钥」中颁发。
        </el-alert>
        <h4 class="guide-title">签名算法</h4>
        <ol class="guide-list">
          <li>每个请求携带四个头：<code>X-AK-Id</code>（AccessKeyId）、<code>X-Timestamp</code>（Unix 秒）、<code>X-Nonce</code>（16-64 位随机 hex，一次性）、<code>X-Signature</code>（签名 hex）。</li>
          <li>构造签名串（换行符连接，共 5 行）：<code>METHOD</code>、<code>PATH</code>（含 query）、<code>timestamp</code>、<code>nonce</code>、<code>sha256(原始请求体)</code>。</li>
          <li>签名 = <code>HMAC-SHA256(SecretKey, 签名串)</code> 的十六进制小写。</li>
          <li>服务端校验时间窗（±5 分钟）与 nonce 一次性；超限或重放即拒绝。SecretKey 不在请求中出现。</li>
        </ol>
        <h4 class="guide-title">推送接口</h4>
        <p class="guide-list"><code>POST /api/v1/ingest/{library_id}/documents</code>（multipart：<code>file</code> 必填，<code>title</code> 可选覆盖展示名）；目标库须在授权白名单内。</p>
        <h4 class="guide-title">curl 示例（bash）</h4>
        <div class="guide-code">
          <pre>{{ guideCurlExample() }}</pre>
          <el-button link type="primary" size="small" :icon="Copy" class="guide-copy"
                     @click="copyText(guideCurlExample(), '示例已复制')">复制示例</el-button>
        </div>
      </template>
      <template #footer>
        <el-button @click="guideDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ks-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 16px 20px 20px;
}

/* 列表 */
.ks-content {
  flex: 1;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-shrink: 0;
}

/* 视图区撑满剩余高度：表格内部滚动，分页固定吸底 */
.table-fill {
  flex: 1;
  min-height: 0;
}

/* 状态筛选/搜索/刷新与新增按钮同行，靠右 */
.filter-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.filter-actions .el-button + .el-button {
  margin-left: 0;
}

.source-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  min-width: 0;
}

.name-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.action-btns {
  display: flex;
  align-items: center;
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

/* 优先级：数字输入与说明同行 */
.priority-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.priority-hint {
  margin-top: 0;
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

/* 已登记的知识库置灰不可选 */
.ws-item-disabled {
  cursor: not-allowed;
  background: #fafafa;
}

.ws-item-disabled:hover {
  background: #fafafa;
}

.ws-item-disabled .ws-name,
.ws-item-disabled .ws-id {
  color: var(--el-text-color-placeholder);
}

.ws-reg-tag {
  margin-left: 6px;
  flex-shrink: 0;
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

.ws-meta {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

/* 密钥颁发弹窗 */
.cred-box {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 4px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cred-box-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
}
.cred-box-row + .cred-box-row {
  border-top: 1px dashed var(--el-border-color-lighter);
}
.cred-box-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
  width: 96px;
}
.cred-box-value {
  font-family: var(--el-font-family-mono, 'SFMono-Regular', Consolas, monospace);
  font-size: 13px;
  color: var(--el-text-color-primary);
  word-break: break-all;
  flex: 1;
}

/* 接入说明弹窗 */
.guide-ak {
  margin-bottom: 12px;
  font-size: 13px;
}
.guide-ak code {
  font-family: var(--el-font-family-mono, 'SFMono-Regular', Consolas, monospace);
}
.guide-title {
  margin: 14px 0 6px;
  font-size: 14px;
  color: var(--el-text-color-primary);
}
.guide-list {
  margin: 0 0 4px;
  padding-left: 18px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.8;
}
.guide-list code {
  font-family: var(--el-font-family-mono, 'SFMono-Regular', Consolas, monospace);
  background: var(--el-fill-color-light);
  padding: 1px 5px;
  border-radius: 3px;
}
.guide-code {
  position: relative;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
  padding: 10px 12px;
}
.guide-code pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: var(--el-font-family-mono, 'SFMono-Regular', Consolas, monospace);
  color: var(--el-text-color-regular);
}
.guide-copy {
  position: absolute;
  top: 6px;
  right: 8px;
}
</style>
