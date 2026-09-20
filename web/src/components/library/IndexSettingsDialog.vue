<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ArrowDown, CopyDocument, Files, MagicStick, Operation, QuestionFilled } from '@element-plus/icons-vue'
import type { TypeRule } from '@/api/document-library'
import { METHODS, defaultSettings, type IndexSettings, type Strategy } from './index-settings'

/** 索引设置弹窗：文档级（单文档索引设置）与知识库级（整体设置）共用的公共组件。

props.value 传入当前设置（无则用默认值）；确定时 emit 校验后的完整设置。
scope=document 隐藏「按文件类型」策略（单文档只有一种类型，该策略无意义）。
*/
const props = withDefaults(defineProps<{
  modelValue: boolean
  title?: string
  scope?: 'document' | 'library'
  value?: IndexSettings | null
}>(), {title: '文档设置', scope: 'document', value: null})

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm', v: IndexSettings): void
}>()

const collapsed = ref(false)
const tab = ref<'system' | 'custom'>('system')
const form = reactive<IndexSettings>(defaultSettings())
const rules = ref<(TypeRule & {ext: string})[]>([])

watch(() => props.modelValue, v => {
  if (!v) return
  const s = props.value ? {...defaultSettings(), ...props.value, enhancements: {...props.value.enhancements}} : defaultSettings()
  Object.assign(form, s)
  rules.value = Object.entries(s.type_rules || {}).map(([ext, r]) => ({ext, ...r}))
  collapsed.value = false
  tab.value = 'system'
})

interface StrategyCard { key: Exclude<Strategy, 'by_file_type'>; title: string; desc: string }
const cards: StrategyCard[] = [
  {key: 'auto', title: '自动', desc: '自动设置分段与预处理规则'},
  {key: 'custom', title: '自定义', desc: '自定义文本分块模式，检索和召回的是相同的'},
  {key: 'parent_child', title: '父子分段', desc: '使用父子模式时，子块用于检索，父块用作上下文'}]

const enhancements = computed(() => [
  {key: 'include_filename', label: '加入文件名', tip: '检索与召回时在分段内容前附带文档名，便于模型溯源'},
  {key: 'auto_summary', label: '模型补充摘要', tip: '解析时由模型为每个分段生成内容摘要，提升语义检索命中'},
  {key: 'auto_questions', label: '模型补充用户问题', tip: '解析时由模型为每个分段生成候选问题，提升问答类查询命中率'},
  {key: 'image_caption', label: '模型补充图片描述', tip: '解析时由模型生成分段内图片的文字描述'}] as const)

function addRule() {
  rules.value.push({ext: '', strategy: 'auto', method: 'naive', chunk_token_num: 512, delimiter: '\n。！？；', children_delimiter: '\n'})
}
function confirm() {
  const type_rules: Record<string, TypeRule> = {}
  for (const {ext, ...rule} of rules.value) {
    if (ext.trim()) type_rules[ext.trim().toLowerCase().replace('.', '')] = rule
  }
  emit('confirm', {...form, enhancements: {...form.enhancements}, type_rules})
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="title" width="min(680px, 94vw)" :close-on-click-modal="false"
             @update:model-value="v => emit('update:modelValue', v)">
    <div class="index-settings">
      <div class="section-head" role="button" @click="collapsed = !collapsed">
        <span class="section-bar" />
        <span class="section-title">索引设置</span>
        <el-icon class="arrow" :class="{collapsed}"><ArrowDown /></el-icon>
      </div>
      <div v-show="!collapsed" class="section-body">
        <div class="field-label">分段策略</div>
        <el-radio-group v-model="tab" class="mode-tabs">
          <el-radio-button value="system">系统</el-radio-button>
          <el-radio-button value="custom">自定义</el-radio-button>
        </el-radio-group>

        <template v-if="tab === 'system'">
          <div
            v-for="card in cards" :key="card.key"
            class="strategy-card" :class="{active: form.strategy === card.key}"
            role="radio" :aria-checked="form.strategy === card.key" tabindex="0"
            @click="form.strategy = card.key"
            @keydown.enter.prevent="form.strategy = card.key">
            <span class="strategy-icon"><el-icon :size="20"><component :is="card.key === 'auto' ? MagicStick : card.key === 'custom' ? Operation : CopyDocument" /></el-icon></span>
            <span class="strategy-text">
              <span class="strategy-title">{{ card.title }}</span>
              <span class="strategy-desc">{{ card.desc }}</span>
            </span>
            <el-radio v-model="form.strategy" :value="card.key" class="strategy-radio" :aria-label="card.title">{{ '' }}</el-radio>
          </div>
          <div v-if="form.strategy === 'parent_child'" class="inline-param">
            <span class="param-label">子分段标识符</span>
            <el-input v-model="form.children_delimiter" placeholder="子分段分隔符，如换行符" />
          </div>
          <div v-if="scope === 'library'" class="strategy-card" :class="{active: form.strategy === 'by_file_type'}"
               role="radio" :aria-checked="form.strategy === 'by_file_type'" tabindex="0"
               @click="form.strategy = 'by_file_type'"
               @keydown.enter.prevent="form.strategy = 'by_file_type'">
            <span class="strategy-icon"><el-icon :size="20"><Files /></el-icon></span>
            <span class="strategy-text">
              <span class="strategy-title">按文件类型</span>
              <span class="strategy-desc">指定类型文件将通过该策略解析，其它类型使用【自动】策略</span>
            </span>
            <el-radio v-model="form.strategy" value="by_file_type" class="strategy-radio" aria-label="按文件类型">{{ '' }}</el-radio>
          </div>
          <div v-if="form.strategy === 'by_file_type'" class="type-rules">
            <div v-for="(rule, i) in rules" :key="i" class="type-rule">
              <el-input v-model="rule.ext" class="rule-ext" placeholder="扩展名 如 pdf" />
              <el-select v-model="rule.strategy" class="rule-strategy" @change="v => { if (v === 'parent_child') rule.method = 'naive' }">
                <el-option label="自动" value="auto" />
                <el-option label="自定义" value="custom" />
                <el-option label="父子分段" value="parent_child" />
              </el-select>
              <template v-if="rule.strategy === 'custom'">
                <el-select v-model="rule.method" class="rule-method">
                  <el-option v-for="m in METHODS" :key="m.value" :label="m.label" :value="m.value" />
                </el-select>
                <el-input-number v-model="rule.chunk_token_num" :min="1" :max="2048" class="rule-num" controls-position="right" />
              </template>
              <el-button link type="danger" @click="rules.splice(i, 1)">移除</el-button>
            </div>
            <el-button link type="primary" @click="addRule">+ 添加文件类型</el-button>
            <div class="rule-hint">未命中的文件类型使用【自动】策略</div>
          </div>
        </template>

        <template v-else>
          <div class="custom-form">
            <div class="custom-row">
              <span class="param-label">分段方式</span>
              <el-select v-model="form.method" :disabled="form.strategy === 'parent_child'" class="param-field">
                <el-option v-for="m in METHODS" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
            </div>
            <div class="custom-row">
              <span class="param-label">分段标识数（Token）<el-tooltip content="每个分段的目标长度，按 Token 数滚动窗口聚合" placement="top"><el-icon class="tip-icon"><QuestionFilled /></el-icon></el-tooltip></span>
              <el-input-number v-model="form.chunk_token_num" :min="1" :max="2048" class="param-field" controls-position="right" />
            </div>
            <div class="custom-row">
              <span class="param-label">分段标识符<el-tooltip content="用于切句的分隔字符集合，如换行与句号" placement="top"><el-icon class="tip-icon"><QuestionFilled /></el-icon></el-tooltip></span>
              <el-input v-model="form.delimiter" class="param-field" placeholder="如：\n。！？；" />
            </div>
            <div class="custom-row" v-if="form.strategy === 'parent_child'">
              <span class="param-label">子分段标识符</span>
              <el-input v-model="form.children_delimiter" class="param-field" />
            </div>
            <div class="custom-hint">当前策略：{{ form.strategy === 'parent_child' ? '父子分段' : '自定义' }}；切换到「系统」页签可选择预设策略</div>
          </div>
        </template>

        <div class="field-label enhance-label">检索内容增强</div>
        <div class="enhance-grid">
          <el-checkbox v-for="item in enhancements" :key="item.key" v-model="form.enhancements[item.key]">
            {{ item.label }}
            <el-tooltip :content="item.tip" placement="top"><el-icon class="tip-icon"><QuestionFilled /></el-icon></el-tooltip>
          </el-checkbox>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.index-settings { max-height: 62vh; overflow: auto; padding-right: 4px; }
.section-head { display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; padding: 2px 0 14px; border-bottom: 1px solid #ebeef5; margin-bottom: 16px; }
.section-bar { width: 4px; height: 16px; border-radius: 2px; background: var(--el-color-primary); }
.section-title { font-size: 15px; font-weight: 600; color: #303133; }
.arrow { margin-left: 4px; color: #909399; transition: transform .2s; }
.arrow.collapsed { transform: rotate(-90deg); }
.field-label { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 10px; }
.mode-tabs { margin-bottom: 14px; }
.strategy-card { display: flex; align-items: center; gap: 12px; border: 1px solid #dcdfe6; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px; cursor: pointer; transition: border-color .15s, background .15s; }
.strategy-card:hover { border-color: var(--el-color-primary-light-5); }
.strategy-card.active { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.strategy-icon { flex: none; width: 36px; height: 36px; border-radius: 8px; background: #e8f3ff; color: var(--el-color-primary); display: flex; align-items: center; justify-content: center; }
.strategy-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.strategy-title { font-size: 14px; font-weight: 600; color: #303133; }
.strategy-desc { font-size: 12px; color: #909399; }
.strategy-radio { flex: none; }
.strategy-radio :deep(.el-radio__label) { display: none; }
.inline-param { display: flex; align-items: center; gap: 12px; padding: 0 16px 12px 64px; margin-top: -4px; }
.param-label { flex: none; font-size: 13px; color: #606266; display: inline-flex; align-items: center; gap: 4px; }
.inline-param .el-input { max-width: 280px; }
.type-rules { border: 1px dashed #dcdfe6; border-radius: 8px; padding: 12px 14px; margin-bottom: 12px; }
.type-rule { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.rule-ext { width: 110px; }
.rule-strategy { width: 110px; }
.rule-method { width: 130px; }
.rule-num { width: 120px; }
.rule-hint { font-size: 12px; color: #909399; }
.custom-form { display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px; }
.custom-row { display: flex; align-items: center; gap: 12px; }
.param-field { max-width: 320px; }
.custom-hint { font-size: 12px; color: #909399; }
.enhance-label { margin-top: 18px; }
.enhance-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 24px; }
.enhance-grid :deep(.el-checkbox) { margin-right: 0; height: auto; }
.tip-icon { color: #c0c4cc; font-size: 14px; cursor: help; }
</style>
