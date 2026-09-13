<script setup lang="ts">
import { computed, getCurrentInstance, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listPipelineVariables, importPipelineSchema } from '@/api/sync'
import type { PipelineVariable } from '@/types/sync'

const props = defineProps<{ datasetId?: string | null; modelValue: Record<string, any>; disabled?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: Record<string, any>): void }>()
const variables = ref<PipelineVariable[]>([])
const loading = ref(false)
const error = ref('')
const mode = ref('')
const configured = ref(false)
const schemaSource = ref('')
const jsonValue = ref('{}')
const jsonError = ref('')
const fileInput = ref<HTMLInputElement>()
const fieldPrefix = `pipeline-${getCurrentInstance()?.uid}`
let generation = 0
const labels: Record<string, string> = {
  parent_mode: '父分段模式', parent_dilmiter: '父分段分隔符', parent_delimiter: '父分段分隔符',
  parent_length: '父分段最大长度', maximum_parent_length: '父分段最大长度',
  child_delimiter: '子分段分隔符', child_length: '子分段最大长度', maximum_child_length: '子分段最大长度',
  clean_1: '合并连续空白字符', clean_2: '删除网址和邮箱',
}
const title = (v: PipelineVariable) => labels[v.variable.toLowerCase()] || v.label
const options: Record<string, string> = { paragraph: '按段落划分', full_doc: '整篇作为父分段' }
const visible = computed(() => !!props.datasetId && mode.value !== 'general')

function applySchema(data: any) {
  mode.value = data.runtime_mode || 'rag_pipeline'
  variables.value = data.variables || []
  configured.value = data.configured
  schemaSource.value = data.schema_source || ''
  const values = { ...props.modelValue }
  for (const v of variables.value) {
    if (values[v.variable] === undefined && v.default_value !== null && v.default_value !== undefined) {
      values[v.variable] = v.default_value
    }
  }
  emit('update:modelValue', values)
}

async function load() {
  const current = ++generation
  variables.value = []
  error.value = ''
  mode.value = ''
  configured.value = false
  jsonError.value = ''
  if (!props.datasetId) { loading.value = false; return }
  loading.value = true
  try {
    const result = await listPipelineVariables(props.datasetId)
    if (current === generation) applySchema(result)
  } catch (e: any) {
    if (current === generation) error.value = e?.response?.data?.detail || e?.message || '读取流水线参数失败'
  } finally {
    if (current === generation) loading.value = false
  }
}
watch(() => props.datasetId, load, { immediate: true })
watch(() => props.modelValue, (value) => { if (!jsonError.value) jsonValue.value = JSON.stringify(value, null, 2) }, { immediate: true, deep: true })
function update(key: string, value: unknown) { emit('update:modelValue', { ...props.modelValue, [key]: value }) }
function changeJson(value: string) {
  jsonValue.value = value
  try {
    const parsed = JSON.parse(value)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
    jsonError.value = ''
    emit('update:modelValue', parsed)
  } catch { jsonError.value = '请填写合法的 JSON 对象' }
}
function validate(): boolean {
  if (!props.datasetId || mode.value === 'general') return true
  const missing = variables.value.filter((v) => v.required && (props.modelValue[v.variable] == null || String(props.modelValue[v.variable]).trim() === ''))
  const message = loading.value ? '参数加载中，请稍候' : error.value || jsonError.value || (missing.length ? `请填写：${missing.map(title).join('、')}` : '')
  if (message) { ElMessage.warning(message); return false }
  return true
}
async function importFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file || !props.datasetId) return
  const datasetId = props.datasetId
  const current = ++generation
  loading.value = true
  try {
    const result = await importPipelineSchema(datasetId, file)
    if (current !== generation) return
    error.value = ''
    applySchema(result)
    ElMessage.success('参数表单已导入，Dify 流水线本身未修改')
  } catch (e: any) {
    if (current === generation) error.value = e?.response?.data?.detail || '导入失败'
  } finally {
    if (current === generation) loading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}
defineExpose({ validate })
</script>

<template>
  <div v-if="visible" class="pipeline-inputs" v-loading="loading">
    <div class="heading"><strong>流水线解析参数</strong><div>
      <el-button link :disabled="disabled || loading" @click="load">重新读取</el-button>
      <el-button :disabled="disabled || loading" @click="fileInput?.click()">导入 .pipeline 配置</el-button>
      <input ref="fileInput" type="file" accept=".pipeline,.yaml,.yml" hidden @change="importFile" />
    </div></div>
    <p class="hint">只影响 Dify 的解析与分段，传输的原文件保持不变。默认值来自{{ schemaSource === 'imported' ? '导入的配置文件' : '已发布流水线' }}。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-for="v in variables" :key="v.variable" class="field">
      <label :for="`${fieldPrefix}-${v.variable}`"><span v-if="v.required" class="required">*</span>{{ title(v) }}<small>{{ v.variable }}</small></label>
      <div class="control">
        <el-select v-if="v.type === 'select'" :id="`${fieldPrefix}-${v.variable}`" :model-value="modelValue[v.variable]" :disabled="disabled" @update:model-value="update(v.variable, $event)">
          <el-option v-for="option in v.options" :key="option" :value="option" :label="options[option] || option" />
        </el-select>
        <el-input-number v-else-if="v.type === 'number'" :id="`${fieldPrefix}-${v.variable}`" :model-value="modelValue[v.variable]" :disabled="disabled" controls-position="right" @update:model-value="update(v.variable, $event)" />
        <el-switch v-else-if="v.type === 'checkbox'" :id="`${fieldPrefix}-${v.variable}`" :aria-label="title(v)" :model-value="modelValue[v.variable] ?? false" :disabled="disabled" :active-text="modelValue[v.variable] ? '已开启' : '已关闭'" @update:model-value="update(v.variable, $event)" />
        <el-input v-else :id="`${fieldPrefix}-${v.variable}`" :model-value="modelValue[v.variable]" :disabled="disabled" :type="v.type === 'paragraph' ? 'textarea' : 'text'" @update:model-value="update(v.variable, $event)" />
        <span v-if="v.unit" class="hint">{{ v.unit }}</span>
        <el-tooltip v-if="v.tooltips" :content="v.tooltips" placement="top"><span class="hint" tabindex="0">说明</span></el-tooltip>
      </div>
    </div>
    <template v-if="!variables.length && !loading && !error">
      <p v-if="configured" class="hint">此文件分支没有需要填写的参数。</p>
      <template v-else>
        <p class="hint">暂未获取参数定义。可导入此知识库导出的 .pipeline 文件生成表单，或填写参数 JSON。</p>
        <el-input :model-value="jsonValue" :disabled="disabled" type="textarea" :rows="4" aria-label="流水线参数 JSON" @input="changeJson" />
        <p v-if="jsonError" class="required">{{ jsonError }}</p>
      </template>
    </template>
  </div>
</template>
<style scoped>
.pipeline-inputs { width: 100%; box-sizing: border-box; padding: 16px; margin: 12px 0; border: 1px solid var(--el-border-color); border-radius: 6px; }
.heading, .control { display: flex; align-items: center; gap: 12px; }
.heading { justify-content: space-between; flex-wrap: wrap; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; }
.field { display: grid; grid-template-columns: minmax(140px, 1fr) minmax(210px, 1.5fr); align-items: center; gap: 14px; margin-top: 14px; }
.field label { font-size: 13px; overflow-wrap: anywhere; }
.field small { display: block; color: var(--el-text-color-secondary); font-size: 11px; }
.control { min-width: 0; }
.control :is(.el-input, .el-input-number, .el-select) { flex: 1; min-width: 0; width: 100%; }
.required { color: var(--el-color-danger); }
@media (max-width: 600px) { .field { grid-template-columns: 1fr; gap: 6px; } }
</style>
