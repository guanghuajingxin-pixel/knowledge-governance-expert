<script setup lang="ts">
/**
 * 知识中心 - 主页面
 * 钉钉知识：实时拉取钉钉开放平台知识库文件
 * 本地上传知识：平台内上传的文档
 */
import { ref, onMounted, watch } from 'vue'
import DingTalkKnowledgeTab from './components/DingTalkKnowledgeTab.vue'
import KnowledgeManageTab from './components/KnowledgeManageTab.vue'
import RecycleBinDialog from './components/RecycleBinDialog.vue'
import KnowledgeDetailDialog from './components/KnowledgeDetailDialog.vue'
import { fetchTaskStats } from '@/api/knowledge-center'
import type { TaskQueueStats } from '@/types/knowledge-center'

// 一级 Tab: 钉钉知识 / 本地上传知识
const scopeTab = ref<'DINGTALK' | 'LOCAL'>('DINGTALK')

// 任务队列（仅本地上传文档有处理状态）
const taskStats = ref<TaskQueueStats>({ total: 0, executing: 0, completed: 0, failed: 0 })

// 弹窗
const recycleVisible = ref(false)
const detailVisible = ref(false)
const detailDocId = ref<string>('')

async function loadTaskStats() {
  try {
    taskStats.value = await fetchTaskStats('DOCUMENT')
  } catch {
    // silently fail
  }
}

function handleRecycleOpen() {
  recycleVisible.value = true
}

function handleDetailOpen(docId: string) {
  detailDocId.value = docId
  detailVisible.value = true
}

watch(scopeTab, (v) => {
  if (v === 'LOCAL') {
    loadTaskStats()
  }
})

onMounted(() => {
  setInterval(() => {
    if (scopeTab.value === 'LOCAL') loadTaskStats()
  }, 30000)
})
</script>

<template>
  <div class="kc-page">
    <!-- 一级 Tab: 钉钉知识 / 本地上传知识 -->
    <el-tabs v-model="scopeTab" class="kc-scope-tabs">
      <el-tab-pane label="钉钉知识" name="DINGTALK" />
      <el-tab-pane label="本地上传知识" name="LOCAL" />
    </el-tabs>

    <!-- 钉钉知识：钉钉开放平台实时文件列表 -->
    <DingTalkKnowledgeTab v-if="scopeTab === 'DINGTALK'" />

    <!-- 本地上传知识：平台内上传的文档 -->
    <KnowledgeManageTab
      v-else
      scope-tab="DOCUMENT"
      :stats="taskStats"
      @recycle="handleRecycleOpen"
      @detail="handleDetailOpen"
    />

    <!-- 回收站弹窗（本地文档） -->
    <RecycleBinDialog v-model="recycleVisible" />

    <!-- 知识详情弹窗（本地文档） -->
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
</style>
