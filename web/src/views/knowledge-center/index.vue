<script setup lang="ts">
/**
 * 知识中心 - 主页面
 * 跨知识库统一知识管理视图
 */
import { ref, onMounted } from 'vue'
import CenterDirectoryTree from './components/CenterDirectoryTree.vue'
import KnowledgeManageTab from './components/KnowledgeManageTab.vue'
import RecycleBinDialog from './components/RecycleBinDialog.vue'
import KnowledgeDetailDialog from './components/KnowledgeDetailDialog.vue'
import TaskQueueBar from './components/TaskQueueBar.vue'
import { fetchDirectoryTree, fetchTaskStats } from '@/api/knowledge-center'
import type { KbTreeNode, TaskQueueStats } from '@/types/knowledge-center'

// 一级 Tab: 企业知识 / 团队知识
const scopeTab = ref<'DOCUMENT' | 'FAQ'>('DOCUMENT')

// 二级 Tab
const subTab = ref('knowledge-manage')
const subTabs = [
  { name: 'knowledge-manage', label: '知识管理' },
  { name: 'dir-permission', label: '目录权限' },
  { name: 'search-permission', label: '检索权限' },
  { name: 'dir-sort', label: '目录排序' },
]

// 目录树数据
const treeData = ref<KbTreeNode[]>([])
const treeLoading = ref(false)

// 任务队列
const taskStats = ref<TaskQueueStats>({ total: 0, executing: 0, completed: 0, failed: 0 })
const taskStatusFilter = ref<string>('')

// 选中目录
const selectedDirectory = ref<{ id: string; kb_id: string } | null>(null)

// 弹窗
const recycleVisible = ref(false)
const detailVisible = ref(false)
const detailDocId = ref<string>('')

async function loadTree() {
  treeLoading.value = true
  try {
    const raw = await fetchDirectoryTree(scopeTab.value)
    // 统一 name 字段：KB 根节点添加 name = kb_name
    treeData.value = raw.map((kb) => ({
      ...kb,
      name: kb.kb_name,
    }))
  } finally {
    treeLoading.value = false
  }
}

async function loadTaskStats() {
  try {
    taskStats.value = await fetchTaskStats(scopeTab.value)
  } catch {
    // silently fail
  }
}

function handleDirectorySelect(dir: { id: string; kb_id: string } | null) {
  selectedDirectory.value = dir
}

function handleScopeTabChange() {
  selectedDirectory.value = null
  taskStatusFilter.value = ''
  loadTree()
  loadTaskStats()
}

function handleSubTabChange() {
  selectedDirectory.value = null
  taskStatusFilter.value = ''
}

function handleRecycleOpen() {
  recycleVisible.value = true
}

function handleDetailOpen(docId: string) {
  detailDocId.value = docId
  detailVisible.value = true
}

function handleTaskFilter(status: string) {
  taskStatusFilter.value = taskStatusFilter.value === status ? '' : status
}

// 定期刷新任务队列
onMounted(() => {
  loadTree()
  loadTaskStats()
  setInterval(loadTaskStats, 30000)
})
</script>

<template>
  <div class="kc-page">
    <!-- 一级 Tab: 企业知识 / 团队知识 -->
    <el-tabs
      :model-value="scopeTab"
      class="kc-scope-tabs"
      @update:model-value="(v: any) => { scopeTab = v as 'DOCUMENT' | 'FAQ'; handleScopeTabChange() }"
    >
      <el-tab-pane label="企业知识" name="DOCUMENT" />
      <el-tab-pane label="团队知识" name="FAQ" />
    </el-tabs>

    <!-- 二级 Tab -->
    <el-tabs
      :model-value="subTab"
      class="kc-sub-tabs"
      @update:model-value="(v: any) => { subTab = v; handleSubTabChange() }"
    >
      <el-tab-pane
        v-for="tab in subTabs"
        :key="tab.name"
        :label="tab.label"
        :name="tab.name"
      />
    </el-tabs>

    <!-- 知识管理 Tab -->
    <div v-if="subTab === 'knowledge-manage'" class="kc-body">
      <div class="kc-split">
        <!-- 左侧目录树 -->
        <CenterDirectoryTree
          :data="treeData"
          :loading="treeLoading"
          @select="handleDirectorySelect"
          @recycle="handleRecycleOpen"
        />

        <!-- 右侧内容区 -->
        <KnowledgeManageTab
          :selected-directory="selectedDirectory"
          :scope-tab="scopeTab"
          :status-filter="taskStatusFilter"
          @recycle="handleRecycleOpen"
          @detail="handleDetailOpen"
        />
      </div>

      <!-- 任务队列状态栏 -->
      <TaskQueueBar
        :stats="taskStats"
        :active-filter="taskStatusFilter"
        @filter="handleTaskFilter"
      />
    </div>

    <!-- 占位 Tab -->
    <div v-else class="kc-placeholder">
      <el-empty :image-size="120" description="功能开发中，敬请期待" />
    </div>

    <!-- 回收站弹窗 -->
    <RecycleBinDialog v-model="recycleVisible" />

    <!-- 知识详情弹窗 -->
    <KnowledgeDetailDialog v-model="detailVisible" :doc-id="detailDocId" />
  </div>
</template>

<style scoped>
.kc-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 一级 Tab */
.kc-scope-tabs {
  flex-shrink: 0;
  background: #fff;
  padding: 0 20px;
  border-bottom: 1px solid #e8e8e8;
}

.kc-scope-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

/* 二级 Tab */
.kc-sub-tabs {
  flex-shrink: 0;
  background: #fff;
  padding: 0 20px;
}

.kc-sub-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

/* 主体 */
.kc-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 16px;
  gap: 12px;
}

.kc-split {
  flex: 1;
  display: flex;
  gap: 16px;
  overflow: hidden;
}

/* 占位 */
.kc-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
}
</style>
