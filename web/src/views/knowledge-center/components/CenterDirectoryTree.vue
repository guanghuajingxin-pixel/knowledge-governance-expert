<script setup lang="ts">
/**
 * 知识中心统一目录树
 * 跨知识库展现所有目录结构
 */
import { ref } from 'vue'
import { Folder, Delete, Search } from '@element-plus/icons-vue'
import type { KbTreeNode } from '@/types/knowledge-center'

defineProps<{
  data: KbTreeNode[]
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'select', dir: { id: string; kb_id: string } | null): void
  (e: 'recycle'): void
}>()

const searchText = ref('')
const filterText = ref('')

function filterNode(value: string, data: any) {
  if (!value) return true
  return String(data.name || '').toLowerCase().includes(value.toLowerCase())
}

function handleNodeClick(data: any) {
  if (data.kb_type) {
    // KB 根节点 — 选中整个知识库
    emit('select', { id: data.kb_id, kb_id: data.kb_id })
  } else {
    // 目录节点
    emit('select', { id: data.id, kb_id: data.kb_id })
  }
}

function handleRecycle() {
  emit('recycle')
}

function onSearchInput() {
  filterText.value = searchText.value
}
</script>

<template>
  <div class="kc-tree-panel">
    <!-- 搜索 -->
    <div class="tree-search">
      <el-input
        v-model="searchText"
        placeholder="输入目录名称检索"
        size="small"
        clearable
        :prefix-icon="Search"
        @input="onSearchInput"
      />
    </div>

    <!-- 树 -->
    <div class="tree-wrapper" v-loading="loading">
      <template v-if="data.length">
        <el-tree
          :data="data"
          :props="{ label: 'name', children: 'children' }"
          node-key="kb_id"
          :filter-node-method="filterNode"
          :filter-text="filterText"
          highlight-current
          accordion
          @node-click="handleNodeClick"
        >
          <template #default="{ data: node }">
            <span class="tree-node">
              <el-icon :size="14"><Folder /></el-icon>
              <span class="node-label">{{ node.name }}</span>
              <span v-if="node.document_count != null" class="node-count">
                {{ node.document_count > 99 ? '99+' : node.document_count }}
              </span>
            </span>
          </template>
        </el-tree>
      </template>
      <el-empty v-else description="暂无知识库" :image-size="60" />
    </div>

    <!-- 回收站入口 -->
    <div class="tree-recycle" @click="handleRecycle">
      <el-icon :size="16"><Delete /></el-icon>
      <span>回收站</span>
    </div>
  </div>
</template>

<style scoped>
.kc-tree-panel {
  width: 240px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tree-search {
  padding: 12px 12px 8px;
  flex-shrink: 0;
}

.tree-wrapper {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.node-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.node-count {
  font-size: 11px;
  color: #909399;
  background: #f0f0f0;
  border-radius: 10px;
  padding: 0 6px;
  min-width: 20px;
  text-align: center;
  flex-shrink: 0;
}

.tree-recycle {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  cursor: pointer;
  color: #606266;
  font-size: 14px;
  border-top: 1px solid #f0f0f0;
  flex-shrink: 0;
  transition: background 0.15s;
}

.tree-recycle:hover {
  background: #f5f7fa;
  color: #f56c6c;
}

:deep(.el-tree) {
  background: transparent;
}

:deep(.el-tree-node__content) {
  height: 32px;
  border-radius: 4px;
}

:deep(.el-tree-node__content:hover) {
  background: #f5f7fa;
}

:deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: #ecf5ff;
}
</style>
