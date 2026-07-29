<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { createKnowledgeBase, updateKnowledgeBase } from '@/api/knowledge-base'
import type { KnowledgeBase, KbCreateRequest, ChunkStrategy } from '@/types/knowledge-base'

const props = defineProps<{
  modelValue: boolean
  editingKb?: KnowledgeBase | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success'): void
}>()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive<KbCreateRequest>({
  name: '',
  description: '',
  kb_type: 'DOCUMENT',
  chunk_strategy: 'PARAGRAPH',
  chunk_size: 512,
  chunk_overlap: 150,
})

const strategies: { label: string; value: ChunkStrategy }[] = [
  { label: '固定大小切片', value: 'FIXED_SIZE' },
  { label: '段落切片', value: 'PARAGRAPH' },
  { label: 'Markdown 标题切片', value: 'MARKDOWN_HEADER' },
  { label: '句子切片', value: 'SENTENCE' },
]

const rules: FormRules = {
  name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }],
  kb_type: [{ required: true, message: '请选择类型', trigger: 'change' }],
}

watch(() => props.modelValue, (val) => {
  if (val) {
    if (props.editingKb) {
      Object.assign(form, {
        name: props.editingKb.name,
        description: props.editingKb.description,
        kb_type: props.editingKb.kb_type,
        chunk_strategy: props.editingKb.chunk_strategy,
        chunk_size: props.editingKb.chunk_size,
        chunk_overlap: props.editingKb.chunk_overlap,
      })
    } else {
      Object.assign(form, { name: '', description: '', kb_type: 'DOCUMENT', chunk_strategy: 'PARAGRAPH', chunk_size: 512, chunk_overlap: 150 })
    }
  }
})

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      if (props.editingKb) {
        await updateKnowledgeBase(props.editingKb.id, form)
        ElMessage.success('更新成功')
      } else {
        await createKnowledgeBase(form)
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
    :title="editingKb ? '编辑知识库' : '创建知识库'"
    width="520px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="请输入知识库名称" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="3" placeholder="可选" />
      </el-form-item>
      <el-form-item label="类型" prop="kb_type">
        <el-radio-group v-model="form.kb_type" :disabled="!!editingKb">
          <el-radio value="DOCUMENT">文档知识库</el-radio>
          <el-radio value="FAQ">FAQ 知识库</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="切片策略" v-if="form.kb_type === 'DOCUMENT'">
        <el-select v-model="form.chunk_strategy" style="width: 100%">
          <el-option v-for="s in strategies" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="切片大小" v-if="form.kb_type === 'DOCUMENT'">
        <el-input-number v-model="form.chunk_size" :min="50" :max="2000" :step="50" />
      </el-form-item>
      <el-form-item label="重叠大小" v-if="form.kb_type === 'DOCUMENT'">
        <el-input-number v-model="form.chunk_overlap" :min="0" :max="500" :step="10" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>
