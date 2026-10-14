<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, Download } from '@element-plus/icons-vue'
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
const uploading = ref(false)

function downloadTemplate() {
  const header = ['问题', '相似问', '答案', '关键词']
  const rows = [
    // 示例 1+2：同一问题拆成多行（问题与答案相同），导入时自动合并为一条问答，相似问聚合
    ['如何重置密码？', '忘记密码怎么办;密码找不回', '在登录页点击「忘记密码」，通过手机号验证后重置。', '密码'],
    ['如何重置密码？', '手机上能改密码吗', '在登录页点击「忘记密码」，通过手机号验证后重置。', '密码'],
    ['支持哪些文件格式？', '', '支持 PDF、Word、PPT、Excel、Markdown、TXT 等格式。', '文件格式'],
  ]
  const esc = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v)
  const csv = [header, ...rows].map(r => r.map(esc).join(',')).join('\r\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'FAQ批量导入模板.csv'
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const handleChange: UploadProps['onChange'] = async (file) => {
  if (file.status !== 'ready' || uploading.value) return
  uploading.value = true
  try {
    const res = await importFaqEntries(props.kbId, file.raw as File)
    const parts: string[] = [`成功导入 ${res.imported} 条问答`]
    if (res.failed > 0) parts.push(`${res.failed} 行格式无效已跳过`)
    if (res.index_failed > 0) parts.push(`${res.index_failed} 条向量索引失败，精准检索可用，恢复后可重新编辑触发重建`)
    ElMessage.success(parts.join('；'))
    emit('success')
    emit('update:modelValue', false)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '导入失败')
  } finally {
    uploading.value = false
    fileList.value = []
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
    width="520px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert type="info" :closable="false" style="margin-bottom: 16px;">
      <template #title>
        列顺序：问题、相似问、答案、关键词。相似问列内多个问句用分号或换行分隔；
        同一问题拆分多行（问题与答案相同）时自动合并为一条问答，相似问归属主问题。关键词用逗号分隔。
      </template>
    </el-alert>
    <el-upload
      v-model:file-list="fileList"
      drag
      :auto-upload="true"
      :show-file-list="true"
      :on-change="handleChange"
      accept=".csv,.xlsx"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">将文件拖到此处，或<em>点击上传</em></div>
      <template #tip>
        <div class="el-upload__tip">支持 .csv / .xlsx；旧版 .xls 请先另存为 .xlsx</div>
      </template>
    </el-upload>
    <template #footer>
      <el-button :icon="Download" @click="downloadTemplate">下载模板</el-button>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>
