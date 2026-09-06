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
  group: string
}

const allMenuItems = computed<MenuItem[]>(() =>
  router
    .getRoutes()
    .filter((r) => r.meta?.title && !r.meta?.hidden && r.name)
    .map((r) => ({
      path: r.path,
      title: r.meta!.title as string,
      icon: r.meta!.icon as string,
      group: (r.meta!.group as string) || 'feature',
    })),
)

// 功能区：feature 组
const featureMenuItems = computed(() =>
  allMenuItems.value.filter((item) => item.group === 'feature'),
)

// 平台配置：config + admin 组（带 roles 的路由仅对应角色可见）
const configMenuItems = computed(() =>
  allMenuItems.value.filter((item) => {
    if (item.group !== 'config' && item.group !== 'admin') return false
    const r = router.getRoutes().find((rr) => rr.path === item.path)
    const roles = r?.meta?.roles as string[] | undefined
    if (roles) return !!userRole.value && roles.includes(userRole.value)
    return true
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

// 「关于我」产品介绍页：public/about.html，纯静态、不依赖登录态
const aboutUrl = `${import.meta.env.BASE_URL}about.html`
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
    <div class="logo" @click="router.push('/chat')">
      <div class="logo-icon">
        <el-icon :size="22" color="#fff"><Icons.Stamp /></el-icon>
      </div>
      <span v-show="!appStore.sidebarCollapsed" class="logo-text">知识治理专家</span>
    </div>

    <nav class="menu-container">
      <!-- 功能区 -->
      <div class="menu-group-label" v-show="!appStore.sidebarCollapsed">功能区</div>
      <div class="menu-group">
        <div
          v-for="item in featureMenuItems"
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

      <!-- 平台配置 -->
      <template v-if="configMenuItems.length > 0">
        <div class="menu-divider" />
        <div class="menu-group-label" v-show="!appStore.sidebarCollapsed">平台配置</div>
        <div class="menu-group">
          <div
            v-for="item in configMenuItems"
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

    <!-- 左下角：关于我（新浏览器页签打开产品介绍） -->
    <div class="sidebar-footer">
      <a class="menu-item about-item" :href="aboutUrl" target="_blank" rel="noopener" title="关于我">
        <span class="menu-icon about-icon">
          <el-icon :size="16"><Icons.InfoFilled /></el-icon>
        </span>
        <span v-show="!appStore.sidebarCollapsed" class="menu-title">关于我</span>
      </a>
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
  background: linear-gradient(135deg, #2b6bff, #6d28d9);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.logo-text {
  font-size: 15px;
  font-weight: 700;
  color: #1a1a2e;
  white-space: nowrap;
}

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
  background: #eef3ff;
}

.menu-item.active .menu-title {
  color: #2b6bff;
  font-weight: 600;
}

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
  background: #2b6bff;
  color: #fff;
}

.menu-title {
  font-size: 14px;
  color: #303133;
  transition: color 0.15s ease;
}

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

/* 左下角「关于我」 */
.sidebar-footer {
  flex-shrink: 0;
  padding: 8px;
  border-top: 1px solid #f0f0f0;
}

.about-icon {
  background: linear-gradient(135deg, #6157ff, #8b7bff);
  color: #fff;
}

.about-item {
  text-decoration: none;
}

.about-item .menu-title {
  color: #6157ff;
  font-weight: 600;
}
</style>
