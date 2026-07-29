<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const statusMap: Record<string, { type: 'success' | 'warning' | 'danger' | 'info'; text: string }> = {
  COMPLETED: { type: 'success', text: '已完成' },
  INDEXED: { type: 'success', text: '已索引' },
  PENDING: { type: 'info', text: '等待中' },
  QUEUED: { type: 'info', text: '排队中' },
  DRAFT: { type: 'info', text: '草稿' },
  PARSING: { type: 'warning', text: '解析中' },
  CHUNKING: { type: 'warning', text: '切片中' },
  EMBEDDING: { type: 'warning', text: '向量化中' },
  INDEXING: { type: 'warning', text: '索引中' },
  PROCESSING: { type: 'warning', text: '处理中' },
  FAILED: { type: 'danger', text: '失败' },
}

const config = computed(() => statusMap[props.status] || { type: 'info' as const, text: props.status })
</script>

<template>
  <el-tag :type="config.type" size="small" effect="light">{{ config.text }}</el-tag>
</template>
