<script setup lang="ts">
import type { SearchResult } from '@/types/search'

defineProps<{
  modelValue: boolean
  result: SearchResult | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', val: boolean): void }>()

function openUrl(url: string) {
  window.open(url, '_blank')
}
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    title="检索结果溯源"
    size="420px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="result" class="trace-content">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="来源类型">
          <el-tag :type="result.source_type === 'FAQ' ? 'success' : 'primary'" size="small">
            {{ result.source_type === 'FAQ' ? 'FAQ 匹配' : '文档检索' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="内容">{{ result.text }}</el-descriptions-item>
        <el-descriptions-item label="文档标题" v-if="result.document_title">{{ result.document_title }}</el-descriptions-item>
        <el-descriptions-item label="所在页码" v-if="result.page_number">第 {{ result.page_number }} 页</el-descriptions-item>
        <el-descriptions-item label="目录路径">{{ result.directory_path || '-' }}</el-descriptions-item>
        <el-descriptions-item label="切片序号" v-if="result.total_chunks">{{ result.chunk_id.split('_').pop() }} / {{ result.total_chunks }}</el-descriptions-item>
        <el-descriptions-item label="相关度评分">{{ (result.score * 100).toFixed(1) }}%</el-descriptions-item>
        <el-descriptions-item label="内容 Hash">{{ result.content_hash }}</el-descriptions-item>
        <el-descriptions-item label="FAQ 答案" v-if="result.faq_answer">{{ result.faq_answer }}</el-descriptions-item>
      </el-descriptions>
      <div class="trace-actions" v-if="result.preview_url || result.source_path">
        <el-button v-if="result.preview_url" type="primary" @click="openUrl(result.preview_url)">
          在线预览原文
        </el-button>
        <el-button v-if="result.source_path" @click="openUrl(result.source_path)">
          下载原文件
        </el-button>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.trace-content { padding: 0; }
.trace-actions { margin-top: 16px; display: flex; gap: 8px; }
</style>
