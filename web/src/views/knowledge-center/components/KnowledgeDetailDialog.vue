<script setup lang="ts">
/**
 * 知识详情弹窗
 */
import { ref, watch } from 'vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { fetchDocumentDetail } from '@/api/knowledge-center'
import { formatDate, formatFileSize } from '@/utils/format'
import type { KnowledgeCenterDocument } from '@/types/knowledge-center'

const props = defineProps<{
  modelValue: boolean
  docId: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
}>()

const detail = ref<KnowledgeCenterDocument | null>(null)
const loading = ref(false)

async function loadDetail() {
  if (!props.docId) return
  loading.value = true
  try {
    detail.value = await fetchDocumentDetail(props.docId)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (val) => {
    if (val) loadDetail()
  },
)

watch(
  () => props.docId,
  () => {
    if (props.modelValue) loadDetail()
  },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="知识详情"
    width="600px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="知识标题" :span="2">
            {{ detail.original_filename }}
          </el-descriptions-item>
          <el-descriptions-item label="文件类型">
            {{ detail.file_type?.toUpperCase() || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="文件大小">
            {{ formatFileSize(detail.file_size) }}
          </el-descriptions-item>
          <el-descriptions-item label="来源知识库">
            {{ detail.kb_name || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="所属目录">
            {{ detail.directory_name || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <StatusTag :status="detail.status" />
          </el-descriptions-item>
          <el-descriptions-item label="切片数">
            {{ detail.chunk_count }}
          </el-descriptions-item>
          <el-descriptions-item label="上传时间">
            {{ formatDate(detail.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="更新时间">
            {{ formatDate(detail.updated_at) }}
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>
