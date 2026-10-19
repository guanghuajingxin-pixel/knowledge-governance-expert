<script setup lang="ts">
import { ref, watch } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import IndexSettingsPanel from './IndexSettingsPanel.vue'
import type { IndexSettings } from './index-settings'

/** 索引设置弹窗：弹窗壳 + 共用分段组件 IndexSettingsPanel（与创建/编辑知识库共用同一份分段实现）。

props.value 传入当前设置（无则用默认值）；确定时 emit 校验后的完整设置与解析开关。
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
  (e: 'confirm', v: IndexSettings, reparse: boolean): void
}>()

// 解析开关：确定后是否按新设置重走文档解析（默认关闭——仅用解析缓存重新分段；
// 需要重新识别文档版面时用户手动打开）
const reparse = ref(false)
const panel = ref<InstanceType<typeof IndexSettingsPanel>>()

watch(() => props.modelValue, v => { if (v) reparse.value = false })

function confirm() {
  if (!panel.value?.validate()) return
  emit('confirm', panel.value.getSettings(), reparse.value)
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="title" width="min(680px, 94vw)" :close-on-click-modal="false"
             @update:model-value="v => emit('update:modelValue', v)">
    <div class="index-settings-dialog">
      <IndexSettingsPanel ref="panel" :scope="scope" :value="value" />
      <div class="reparse-row">
        <el-switch v-model="reparse" aria-label="保存后重新解析" />
        <span class="reparse-text">{{ reparse ? '保存后重新解析该文档' : '保存后仅重新分段（不重新解析）' }}</span>
        <el-tooltip content="开启=重走文档解析（版面重新识别）后按新设置分段；关闭=直接用已有解析结果按新设置重新分段，速度更快。两种方式都会清除已有分段及人工修改" placement="top">
          <el-icon class="tip-icon"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.index-settings-dialog { max-height: 62vh; overflow: auto; padding-right: 4px; }
.reparse-row { display: flex; align-items: center; gap: 8px; margin-top: 18px; padding-top: 14px; border-top: 1px solid #ebeef5; }
.reparse-text { font-size: 13px; color: #303133; }
.tip-icon { color: #c0c4cc; font-size: 14px; cursor: help; }
</style>
