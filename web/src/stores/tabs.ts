import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export interface Tab {
  path: string
  title: string
}

// 关闭页签后无页签可停留时的回落页
const DEFAULT_PATH = '/chat'

// 页签持久化：刷新浏览器保留已打开的页签（sessionStorage 在浏览器标签关闭后自动清理）
const STORAGE_KEY = 'kge.tabs'

function loadTabs(): Tab[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((t) => t && typeof t.path === 'string' && t.path.length > 0)
      .map((t) => ({ path: t.path, title: typeof t.title === 'string' && t.title ? t.title : t.path }))
  } catch {
    return []
  }
}

function saveTabs(list: Tab[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(list))
  } catch {
    // 隐私模式或存储被禁用：静默降级为仅内存态
  }
}

export const useTabsStore = defineStore('tabs', () => {
  const route = useRoute()
  const router = useRouter()

  const tabs = ref<Tab[]>(loadTabs())

  function addTab(path: string, title: string) {
    const existing = tabs.value.find((t) => t.path === path)
    if (!existing) {
      tabs.value.push({ path, title })
    }
  }

  // 动态页签标题：详情页加载到实体名后更新（如文档分段页显示文件名）
  function updateTabTitle(path: string, title: string) {
    if (!title) return
    const tab = tabs.value.find((t) => t.path === path)
    if (tab) tab.title = title
  }

  function removeTab(path: string) {
    const tab = tabs.value.find((t) => t.path === path)
    if (!tab) return

    const idx = tabs.value.indexOf(tab)
    tabs.value.splice(idx, 1)

    // If closed tab was active, navigate to nearest sibling
    if (route.path === path || route.path.startsWith(path + '/') || route.path.startsWith(path + '?')) {
      const next = tabs.value[idx] || tabs.value[idx - 1]
      router.push(next ? next.path : DEFAULT_PATH)
    }
  }

  function closeOthers(path: string) {
    tabs.value = tabs.value.filter((t) => t.path === path)
  }

  function closeAll() {
    tabs.value = []
    router.push(DEFAULT_PATH)
  }

  // 持久化：tabs 任何变化都同步写回 sessionStorage
  watch(
    tabs,
    (list) => {
      saveTabs(list)
    },
    { deep: true },
  )

  // Auto-add tabs on route change
  watch(
    () => route.path,
    (path) => {
      if (path === '/' || path === '/login') return
      // Find matched route to get title
      const matched = route.matched.filter((r) => r.meta?.title)
      const title = matched.length > 0 ? (matched[matched.length - 1].meta!.title as string) : path
      addTab(path, title)
    },
    { immediate: true },
  )

  return { tabs, addTab, updateTabTitle, removeTab, closeOthers, closeAll }
})
