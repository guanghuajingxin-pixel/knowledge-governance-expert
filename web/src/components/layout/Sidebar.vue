<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useUserStore } from '@/stores/user'
import * as Icons from '@element-plus/icons-vue'
import { computed } from 'vue'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const userStore = useUserStore()

const userRole = computed(() => userStore.userInfo?.role)

interface MenuItem {
  path: string
  title: string
  icon: string
}

const allMenuItems = computed<MenuItem[]>(() =>
  router
    .getRoutes()
    .filter((r) => r.meta?.title && !r.meta?.hidden && r.name)
    .map((r) => ({
      path: r.path,
      title: r.meta!.title as string,
      icon: r.meta!.icon as string,
      roles: r.meta?.roles as string[] | undefined,
    })),
)

const mainMenuItems = computed(() =>
  allMenuItems.value.filter((item) => {
    const route = router.getRoutes().find((r) => r.path === item.path)
    return !route?.meta?.roles && !route?.meta?.bottomSidebar
  }),
)

const adminMenuItems = computed(() =>
  allMenuItems.value.filter((item) => {
    const route = router.getRoutes().find((r) => r.path === item.path)
    const roles = route?.meta?.roles as string[] | undefined
    return roles && userRole.value && roles.includes(userRole.value)
  }),
)

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(path + '/')
}

function navigate(path: string) {
  if (route.path !== path) {
    router.push(path)
  }
}

function navigateToKC() {
  router.push({ name: 'KnowledgeCenter' })
}

function isKCActive(): boolean {
  return route.path === '/knowledge-center' || route.path.startsWith('/knowledge-center/')
}

const knowledgeCenterItem = computed(() =>
  router.getRoutes().find((r) => (r.meta as any)?.bottomSidebar),
)
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
    <div class="logo" @click="router.push('/dashboard')">
      <div class="logo-icon">
        <el-icon :size="22" color="#fff"><Icons.Reading /></el-icon>
      </div>
      <span v-show="!appStore.sidebarCollapsed" class="logo-text">知识库平台</span>
    </div>

    <nav class="menu-container">
      <!-- 功能菜单 -->
      <div class="menu-group">
        <div
          v-for="item in mainMenuItems"
          :key="item.path"
          class="menu-item"
          :class="{ active: isActive(item.path) }"
          :title="item.title"
          @click="navigate(item.path)"
        >
          <span class="menu-icon">
            <el-icon :size="16">
              <component :is="(Icons as Record<string, any>)[item.icon]" />
            </el-icon>
          </span>
          <span v-show="!appStore.sidebarCollapsed" class="menu-title">{{ item.title }}</span>
        </div>
      </div>

      <!-- 平台管理 -->
      <template v-if="adminMenuItems.length > 0">
        <div class="menu-divider" />
        <div
          v-show="!appStore.sidebarCollapsed"
          class="menu-group-label"
        >平台管理</div>
        <div class="menu-group">
          <div
            v-for="item in adminMenuItems"
            :key="item.path"
            class="menu-item"
            :class="{ active: isActive(item.path) }"
            :title="item.title"
            @click="navigate(item.path)"
          >
            <span class="menu-icon">
              <el-icon :size="16">
                <component :is="(Icons as Record<string, any>)[item.icon]" />
              </el-icon>
            </span>
            <span v-show="!appStore.sidebarCollapsed" class="menu-title">{{ item.title }}</span>
          </div>
        </div>
      </template>
    </nav>

    <!-- 知识中心（左下角固定入口） -->
    <div
      v-if="knowledgeCenterItem"
      class="kc-entry"
      :class="{ active: isKCActive() }"
      :title="(knowledgeCenterItem.meta as any)?.title || '知识中心'"
      @click="navigateToKC"
    >
      <span class="menu-icon">
        <el-icon :size="16"><Icons.Reading /></el-icon>
      </span>
      <span v-show="!appStore.sidebarCollapsed" class="menu-title">知识中心</span>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 220px;
  background: #fff;
  border-right: 1px solid #e8e8e8;
  display: flex;
  flex-direction: column;
  transition: width 0.3s ease;
  overflow: hidden;
  flex-shrink: 0;
}

.sidebar.collapsed {
  width: 64px;
}

/* Logo */
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  cursor: pointer;
  flex-shrink: 0;
}

.logo-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: linear-gradient(135deg, #409EFF, #7C5CFC);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.logo-text {
  font-size: 16px;
  font-weight: 700;
  color: #1a1a2e;
  white-space: nowrap;
}

/* Menu Container */
.menu-container {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.menu-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.menu-divider {
  height: 1px;
  background: #f0f0f0;
  margin: 12px 8px;
}

.menu-group-label {
  font-size: 11px;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 0 12px 6px;
  white-space: nowrap;
}

/* Menu Item */
.menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
  white-space: nowrap;
}

.menu-item:hover {
  background: #f5f7fa;
}

.menu-item.active {
  background: #ecf5ff;
}

.menu-item.active .menu-title {
  color: #409EFF;
  font-weight: 600;
}

/* Menu Icon */
.menu-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: #f0f0f0;
  color: #666;
  transition: background 0.15s ease, color 0.15s ease, transform 0.15s ease;
}

.menu-item:hover .menu-icon {
  transform: scale(1.08);
}

.menu-item.active .menu-icon {
  background: #409EFF;
  color: #fff;
}

/* Menu Title */
.menu-title {
  font-size: 14px;
  color: #303133;
  transition: color 0.15s ease;
}

/* Scrollbar */
.menu-container::-webkit-scrollbar {
  width: 4px;
}

.menu-container::-webkit-scrollbar-thumb {
  background: #d9d9d9;
  border-radius: 2px;
}

.menu-container::-webkit-scrollbar-track {
  background: transparent;
}

/* 知识中心底部入口 */
.kc-entry {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin: 4px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
  white-space: nowrap;
  flex-shrink: 0;
  border-top: 1px solid #f0f0f0;
}

.kc-entry:hover {
  background: #f5f7fa;
}

.kc-entry.active {
  background: #ecf5ff;
}

.kc-entry.active .menu-title {
  color: #409EFF;
  font-weight: 600;
}

.kc-entry:hover .menu-icon {
  transform: scale(1.08);
}

.kc-entry.active .menu-icon {
  background: #409EFF;
  color: #fff;
}
</style>
