<script setup lang="ts">
/**
 * 入库审核（原「知识打标」页）
 * 页面仅保留钉钉知识列表（列表内完成入库审核），无页内签
 */
import DingTalkKnowledgeTab from '@/views/knowledge-center/components/DingTalkKnowledgeTab.vue'
</script>

<template>
  <div class="kge-page review-page">
    <DingTalkKnowledgeTab />
  </div>
</template>

<style scoped>
/* kge-page 为 flex 纵向容器：让钉钉知识列表撑满剩余高度（kge-fill 约定） */
.review-page :deep(.dt-manage) {
  flex: 1;
  min-height: 0;
  height: auto;
}
</style>
