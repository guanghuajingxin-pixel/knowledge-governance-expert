<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Plus, QuestionFilled, Close } from '@element-plus/icons-vue'
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
  similar_questions: [],
})
// 相似问逐行编辑：一行一条问句，空行提交时自动过滤
const similarRows = ref<string[]>([])

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
        keywords: [...(props.editingEntry.keywords || [])],
        similar_questions: [...(props.editingEntry.similar_questions || [])],
      })
    } else {
      Object.assign(form, { question: '', answer: '', keywords: [], similar_questions: [] })
    }
    similarRows.value = [...(form.similar_questions || [])]
  }
})

function addSimilarRow() { similarRows.value.push('') }
function removeSimilarRow(i: number) { similarRows.value.splice(i, 1) }

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      const similar = similarRows.value.map(s => s.trim()).filter(Boolean)
      const payload = { ...form, similar_questions: similar }
      if (props.editingEntry) {
        await updateFaqEntry(props.editingEntry.id, payload)
        ElMessage.success('更新成功')
      } else {
        await createFaqEntry(props.kbId, payload)
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
    width="600px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="问题" prop="question">
        <el-input v-model="form.question" type="textarea" :rows="2" maxlength="2000" show-word-limit placeholder="标准问句，作为这条问答的主问题" />
      </el-form-item>
      <el-form-item>
        <template #label>
          <span>相似问</span>
          <el-tooltip content="与主问题含义相同的问句变体，一行一条；检索命中任一相似问即返回本条答案" placement="top">
            <el-icon class="tip-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
        </template>
        <div class="similar-list">
          <div v-if="similarRows.length" class="similar-rows">
            <div v-for="(_, i) in similarRows" :key="i" class="similar-row">
              <el-input v-model="similarRows[i]" maxlength="2000" :placeholder="`相似问 ${i + 1}`" />
              <el-button link type="danger" :icon="Close" aria-label="删除相似问" @click="removeSimilarRow(i)" />
            </div>
          </div>
          <el-button link type="primary" :icon="Plus" @click="addSimilarRow">添加相似问</el-button>
        </div>
      </el-form-item>
      <el-form-item label="答案" prop="answer">
        <el-input v-model="form.answer" type="textarea" :rows="4" placeholder="这条问答的标准答案" />
      </el-form-item>
      <el-form-item>
        <template #label>
          <span>关键词</span>
          <el-tooltip content="补充检索用的关键词，输入后回车确认" placement="top">
            <el-icon class="tip-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
        </template>
        <el-select v-model="form.keywords" multiple filterable allow-create default-first-option style="width: 100%" placeholder="输入后回车" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.tip-icon { color: #c0c4cc; font-size: 14px; cursor: help; margin-left: 2px; vertical-align: -2px; }
.similar-list { width: 100%; }
.similar-rows { display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; }
.similar-row { display: flex; align-items: center; gap: 4px; }
.similar-row .el-input { flex: 1; }
</style>
