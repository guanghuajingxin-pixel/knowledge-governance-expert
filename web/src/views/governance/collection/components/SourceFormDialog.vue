<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { buildTree, createSource, listNodes, testSourceDraft, updateSource } from '@/api/sync'
import type { Source, SourcePayload, TreeNode } from '@/types/sync'
import { listKnowledgeSources } from '@/api/knowledge-center'
import type { KnowledgeSource } from '@/types/knowledge-center'
import { useRouter } from 'vue-router'

const router = useRouter()

const props = defineProps<{ visible: boolean; source: Source | null }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'saved'): void }>()

const form = reactive<SourcePayload>({
  name: '',
  workspace_id: '',
  root_node_id: '',
  start_dir: '',
  dify_dataset_name: '',
  delete_policy: 'sync',
  cron: '0 2 * * *',
  enabled: true,
})

const saving = ref(false)
const testing = ref(false)
const testedSignature = ref('')
const dingtalkSources = ref<KnowledgeSource[]>([])
const workspaceLoading = ref(false)
const difySources = ref<KnowledgeSource[]>([])
const difyDatasetLoading = ref(false)
const difyDatasetError = ref('')
const treeData = ref<TreeNode[]>([])
const treeMode = ref<'lazy' | 'full'>('lazy')
const searchLoading = ref(false)
const filterText = ref('')
const selectedNodeId = ref('')
const treeRef = ref<any>(null)
const currentDingtalkSource = ref<KnowledgeSource | null>(null)
const fullTreeCache = new Map<string, TreeNode[]>()
let searchTimer: number | undefined

const treeKey = computed(() => `${treeMode.value}:${form.workspace_id || 'empty'}`)

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

function makeRoot(source: KnowledgeSource): TreeNode {
  return {
    nodeId: getDingtalkRootNodeId(source),
    name: source.name || '知识库根目录',
    category: 'OTHER',
    hasChildren: true,
    children: [],
  }
}

function makeFullRoot(source: KnowledgeSource, children: TreeNode[]): TreeNode {
  return {
    nodeId: getDingtalkRootNodeId(source),
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
    form.dify_dataset_name = source?.dify_dataset_name || ''
    form.delete_policy = source?.delete_policy || 'sync'
    form.cron = source?.cron || '0 2 * * *'
    form.enabled = source?.enabled ?? true
    testedSignature.value = ''
    selectedNodeId.value = ''
    filterText.value = ''
    currentDingtalkSource.value = null
    treeMode.value = 'lazy'
    treeData.value = []
    await Promise.all([loadDingtalkSources(), loadDifySources()])
    if (form.workspace_id) {
      const ks = dingtalkSources.value.find((item) => item.external_id === form.workspace_id)
      currentDingtalkSource.value = ks || null
      selectedNodeId.value = form.root_node_id || ''
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
  try {
    difySources.value = await listKnowledgeSources({ source_type: 'dify_dataset', enabled_only: true })
  } catch (error: any) {
    difySources.value = []
    difyDatasetError.value = error?.response?.data?.detail || error?.message || '加载 Dify 知识库失败'
  } finally {
    difyDatasetLoading.value = false
  }
}

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
  treeMode.value = 'lazy'
  treeData.value = []
  if (!workspaceId) return
  const ks = dingtalkSources.value.find((item) => item.external_id === workspaceId)
  if (ks) {
    currentDingtalkSource.value = ks
    expandRoot()
  }
}

function expandRoot(retries = 6) {
  const ks = currentDingtalkSource.value
  if (!ks) return
  const key = getDingtalkRootNodeId(ks)
  const attempt = (retryLeft: number) => {
    const node = treeRef.value?.getNode(key)
    if (node) {
      node.expand()
      return
    }
    if (retryLeft > 0) {
      window.setTimeout(() => attempt(retryLeft - 1), 100)
    }
  }
  window.setTimeout(() => attempt(retries), 50)
}

function loadNode(node: any, resolve: (data: TreeNode[]) => void) {
  const ks = currentDingtalkSource.value
  if (!ks) {
    resolve([])
    return
  }
  if (node.level === 0) {
    resolve([makeRoot(ks)])
    return
  }
  listNodes(node.data.nodeId)
    .then((nodes) => resolve(nodes.map((n) => ({
      nodeId: n.nodeId,
      name: n.name,
      category: n.category,
      hasChildren: n.hasChildren,
      children: [],
    }))))
    .catch(() => resolve([]))
}

function onFilterTextChange() {
  const keyword = filterText.value.trim()
  if (searchTimer) window.clearTimeout(searchTimer)
  if (!keyword) {
    treeRef.value?.filter('')
    treeMode.value = 'lazy'
    treeData.value = []
    return
  }
  searchTimer = window.setTimeout(() => applySearch(keyword), 300)
}

async function applySearch(keyword: string) {
  const ks = currentDingtalkSource.value
  if (!ks) return
  let cached = fullTreeCache.get(ks.external_id)
  if (!cached) {
    searchLoading.value = true
    try {
      const children = await buildTree(getDingtalkRootNodeId(ks))
      cached = [makeFullRoot(ks, children)]
      fullTreeCache.set(ks.external_id, cached)
    } finally {
      searchLoading.value = false
    }
  }
  treeMode.value = 'full'
  treeData.value = cached
  await nextTick()
  treeRef.value?.filter(keyword)
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
  if (!form.root_node_id.trim()) {
    const ks = dingtalkSources.value.find((item) => item.external_id === form.workspace_id)
    if (!ks) { ElMessage.error('请选择目录'); return false }
    form.root_node_id = getDingtalkRootNodeId(ks)
    form.start_dir = ks.name
  }
  if (!form.dify_dataset_name.trim()) { ElMessage.error('请选择 Dify 知识库'); return false }
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
    ElMessage({ type: ok ? 'success' : 'error', message: ok ? '连接成功：钉钉权限 OK · Dify 可达' : '连接失败，详见测试结果', duration: 5000 })
  } catch {
    testedSignature.value = ''
  } finally { testing.value = false }
}
</script>

<template>
  <el-dialog :model-value="visible" width="720px" :title="source ? '编辑同步源' : '新增同步源'" @close="close">
    <el-form label-position="top">
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
        <el-form-item label="同步源名称" required>
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
      <el-form-item label="目录选择">
        <div style="width: 100%">
          <el-input v-model="filterText" clearable placeholder="输入关键字搜索目录（首次搜索会构建完整目录）" style="margin-bottom: 8px" @input="onFilterTextChange" @clear="onFilterTextChange" />
          <div v-loading="searchLoading" style="border: 1px solid var(--el-border-color); border-radius: 6px; max-height: 260px; overflow: auto; padding: 4px">
            <el-tree
              ref="treeRef"
              :key="treeKey"
              :data="treeData"
              node-key="nodeId"
              :props="treeProps"
              :lazy="treeMode === 'lazy'"
              :load="loadNode"
              :filter-node-method="filterNode"
              :expand-on-click-node="false"
              highlight-current
              :current-node-key="selectedNodeId"
              empty-text="请先选择知识库"
              @node-click="onNodeClick"
            />
          </div>
        </div>
      </el-form-item>
      <el-form-item label="已选目录" required>
        <el-input v-model="form.start_dir" placeholder="请选择目录（不选时默认同步整个知识库）" />
      </el-form-item>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
        <el-form-item label="Dify 知识库名称" required>
          <div style="display:flex;gap:8px;width:100%">
            <el-select v-model="form.dify_dataset_name" filterable clearable placeholder="选择已登记的 Dify 数据集" :loading="difyDatasetLoading" style="flex:1">
              <el-option v-for="item in difySources" :key="item.id" :label="item.name" :value="item.name">
                <span>{{ item.name }}</span>
                <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">{{ item.external_id }}</span>
              </el-option>
            </el-select>
          </div>
          <div v-if="difySources.length === 0 && !difyDatasetLoading" style="font-size: 12px; color: var(--el-color-warning); margin-top: 4px">
            暂无已登记的 Dify 数据集，请先到<a style="color: var(--el-color-primary); cursor: pointer" @click="goRegisterSource">知识源管理</a>登记。
          </div>
          <div v-else style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px">仅显示并使用已登记的 Dify 知识库。</div>
        </el-form-item>
        <el-form-item label="删除策略">
          <el-select v-model="form.delete_policy" style="width: 100%">
            <el-option label="同步删除（源删除则删 Dify 文档）" value="sync" />
            <el-option label="保留（仅清理状态）" value="keep" />
          </el-select>
        </el-form-item>
      </div>
      <el-form-item label="定时表达式 (cron)">
        <el-input v-model="form.cron" placeholder="如：0 2 * * *（每日凌晨 2 点）" />
        <div style="font-size:12px;color:var(--el-text-color-secondary);margin-top:4px">五段式：分 时 日 月 周。留空或错误将不参与定时。</div>
      </el-form-item>
      <el-form-item label="立即启用">
        <el-switch v-model="form.enabled" active-text="停用状态不会参与定时同步" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :loading="testing" @click="test">测试连接</el-button>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
