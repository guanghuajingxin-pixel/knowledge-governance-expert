<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createSource, testSource, updateSource } from '@/api/sources'
import { buildTree, listNodes, listWorkspaces } from '@/api/dingtalk'
import { errMsg } from '@/api/http'
import type { Source, SourcePayload, TreeNode, Workspace } from '@/types'

const props = defineProps<{ visible: boolean; source: Source | null }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'saved'): void }>()

const form = reactive<SourcePayload>({
  name: '',
  workspace_id: '',
  root_node_id: '',
  start_dir: '',
  dify_dataset_name: '',
  delete_policy: 'sync',
  enabled: true,
})

const saving = ref(false)
const testing = ref(false)
const workspaces = ref<Workspace[]>([])
const workspaceLoading = ref(false)
const treeData = ref<TreeNode[]>([])
const treeMode = ref<'lazy' | 'full'>('lazy')
const searchLoading = ref(false)
const filterText = ref('')
const selectedNodeId = ref('')
const treeRef = ref<any>(null)
const currentWorkspace = ref<Workspace | null>(null)
const fullTreeCache = new Map<string, TreeNode[]>()
let searchTimer: number | undefined

const treeKey = computed(() => `${treeMode.value}:${form.workspace_id || 'empty'}`)

const isFileNode = (node: TreeNode) => node.category === 'DOCUMENT' || node.category === 'ALIDOC'

const treeProps = {
  label: 'name',
  children: 'children',
  disabled: (data: TreeNode) => isFileNode(data),
  isLeaf: (data: TreeNode) => isFileNode(data) || data.hasChildren === false,
}

function makeRoot(workspace: Workspace): TreeNode {
  return {
    nodeId: workspace.rootNodeId,
    name: workspace.name || '知识库根目录',
    category: 'OTHER',
    hasChildren: true,
    children: [],
  }
}

function makeFullRoot(workspace: Workspace, children: TreeNode[]): TreeNode {
  return {
    nodeId: workspace.rootNodeId,
    name: workspace.name || '知识库根目录',
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
    form.enabled = source?.enabled ?? true
    selectedNodeId.value = ''
    filterText.value = ''
    currentWorkspace.value = null
    treeMode.value = 'lazy'
    treeData.value = []
    await loadWorkspaces()
    if (form.workspace_id) {
      const workspace = workspaces.value.find((item) => item.workspaceId === form.workspace_id)
      currentWorkspace.value = workspace || null
      selectedNodeId.value = form.root_node_id || ''
    }
  },
)

async function loadWorkspaces() {
  workspaceLoading.value = true
  try {
    workspaces.value = await listWorkspaces()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    workspaceLoading.value = false
  }
}

function onWorkspaceChange(workspaceId: string) {
  form.workspace_id = workspaceId
  form.root_node_id = ''
  form.start_dir = ''
  selectedNodeId.value = ''
  filterText.value = ''
  currentWorkspace.value = null
  treeMode.value = 'lazy'
  treeData.value = []
  if (!workspaceId) return
  const workspace = workspaces.value.find((item) => item.workspaceId === workspaceId)
  if (workspace) {
    currentWorkspace.value = workspace
    expandRoot()
  }
}

function expandRoot(retries = 6) {
  const workspace = currentWorkspace.value
  if (!workspace) return
  const key = workspace.rootNodeId
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
  const workspace = currentWorkspace.value
  if (!workspace) {
    resolve([])
    return
  }
  if (node.level === 0) {
    resolve([makeRoot(workspace)])
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
    .catch((e) => {
      ElMessage.error(errMsg(e))
      resolve([])
    })
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
  const workspace = currentWorkspace.value
  if (!workspace) return
  let cached = fullTreeCache.get(workspace.workspaceId)
  if (!cached) {
    searchLoading.value = true
    try {
      const children = await buildTree(workspace.rootNodeId)
      cached = [makeFullRoot(workspace, children)]
      fullTreeCache.set(workspace.workspaceId, cached)
    } catch (e) {
      ElMessage.error(errMsg(e))
      return
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
  if (!form.dify_dataset_name.trim()) form.dify_dataset_name = label
}

function nodeMatches(node: TreeNode, keyword: string): boolean {
  if ((node.name || '').toLowerCase().includes(keyword)) return true
  return (node.children || []).some((child) => nodeMatches(child, keyword))
}

function filterNode(value: string, data: TreeNode): boolean {
  if (!value) return true
  return nodeMatches(data, value.toLowerCase())
}

function close() { emit('update:visible', false) }

async function save() {
  if (!form.name.trim()) { ElMessage.error('请填写同步源名称'); return }
  if (!form.workspace_id.trim() || !form.root_node_id.trim()) { ElMessage.error('请选择钉钉知识库与起始目录'); return }
  if (!form.dify_dataset_name.trim()) form.dify_dataset_name = (form.start_dir || '').trim() || form.name.trim()
  saving.value = true
  try {
    if (props.source) await updateSource(props.source.id, { ...form })
    else await createSource({ ...form })
    ElMessage.success(props.source ? '同步任务已更新' : '同步任务已创建')
    emit('saved')
    close()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { saving.value = false }
}

async function test() {
  if (!props.source) { ElMessage.warning('请先保存同步任务后再测试连接'); return }
  testing.value = true
  try {
    const r: any = await testSource(props.source.id)
    const ok = !!r.ok
    ElMessage({ type: ok ? 'success' : 'error', message: ok ? '连接成功：钉钉权限 OK · Dify 可达' : '连接失败，详见测试结果', duration: 5000 })
  } catch (e) { ElMessage.error(errMsg(e)) } finally { testing.value = false }
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
          <el-select v-model="form.workspace_id" filterable clearable placeholder="选择知识库" :loading="workspaceLoading" style="width: 100%" @change="onWorkspaceChange">
            <el-option v-for="item in workspaces" :key="item.workspaceId" :label="item.name" :value="item.workspaceId" />
          </el-select>
        </el-form-item>
      </div>
      <el-form-item label="起始目录" required>
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
      <el-form-item label="已选起始目录">
        <el-input v-model="form.start_dir" placeholder="选择目录后自动填充，也可修改用于展示" />
      </el-form-item>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
        <el-form-item label="Dify 知识库名称">
          <el-input v-model="form.dify_dataset_name" placeholder="默认 = 目录路径" />
        </el-form-item>
        <el-form-item label="删除策略">
          <el-select v-model="form.delete_policy" style="width: 100%">
            <el-option label="同步删除（源删除则删 Dify 文档）" value="sync" />
            <el-option label="保留（仅清理本地缓存状态）" value="keep" />
          </el-select>
        </el-form-item>
      </div>
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