<script setup lang="ts">
import Sidebar from '@/components/layout/Sidebar.vue'
import TabBar from '@/components/layout/TabBar.vue'
</script>

<template>
  <div class="app-layout">
    <Sidebar />
    <div class="main-section">
      <TabBar />
      <div class="content-area">
        <router-view />
      </div>
    </div>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
}
.main-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.content-area {
  flex: 1;
  min-height: 0;
  /* 滚动权下放给页面内部（页签 pane / page-content），外框只负责按比例分配高度 */
  overflow: hidden;
  background: #f5f7fa;
}
</style>
