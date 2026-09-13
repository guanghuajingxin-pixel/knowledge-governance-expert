<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { buildTree, createSource, testSourceDraft, updateSource } from '@/api/sync'
import type { Source, SourcePayload, TreeNode } from '@/types/sync'
import { listKnowledgeSources, fetchDingtalkFolderSnapshot } from '@/api/knowledge-center'
import type { KnowledgeSource } from '@/types/knowledge-center'
import { useRouter } from 'vue-router'
import PipelineInputs from '@/components/collection/PipelineInputs.vue'
import { cronLabel } from './cron'

const router = useRouter()

const props = defineProps<{ visible: boolean; source: Source | null }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'saved'): void }>()

const form = reactive<SourcePayload>({
  name: '',
  workspace_id: '',
  root_node_id: '',
  start_dir: '',
  backend_type: 'dify',
  dify_dataset_name: '',
  dify_dataset_id: '',
  delete_policy: 'sync',
  cron: '0 2 * * *',
  enabled: true,
  pipeline_inputs: {},
})

const saving = ref(false)
const testing = ref(false)
const testedSignature = ref('')

// ============ 定时任务便捷选择（频率 + 星期 + 时间 → cron） ============
const WEEK_OPTIONS = [
  { label: '周日', value: 0 }, { label: '周一', value: 1 }, { label: '周二', value: 2 },
  { label: '周三', value: 3 }, { label: '周四', value: 4 }, { label: '周五', value: 5 },
  { label: '周六', value: 6 },
]
const cronFreq = ref<'daily' | 'weekly' | 'workday' | 'hourly' | 'custom'>('daily')
const cronWeekday = ref(1) // cron dow：0/7=周日，1=周一…
const cronTime = ref('17:00') // HH:mm

// 从既有 cron 反解析出便捷选择状态；无法识别时回退「自定义」
function parseCron(expr: string) {
  const parts = (expr || '').trim().split(/\s+/)
  if (parts.length !== 5) { cronFreq.value = 'custom'; return }
  const [min, hour, dom, mon, dow] = parts
  if (dom !== '*' || mon !== '*') { cronFreq.value = 'custom'; return }
  if (hour === '*' && min === '0') { cronFreq.value = 'hourly'; return }
  if (!/^\d+$/.test(min) || !/^\d+$/.test(hour)) { cronFreq.value = 'custom'; return }
  cronTime.value = `${hour.padStart(2, '0')}:${min.padStart(2, '0')}`
  if (dow === '*') { cronFreq.value = 'daily'; return }
  if (dow === '1-5') { cronFreq.value = 'workday'; return }
  if (/^\d+$/.test(dow)) { cronFreq.value = 'weekly'; cronWeekday.value = Number(dow) % 7; return }
  cronFreq.value = 'custom'
}

// 便捷选择变化时生成/回填 cron
function syncCron() {
  const [h, m] = (cronTime.value || '17:00').split(':')
  if (cronFreq.value === 'custom') return // 自定义由用户手输，不覆盖
  if (cronFreq.value === 'hourly') { form.cron = '0 * * * *'; return }
  const dow = cronFreq.value === 'weekly' ? String(cronWeekday.value) : '*'
  const workday = cronFreq.value === 'workday' ? '1-5' : dow
  form.cron = `${Number(m) || 0} ${Number(h) || 0} * * ${workday}`
}

const dingtalkSources = ref<KnowledgeSource[]>([])
const workspaceLoading = ref(false)
const difySources = ref<KnowledgeSource[]>([])
const difyDatasetLoading = ref(false)
const difyDatasetError = ref('')
const treeData = ref<TreeNode[]>([])
const treeLoading = ref(false)
const filterText = ref('')
const selectedNodeId = ref('')
const treeRef = ref<any>(null)
const currentDingtalkSource = ref<KnowledgeSource | null>(null)

const pipelineForm = ref<InstanceType<typeof PipelineInputs>>()
function onDatasetChange(datasetId: string) {
  form.dify_dataset_name = difySources.value.find((item) => item.external_id === datasetId)?.name || ''
  form.pipeline_inputs = {}
}
// 目录树数据源：优先读 dingtalk_folder_stats 文件夹快照（知识源登记/知识缺口「刷新」时
// 后台遍历写入，DB 只读秒开）；快照缺失时回退实时 buildTree 遍历钉钉。
// 快照 path 不带前导斜杠、根为空串，按「父路径 = 去掉最后一段」还原成树。
function buildTreeFromSnapshot(folders: Array<{ node_id: string; path: string }>): TreeNode[] {
  const pathMap = new Map<string, TreeNode>()
  const roots: TreeNode[] = []
  const sorted = folders.filter((f) => f.path).sort((a, b) => a.path.localeCompare(b.path))
  for (const f of sorted) {
    const sep = f.path.lastIndexOf('/')
    const name = sep >= 0 ? f.path.slice(sep + 1) : f.path
    const parentPath = sep >= 0 ? f.path.slice(0, sep) : ''
    const node: TreeNode = { nodeId: f.node_id, name, category: 'OTHER', hasChildren: true, children: [] }
    pathMap.set(f.path, node)
    const parent = parentPath ? pathMap.get(parentPath) : undefined
    if (parent) parent.children!.push(node)
    else roots.push(node)
  }
  const markLeaves = (nodes: TreeNode[]) => {
    for (const n of nodes) {
      if (n.children && n.children.length) markLeaves(n.children)
      else n.hasChildren = false
    }
  }
  markLeaves(roots)
  return roots
}

const treeKey = computed(() => `full:${form.workspace_id || 'empty'}`)
const expandedKeys = computed(() => (treeData.value.length ? [treeData.value[0].nodeId] : []))

const isFileNode = (node: TreeNode) => node.category === 'DOCUMENT' || node.category === 'ALIDOC'

const treeProps = {
  label: 'name',
  children: 'children',
  disabled: (data: any) => isFileNode(data),
  isLeaf: (data: any) => isFileNode(data) || data.hasChildren === false,
}

function getDingtalkRootNodeId(source: KnowledgeSource): string {
  return (source.config?.root_node_id as string) || source.external_id
}

function makeFullRoot(source: KnowledgeSource, children: TreeNode[], rootNodeId?: string): TreeNode {
  return {
    nodeId: rootNodeId || getDingtalkRootNodeId(source),
    name: source.name || '知识库根目录',
    category: 'OTHER',
    hasChildren: children.length > 0,
    children,
  }
}

watch(
  () => props.visible,
  async (visible) => {
    if (!visible) return
    const source = props.source
    form.name = source?.name || ''
    form.workspace_id = source?.workspace_id || ''
    form.root_node_id = source?.root_node_id || ''
    form.start_dir = source?.start_dir || ''
    form.backend_type = source?.backend_type || 'dify'
    form.dify_dataset_name = source?.dify_dataset_name || ''
    form.dify_dataset_id = source?.dify_dataset_id || ''
    form.delete_policy = source?.delete_policy || 'sync'
    form.cron = source?.cron || '0 2 * * *'
    parseCron(form.cron)
    form.enabled = source?.enabled ?? true
    form.pipeline_inputs = { ...(source?.pipeline_inputs || {}) }
    testedSignature.value = ''
    selectedNodeId.value = ''
    filterText.value = ''
    currentDingtalkSource.value = null
    treeData.value = []
    await Promise.all([loadDingtalkSources(), loadDifySources()])
    if (!form.dify_dataset_id) {
      const matches = difySources.value.filter((item) => item.name === form.dify_dataset_name)
      if (matches.length === 1) form.dify_dataset_id = matches[0].external_id
    }
    if (form.workspace_id) {
      const ks = dingtalkSources.value.find((item) => item.external_id === form.workspace_id)
      currentDingtalkSource.value = ks || null
      selectedNodeId.value = form.root_node_id || ''
      if (ks) loadWorkspaceTree()
    }
  },
)

async function loadDingtalkSources() {
  workspaceLoading.value = true
  try {
    dingtalkSources.value = await listKnowledgeSources({ source_type: 'dingtalk_workspace', enabled_only: true })
  } catch {
    /* request 拦截器已提示 */
  } finally {
    workspaceLoading.value = false
  }
}

async function loadDifySources() {
  difyDatasetLoading.value = true
  difyDatasetError.value = ''
  // 目标库列表按引擎类型取：只列已登记为知识源的库（不实时列引擎全部库）
  const sourceType = form.backend_type === 'ragflow' ? 'ragflow_dataset' : 'dify_dataset'
  try {
    difySources.value = await listKnowledgeSources({ source_type: sourceType, enabled_only: true })
  } catch (error: any) {
    difySources.value = []
    difyDatasetError.value = error?.response?.data?.detail || error?.message || '加载目标知识库失败'
  } finally {
    difyDatasetLoading.value = false
  }
}

// 切换目标引擎：清空已选目标库并按新引擎重新拉取已登记库
async function onEngineChange() {
  form.dify_dataset_id = ''
  form.dify_dataset_name = ''
  form.pipeline_inputs = {}
  testedSignature.value = ''
  await loadDifySources()
}

const engineLabel = computed(() => (form.backend_type === 'ragflow' ? 'RAGFlow' : 'Dify'))

function goRegisterSource() {
  router.push('/knowledge-sources')
  emit('update:visible', false)
}

function onWorkspaceChange(workspaceId: string) {
  form.workspace_id = workspaceId
  form.root_node_id = ''
  form.start_dir = ''
  selectedNodeId.value = ''
  filterText.value = ''
  currentDingtalkSource.value = null
  treeData.value = []
  if (!workspaceId) return
  const ks = dingtalkSources.value.find((item) => item.external_id === workspaceId)
  if (ks) {
    currentDingtalkSource.value = ks
    loadWorkspaceTree()
  }
}

async function loadWorkspaceTree() {
  const ks = currentDingtalkSource.value
  if (!ks) return
  const apply = async () => {
    await nextTick()
    treeRef.value?.filter(filterText.value.trim())
    // 编辑场景恢复已保存目录的高亮（数据晚于 current-node-key 到达时需手动设置）
    if (selectedNodeId.value) treeRef.value?.setCurrentKey(selectedNodeId.value)
  }
  treeLoading.value = true
  try {
    // 优先读知识治理-知识缺口的文件夹快照（DB 只读，秒开）；快照为空时回退实时遍历
    try {
      const snap = await fetchDingtalkFolderSnapshot(ks.id)
      if (snap.count > 0) {
        const rootId = snap.folders.find((f) => f.path === '')?.node_id
        const wrapped = [makeFullRoot(ks, buildTreeFromSnapshot(snap.folders), rootId)]
        treeData.value = wrapped
        await apply()
        return
      }
    } catch {
      /* 快照接口异常时回退实时拉取 */
    }
    const children = await buildTree(getDingtalkRootNodeId(ks))
    treeData.value = [makeFullRoot(ks, children)]
    await apply()
  } catch {
    /* 请求拦截器已提示；保持现状，可用「刷新」重试 */
  } finally {
    treeLoading.value = false
  }
}

let searchTimer: number | undefined

function onFilterTextChange() {
  if (searchTimer) window.clearTimeout(searchTimer)
  const keyword = filterText.value.trim()
  searchTimer = window.setTimeout(() => treeRef.value?.filter(keyword), 300)
}

function onNodeClick(data: TreeNode, node: any) {
  if (isFileNode(data)) return
  const parts: string[] = []
  let current = node
  while (current) {
    if (current.data && current.data.name) parts.unshift(current.data.name)
    current = current.parent
  }
  const label = parts.join(' / ')
  selectedNodeId.value = data.nodeId
  form.root_node_id = data.nodeId
  form.start_dir = label
}

function nodeMatches(node: TreeNode, keyword: string): boolean {
  if ((node.name || '').toLowerCase().includes(keyword)) return true
  return (node.children || []).some((child) => nodeMatches(child, keyword))
}

function filterNode(value: string, data: any): boolean {
  if (!value) return true
  return nodeMatches(data, value.toLowerCase())
}

function close() { emit('update:visible', false) }

function validateForm(): boolean {
  if (!form.name.trim()) { ElMessage.error('请填写同步源名称'); return false }
  if (!form.workspace_id.trim()) { ElMessage.error('请选择钉钉知识库'); return false }
  if (!form.root_node_id.trim()) { ElMessage.error('请在目录选择中点选要同步的目录'); return false }
  if (!form.dify_dataset_id) { ElMessage.error(`请选择目标 ${engineLabel.value} 知识库`); return false }
  if (pipelineForm.value && !pipelineForm.value.validate()) return false
  return true
}

function formSignature() {
  return JSON.stringify({ ...form })
}

async function save() {
  if (!validateForm()) return
  if (testedSignature.value !== formSignature()) {
    ElMessage.warning('请先测试当前配置并确认连接成功，再保存')
    return
  }
  saving.value = true
  try {
    if (props.source) await updateSource(props.source.id, { ...form })
    else await createSource({ ...form })
    ElMessage.success(props.source ? '同步源已更新' : '同步源已创建')
    emit('saved')
    close()
  } finally { saving.value = false }
}

async function test() {
  if (!validateForm()) return
  testing.value = true
  try {
    const r: any = await testSourceDraft({ ...form })
    const ok = !!r.ok
    if (ok) testedSignature.value = formSignature()
    else testedSignature.value = ''
    ElMessage({ type: ok ? 'success' : 'error', message: ok ? '连接成功' : '连接失败，详见测试结果', duration: 5000 })
  } catch {
    testedSignature.value = ''
  } finally { testing.value = false }
}
</script>

<template>
  <el-dialog :model-value="visible" width="720px" :title="source ? '编辑同步任务' : '新增同步任务'" @close="close">
    <el-form label-position="top">
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
        <el-form-item label="同步任务名称" required>
          <el-input v-model="form.name" placeholder="如：产品手册" />
        </el-form-item>
        <el-form-item label="钉钉知识库" required>
          <el-select v-model="form.workspace_id" filterable clearable placeholder="选择已登记的钉钉知识库" :loading="workspaceLoading" style="width: 100%" @change="onWorkspaceChange">
            <el-option v-for="item in dingtalkSources" :key="item.id" :label="item.name" :value="item.external_id">
              <span>{{ item.name }}</span>
              <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">{{ item.external_id }}</span>
            </el-option>
          </el-select>
          <div v-if="dingtalkSources.length === 0 && !workspaceLoading" style="font-size: 12px; color: var(--el-color-warning); margin-top: 4px">
            暂无已登记的钉钉知识库，请先到<a style="color: var(--el-color-primary); cursor: pointer" @click="goRegisterSource">知识源管理</a>登记。
          </div>
        </el-form-item>
      </div>
      <el-form-item label="目录选择" required>
        <div style="width: 100%">
          <div style="display: flex; gap: 8px; margin-bottom: 8px">
            <el-input v-model="filterText" clearable placeholder="输入关键字过滤目录" style="flex: 1" @input="onFilterTextChange" @clear="onFilterTextChange" />
            <el-button :icon="Refresh" :loading="treeLoading" style="flex-shrink: 0" @click="loadWorkspaceTree()">刷新</el-button>
          </div>
          <div v-loading="treeLoading" style="border: 1px solid var(--el-border-color); border-radius: 6px; max-height: 260px; overflow: auto; padding: 4px">
            <el-tree
              ref="treeRef"
              :key="treeKey"
              :data="treeData"
              node-key="nodeId"
              :props="treeProps"
              :filter-node-method="filterNode"
              :default-expanded-keys="expandedKeys"
              :expand-on-click-node="false"
              highlight-current
              :current-node-key="selectedNodeId"
              empty-text="请先选择知识库"
              @node-click="onNodeClick"
            />
          </div>
          <div style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px">目录列表读取已拉取的文件夹快照（知识源登记或知识缺口页「刷新」时后台生成），秒开不实时调钉钉；快照缺失时自动实时拉取，目录有更新可点「刷新」重新读取。</div>
        </div>
      </el-form-item>
      <el-form-item label="已选目录">
        <el-input v-model="form.start_dir" readonly placeholder="在上方目录选择中点选目录" />
      </el-form-item>
      <el-form-item label="同步目标引擎" required>
        <el-radio-group v-model="form.backend_type" @change="onEngineChange">
          <el-radio-button value="dify">Dify 知识库</el-radio-button>
          <el-radio-button value="ragflow">RAGFlow 知识库</el-radio-button>
        </el-radio-group>
        <div style="font-size:12px;color:var(--el-text-color-secondary);margin-top:4px">钉钉目录同步到哪个引擎。切换引擎会清空已选目标库并重新加载对应引擎已登记的知识库。</div>
      </el-form-item>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
        <el-form-item :label="`目标 ${engineLabel} 知识库`" required>
          <div style="display:flex;gap:8px;width:100%">
            <el-select v-model="form.dify_dataset_id" filterable clearable @change="onDatasetChange" :placeholder="`选择已登记的 ${engineLabel} 知识库`" :loading="difyDatasetLoading" style="flex:1">
              <el-option v-for="item in difySources" :key="item.id" :label="item.name" :value="item.external_id">
                <span>{{ item.name }}</span>
                <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">{{ item.external_id }}</span>
              </el-option>
            </el-select>
          </div>
          <div v-if="difySources.length === 0 && !difyDatasetLoading" style="font-size: 12px; color: var(--el-color-warning); margin-top: 4px">
            暂无已登记的 {{ engineLabel }} 知识库，请先到<a style="color: var(--el-color-primary); cursor: pointer" @click="goRegisterSource">知识源管理</a>登记。
          </div>
          <div v-else style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px">仅显示并使用已登记的 {{ engineLabel }} 知识库。</div>
        </el-form-item>
        <el-form-item label="删除策略">
          <el-select v-model="form.delete_policy" style="width: 100%">
            <el-option label="同步删除（源删除则删目标文档）" value="sync" />
            <el-option label="保留（仅清理状态）" value="keep" />
          </el-select>
        </el-form-item>
      </div>
      <PipelineInputs v-if="visible && form.backend_type === 'dify'" ref="pipelineForm" :dataset-id="form.dify_dataset_id" v-model="form.pipeline_inputs" :disabled="saving || testing" />
      <el-form-item label="定时任务">
        <div style="display:flex;gap:8px;width:100%;flex-wrap:wrap">
          <el-select v-model="cronFreq" style="width:110px" @change="syncCron">
            <el-option label="每天" value="daily" />
            <el-option label="每周" value="weekly" />
            <el-option label="工作日" value="workday" />
            <el-option label="每小时" value="hourly" />
            <el-option label="自定义" value="custom" />
          </el-select>
          <el-select v-if="cronFreq === 'weekly'" v-model="cronWeekday" style="width:100px" @change="syncCron">
            <el-option v-for="w in WEEK_OPTIONS" :key="w.value" :label="w.label" :value="w.value" />
          </el-select>
          <el-time-select
            v-if="cronFreq !== 'custom' && cronFreq !== 'hourly'"
            v-model="cronTime"
            start="00:00"
            end="23:45"
            step="00:15"
            placeholder="选择时间"
            style="width:120px"
            @change="syncCron"
          />
          <el-input
            v-if="cronFreq === 'custom'"
            v-model="form.cron"
            placeholder="如：0 2 * * *（五段式：分 时 日 月 周）"
            style="flex:1;min-width:200px"
          />
        </div>
        <div style="font-size:12px;color:var(--el-text-color-secondary);margin-top:4px">
          当前：<b style="color:var(--el-color-primary)">{{ cronLabel(form.cron) }}</b>（cron：{{ form.cron || '未设置' }}，留空或错误将不参与定时）
        </div>
      </el-form-item>
      <el-form-item label="立即启用">
        <el-switch v-model="form.enabled" :active-text="form.enabled ? '已启用' : '已停用'" aria-label="启用同步任务" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :loading="testing" @click="test">测试连接</el-button>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
