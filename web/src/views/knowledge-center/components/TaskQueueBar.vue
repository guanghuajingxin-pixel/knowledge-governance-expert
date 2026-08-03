<script setup lang="ts">
/**
 * 任务队列状态栏
 * 固定在知识列表底部，展示处理任务统计
 */
import type { TaskQueueStats } from '@/types/knowledge-center'

const props = defineProps<{
  stats: TaskQueueStats
  activeFilter: string
}>()

const emit = defineEmits<{
  (e: 'filter', status: string): void
}>()

interface QueueItem {
  key: string
  label: string
  count: number
  statusFilter?: string
}

const items: QueueItem[] = [
  { key: 'total', label: '全部', count: 0 },
  { key: 'executing', label: '执行中', count: 0, statusFilter: 'executing' },
  { key: 'completed', label: '已完成', count: 0, statusFilter: 'completed' },
  { key: 'failed', label: '失败', count: 0, statusFilter: 'failed' },
]

function handleClick(item: QueueItem) {
  if (item.statusFilter) {
    emit('filter', item.statusFilter)
  } else {
    emit('filter', '')
  }
}

function isActive(item: QueueItem): boolean {
  if (item.key === 'total' && !props.activeFilter) return true
  return item.statusFilter === props.activeFilter
}
</script>

<template>
  <div class="task-queue-bar">
    <div
      v-for="item in items"
      :key="item.key"
      class="queue-item"
      :class="{ active: isActive(item) }"
      @click="handleClick(item)"
    >
      {{ item.label }}({{ stats[item.key as keyof TaskQueueStats] ?? 0 }})
    </div>
  </div>
</template>

<style scoped>
.task-queue-bar {
  display: flex;
  align-items: center;
  gap: 0;
  background: #fff;
  border-radius: 4px;
  padding: 0;
  flex-shrink: 0;
  overflow: hidden;
}

.queue-item {
  flex: 1;
  text-align: center;
  padding: 10px 0;
  font-size: 13px;
  color: #606266;
  cursor: pointer;
  transition: all 0.15s ease;
  border-right: 1px solid #f0f0f0;
  user-select: none;
}

.queue-item:last-child {
  border-right: none;
}

.queue-item:hover {
  background: #f5f7fa;
  color: #409EFF;
}

.queue-item.active {
  background: #ecf5ff;
  color: #409EFF;
  font-weight: 600;
}
</style>
