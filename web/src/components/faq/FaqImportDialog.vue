<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import type { UploadProps } from 'element-plus'
import { importFaqEntries } from '@/api/faq'

const props = defineProps<{
  modelValue: boolean
  kbId: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success'): void
}>()

const fileList = ref<any[]>([])

const handleChange: UploadProps['onChange'] = async (file) => {
  if (file.status === 'ready') {
    try {
      const res = await importFaqEntries(props.kbId, file.raw as File)
      ElMessage.success(`导入完成：成功 ${res.imported} 条，失败 ${res.failed} 条`)
      emit('success')
      emit('update:modelValue', false)
    } catch {
      ElMessage.error('导入失败')
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
    title="批量导入问答"
    width="480px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert title="文件格式说明" type="info" :closable="false" style="margin-bottom: 16px;">
      CSV 或 Excel 文件，第一列「问题」，第二列「答案」，第三列可选「关键词」（逗号分隔）。
    </el-alert>
    <el-upload
      v-model:file-list="fileList"
      drag
      :auto-upload="true"
      :show-file-list="true"
      :on-change="handleChange"
      accept=".csv,.xlsx,.xls"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">将文件拖到此处，或<em>点击上传</em></div>
      <template #tip>
        <div class="el-upload__tip">支持 .csv / .xlsx / .xls</div>
      </template>
    </el-upload>
  </el-dialog>
</template>
