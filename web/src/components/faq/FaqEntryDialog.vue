<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { createFaqEntry, updateFaqEntry } from '@/api/faq'
import type { FaqEntry, FaqEntryCreateRequest } from '@/types/faq'

const props = defineProps<{
  modelValue: boolean
  kbId: string
  editingEntry?: FaqEntry | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success'): void
}>()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive<FaqEntryCreateRequest>({
  question: '',
  answer: '',
  keywords: [],
  category_tags: [],
})

const rules: FormRules = {
  question: [{ required: true, message: '请输入问题', trigger: 'blur' }],
  answer: [{ required: true, message: '请输入答案', trigger: 'blur' }],
}

watch(() => props.modelValue, (val) => {
  if (val) {
    if (props.editingEntry) {
      Object.assign(form, {
        question: props.editingEntry.question,
        answer: props.editingEntry.answer,
        keywords: [...props.editingEntry.keywords],
        category_tags: [...props.editingEntry.category_tags],
      })
    } else {
      Object.assign(form, { question: '', answer: '', keywords: [], category_tags: [] })
    }
  }
})

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      if (props.editingEntry) {
        await updateFaqEntry(props.editingEntry.id, form)
        ElMessage.success('更新成功')
      } else {
        await createFaqEntry(props.kbId, form)
        ElMessage.success('创建成功')
      }
      emit('success')
      emit('update:modelValue', false)
    } finally {
      loading.value = false
    }
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="editingEntry ? '编辑问答' : '新增问答'"
    width="560px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="问题" prop="question">
        <el-input v-model="form.question" type="textarea" :rows="2" placeholder="请输入问题" />
      </el-form-item>
      <el-form-item label="答案" prop="answer">
        <el-input v-model="form.answer" type="textarea" :rows="4" placeholder="请输入答案" />
      </el-form-item>
      <el-form-item label="关键词">
        <el-select v-model="form.keywords" multiple filterable allow-create default-first-option style="width: 100%" placeholder="输入后回车">
        </el-select>
      </el-form-item>
      <el-form-item label="分类标签">
        <el-select v-model="form.category_tags" multiple filterable allow-create default-first-option style="width: 100%" placeholder="输入后回车">
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>
