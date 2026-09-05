<script setup lang="ts">
import Sidebar from '@/components/layout/Sidebar.vue'
import Header from '@/components/layout/Header.vue'
import TabBar from '@/components/layout/TabBar.vue'
</script>

<template>
  <div class="app-layout">
    <Sidebar />
    <div class="main-section">
      <Header />
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
  overflow-y: auto;
  background: #f5f7fa;
}
</style>
