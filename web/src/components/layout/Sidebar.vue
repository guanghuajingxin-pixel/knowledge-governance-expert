<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useUserStore } from '@/stores/user'
import * as Icons from '@element-plus/icons-vue'
import { computed, ref } from 'vue'

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
  parent?: string
  roles?: string[]
}

interface MenuGroup {
  key: string
  parentTitle: string
  parentIcon: string
  children: MenuItem[]
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
      parent: r.meta!.parent as string | undefined,
      roles: r.meta!.roles as string[] | undefined,
    })),
)

// 过滤角色可见的菜单项
function filterByRole(items: MenuItem[]): MenuItem[] {
  return items.filter((item) => {
    const r = router.getRoutes().find((rr) => rr.path === item.path)
    const roles = r?.meta?.roles as string[] | undefined
    if (roles) return !!userRole.value && roles.includes(userRole.value)
    return true
  })
}

// 功能区：feature 组（含二级分组）
const featureMenuGroups = computed<MenuGroup[]>(() => {
  const items = filterByRole(allMenuItems.value.filter((i) => i.group === 'feature'))
  const groupMap = new Map<string, MenuGroup>()
  const parents: MenuItem[] = []
  const children: MenuItem[] = []

  for (const item of items) {
    if (item.parent) {
      children.push(item)
    } else {
      parents.push(item)
    }
  }

  // 父项先创建分组
  for (const p of parents) {
    groupMap.set(p.path, {
      key: p.path,
      parentTitle: p.title,
      parentIcon: p.icon,
      children: [],
    })
  }

  // 子项归入对应父分组
  for (const child of children) {
    if (child.parent && groupMap.has(child.parent)) {
      groupMap.get(child.parent)!.children.push(child)
    }
  }

  // 没有子项的分组降级为单独项（children 为空时仍以分组形式展示但不展开）
  return Array.from(groupMap.values())
})

// 所有独立功能菜单项（没有 parent 的）
const standaloneFeatureItems = computed(() => {
  const items = filterByRole(allMenuItems.value.filter((i) => i.group === 'feature' && !i.parent))
  return items.filter((item) => !featureMenuGroups.value.some((g) => g.key === item.path))
})

// 平台配置：config + admin 组
const configMenuItems = computed(() =>
  allMenuItems.value.filter((item) => {
    if (item.group !== 'config' && item.group !== 'admin') return false
    if (item.parent) return false // 配置区暂不支持二级分组
    const r = router.getRoutes().find((rr) => rr.path === item.path)
    const roles = r?.meta?.roles as string[] | undefined
    if (roles) return !!userRole.value && roles.includes(userRole.value)
    return true
  }),
)

// 父分组展开状态（默认展开）
const expandedGroups = ref<Record<string, boolean>>({})
function toggleGroup(key: string) {
  expandedGroups.value[key] = !expandedGroups.value[key]
}
function isGroupExpanded(key: string): boolean {
  if (expandedGroups.value[key] !== undefined) return expandedGroups.value[key]
  // 默认展开有子项的分组
  const group = featureMenuGroups.value.find((g) => g.key === key)
  return group ? group.children.length > 0 : false
}

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(path + '/')
}

function isGroupActive(groupKey: string): boolean {
  // 父分组自身路径活跃 或 任一子项活跃
  if (isActive(groupKey)) return true
  const group = featureMenuGroups.value.find((g) => g.key === groupKey)
  if (!group) return false
  return group.children.some((c) => isActive(c.path))
}

function navigate(path: string) {
  if (route.path !== path) {
    router.push(path)
  }
}

// 「关于我」产品介绍页
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
        <!-- 二级分组项 -->
        <template v-for="group in featureMenuGroups" :key="group.key">
          <!-- 有子项的分组 -->
          <div
            v-if="group.children.length > 0"
            class="menu-group-wrapper"
          >
            <div
              class="menu-item menu-item--parent"
              :class="{ active: isGroupActive(group.key) }"
              @click="navigate(group.key)"
              @contextmenu.prevent
            >
              <span class="menu-icon">
                <el-icon :size="16">
                  <component :is="(Icons as Record<string, any>)[group.parentIcon]" />
                </el-icon>
              </span>
              <span v-show="!appStore.sidebarCollapsed" class="menu-title">{{ group.parentTitle }}</span>
            </div>
            <!-- 展开箭头（点击切换子项显示） -->
            <el-icon
              v-show="!appStore.sidebarCollapsed"
              class="menu-expand"
              :class="{ expanded: isGroupExpanded(group.key) }"
              @click.stop="toggleGroup(group.key)"
            >
              <Icons.ArrowDown />
            </el-icon>
            <!-- 子项列表 -->
            <transition name="submenu">
              <div v-show="isGroupExpanded(group.key) && !appStore.sidebarCollapsed" class="submenu">
                <div
                  v-for="child in group.children"
                  :key="child.path"
                  class="menu-item menu-item--child"
                  :class="{ active: isActive(child.path) }"
                  :title="child.title"
                  @click="navigate(child.path)"
                >
                  <span class="menu-icon menu-icon--child">
                    <el-icon :size="14">
                      <component :is="(Icons as Record<string, any>)[child.icon]" />
                    </el-icon>
                  </span>
                  <span class="menu-title">{{ child.title }}</span>
                </div>
              </div>
            </transition>
          </div>

          <!-- 无子项的分组（降级为普通项） -->
          <div
            v-else
            class="menu-item"
            :class="{ active: isActive(group.key) }"
            :title="group.parentTitle"
            @click="navigate(group.key)"
          >
            <span class="menu-icon">
              <el-icon :size="16">
                <component :is="(Icons as Record<string, any>)[group.parentIcon]" />
              </el-icon>
            </span>
            <span v-show="!appStore.sidebarCollapsed" class="menu-title">{{ group.parentTitle }}</span>
          </div>
        </template>

        <!-- 独立功能菜单项 -->
        <div
          v-for="item in standaloneFeatureItems"
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

    <!-- 左下角：关于我 -->
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

.menu-group-wrapper {
  position: relative;
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

.menu-item--parent {
  padding-right: 30px; /* 给展开箭头留空间 */
}

.menu-item--child {
  padding-left: 36px;
  padding-top: 8px;
  padding-bottom: 8px;
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

.menu-icon--child {
  width: 24px;
  height: 24px;
  border-radius: 6px;
}

.menu-item:hover .menu-icon {
  transform: scale(1.08);
}

.menu-item.active .menu-icon {
  background: #2b6bff;
  color: #fff;
}

.menu-expand {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 12px;
  color: #999;
  cursor: pointer;
  padding: 4px;
  transition: transform 0.2s ease;
  z-index: 1;
}

.menu-expand.expanded {
  transform: translateY(-50%) rotate(180deg);
}

.menu-expand:hover {
  color: #2b6bff;
}

.submenu {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin-top: 2px;
}

/* 展开动画 */
.submenu-enter-active,
.submenu-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.submenu-enter-from,
.submenu-leave-to {
  opacity: 0;
  max-height: 0;
}
.submenu-enter-to,
.submenu-leave-from {
  opacity: 1;
  max-height: 300px;
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
