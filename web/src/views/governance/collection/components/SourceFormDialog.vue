<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { buildTree, createSource, testSourceDraft, updateSource } from '@/api/sync'
import type { Source, SourcePayload, TreeNode } from '@/types/sync'
import { listKnowledgeSources, fetchDingtalkFolderSnapshot } from '@/api/knowledge-center'
import type { KnowledgeSource } from '@/types/knowledge-center'
import { listDocumentLibraries, type DocumentLibrary } from '@/api/document-library'
import { useRouter } from 'vue-router'

const router = useRouter()

const props = defineProps<{ visible: boolean; source: Source | null }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'saved'): void }>()

const form = reactive<SourcePayload>({
  name: '',
  workspace_id: '',
  root_node_id: '',
  start_dir: '',
  dataset_name: '',
  dataset_id: '',
  delete_policy: 'sync',
  enabled: true,
})

const saving = ref(false)
const testing = ref(false)
const testedSignature = ref('')

const dingtalkSources = ref<KnowledgeSource[]>([])
const workspaceLoading = ref(false)
const docLibraries = ref<DocumentLibrary[]>([])
const docLibraryLoading = ref(false)
const docLibraryError = ref('')
const treeData = ref<TreeNode[]>([])
const treeLoading = ref(false)
const filterText = ref('')
const selectedNodeId = ref('')
const treeRef = ref<any>(null)
const currentDingtalkSource = ref<KnowledgeSource | null>(null)

function onDatasetChange(datasetId: string) {
  form.dataset_name = docLibraries.value.find((item) => String(item.id) === datasetId)?.name || ''
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
    form.dataset_name = source?.dataset_name || ''
    form.dataset_id = source?.dataset_id || ''
    form.delete_policy = source?.delete_policy || 'sync'
    form.enabled = source?.enabled ?? true
    testedSignature.value = ''
    selectedNodeId.value = ''
    filterText.value = ''
    currentDingtalkSource.value = null
    treeData.value = []
    await Promise.all([loadDingtalkSources(), loadDocumentLibraries()])
    if (!form.dataset_id) {
      const matches = docLibraries.value.filter((item) => item.name === form.dataset_name)
      if (matches.length === 1) form.dataset_id = String(matches[0].id)
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

async function loadDocumentLibraries() {
  docLibraryLoading.value = true
  docLibraryError.value = ''
  try {
    docLibraries.value = (await listDocumentLibraries()).filter((item) => item.enabled)
  } catch (error: any) {
    docLibraries.value = []
    docLibraryError.value = error?.response?.data?.detail || error?.message || '加载目标文档库失败'
  } finally {
    docLibraryLoading.value = false
  }
}

function goRegisterSource() {
  router.push('/knowledge-sources')
  emit('update:visible', false)
}

function goCreateLibrary() {
  router.push('/apply/knowledge-libraries')
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
  if (!form.dataset_id) { ElMessage.error('请选择目标文档库'); return false }
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
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
        <el-form-item label="目标文档库" required>
          <div style="display:flex;gap:8px;width:100%">
            <el-select v-model="form.dataset_id" filterable clearable @change="onDatasetChange" placeholder="选择目标文档库" :loading="docLibraryLoading" style="flex:1">
              <el-option v-for="item in docLibraries" :key="item.id" :label="item.name" :value="String(item.id)">
                <span>{{ item.name }}</span>
                <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">{{ item.document_count }} 篇</span>
              </el-option>
            </el-select>
          </div>
          <div v-if="docLibraries.length === 0 && !docLibraryLoading" style="font-size: 12px; color: var(--el-color-warning); margin-top: 4px">
            暂无可用文档库，请先到<a style="color: var(--el-color-primary); cursor: pointer" @click="goCreateLibrary">知识库</a>创建。
          </div>
          <div v-else style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px">钉钉目录将同步到该文档库，仅列出已启用的文档库。</div>
        </el-form-item>
        <el-form-item label="删除策略">
          <el-select v-model="form.delete_policy" style="width: 100%">
            <el-option label="同步删除（源删除则删目标文档）" value="sync" />
            <el-option label="保留（仅清理状态）" value="keep" />
          </el-select>
        </el-form-item>
      </div>
      <el-form-item label="立即启用">
        <el-switch v-model="form.enabled" :active-text="form.enabled ? '已启用' : '已停用'" aria-label="启用同步任务" />
        <div style="font-size:12px;color:var(--el-text-color-secondary);margin-top:4px;width:100%">
          启用后，钉钉知识库内容变化时自动同步到目标文档库；也可在列表中手动触发立即同步。
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :loading="testing" @click="test">测试连接</el-button>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
