<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import * as Icons from '@element-plus/icons-vue'
import { computed } from 'vue'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()

const menuItems = computed(() =>
  router.getRoutes().filter(
    (r) => r.meta?.title && !r.meta?.hidden && r.name,
  ),
)
</script>

<template>
  <div class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
    <div class="logo">
      <el-icon size="24" color="#fff"><Icons.Reading /></el-icon>
      <span v-show="!appStore.sidebarCollapsed" class="logo-text">知识库</span>
    </div>
    <el-menu
      :default-active="route.path"
      :collapse="appStore.sidebarCollapsed"
      background-color="#263445"
      text-color="#bfcbd9"
      active-text-color="#409EFF"
      router
    >
      <el-menu-item
        v-for="item in menuItems"
        :key="item.path"
        :index="item.path"
      >
        <el-icon><component :is="(Icons as Record<string, any>)[item.meta!.icon!]" /></el-icon>
        <template #title>{{ item.meta!.title }}</template>
      </el-menu-item>
    </el-menu>
  </div>
</template>

<style scoped>
.sidebar {
  width: 220px;
  background: #263445;
  transition: width 0.3s;
  overflow: hidden;
}
.sidebar.collapsed {
  width: 64px;
}
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
}
.logo-text {
  font-size: 18px;
  font-weight: 600;
  white-space: nowrap;
}
:deep(.el-menu) {
  border-right: none;
}
</style>
