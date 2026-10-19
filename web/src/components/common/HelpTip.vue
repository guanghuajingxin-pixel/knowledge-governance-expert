<script setup lang="ts">
// 全站统一的「? 暗提示」组件：QuestionFilled 图标 + el-tooltip，hover/聚焦显示补充说明。
// 视觉基准沿用存量 tip-icon（placeholder 灰、14px、hover 主色），禁止各页面再自定义 ? 角标样式。
// badge 模式：绝对定位于目标对象右上角（不占行内主轴位置），使用方容器需 position: relative。
// 图标体系 lucide Phase 3 迁移时只需替换本文件图标导入（QuestionFilled → CircleHelp），全站点生效。
import { QuestionFilled } from '@element-plus/icons-vue'

withDefaults(defineProps<{
  /** 提示内容（简单文本；复杂内容用默认插槽） */
  content?: string
  /** tooltip 方位 */
  placement?: 'top' | 'bottom' | 'left' | 'right'
  /** 角标模式：绝对定位于容器右上角 */
  badge?: boolean
  /** 可访问名称（读屏无障碍） */
  label?: string
}>(), { content: '', placement: 'top', badge: false, label: '查看说明' })
</script>

<template>
  <el-tooltip :placement="placement" :show-after="200">
    <template #content>
      <div class="help-tip-content"><slot>{{ content }}</slot></div>
    </template>
    <el-icon :class="['help-tip', { 'is-badge': badge }]" :aria-label="label" role="note" tabindex="0">
      <QuestionFilled />
    </el-icon>
  </el-tooltip>
</template>

<style scoped>
.help-tip {
  color: var(--el-text-color-placeholder);
  font-size: 14px;
  cursor: help;
}

.help-tip:hover,
.help-tip:focus {
  color: var(--el-color-primary);
}

.help-tip.is-badge {
  position: absolute;
  top: -7px;
  right: -9px;
  z-index: 1;
}

.help-tip-content {
  max-width: 360px;
}
</style>
