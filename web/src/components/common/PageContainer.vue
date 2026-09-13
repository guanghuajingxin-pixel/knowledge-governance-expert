<script setup lang="ts">
defineProps<{
  title?: string
}>()
</script>

<template>
  <div class="page-container">
    <div v-if="title || $slots.actions" class="page-header">
      <div class="page-title">{{ title }}</div>
      <div class="page-actions">
        <slot name="actions" />
      </div>
    </div>
    <div class="page-content">
      <slot />
    </div>
  </div>
</template>

<style scoped>
/* 统一页面框架：撑满内容区剩余高度，页头固定、内容区内部滚动 */
.page-container {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 16px 20px 20px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-shrink: 0;
}
.page-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}
.page-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: #fff;
  border-radius: 4px;
  padding: 20px;
}
</style>
