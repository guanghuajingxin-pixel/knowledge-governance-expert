<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import type { UploadProps } from 'element-plus'
import { uploadDocument } from '@/api/document'

const props = defineProps<{
  modelValue: boolean
  kbId: string
  directoryId?: string | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success'): void
}>()

const fileList = ref<any[]>([])

const handleChange: UploadProps['onChange'] = async (file) => {
  if (file.status === 'ready') {
    try {
      await uploadDocument(file.raw as File, props.kbId, props.directoryId || undefined)
      ElMessage.success(`${file.name} 上传成功，正在后台处理`)
      emit('success')
    } catch {
      ElMessage.error(`${file.name} 上传失败`)
    }
  }
}

watch(() => props.modelValue, (val) => {
  if (!val) fileList.value = []
})
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="上传文档"
    width="480px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-upload
      v-model:file-list="fileList"
      drag
      :auto-upload="false"
      :show-file-list="true"
      :on-change="handleChange"
      accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.xls"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">将文件拖到此处，或<em>点击上传</em></div>
      <template #tip>
        <div class="el-upload__tip">支持 PDF / Word / Excel / Markdown / TXT / CSV（PDF/Word/Excel 需 MinerU 云解析，暂未启用）</div>
      </template>
    </el-upload>
  </el-dialog>
</template>
