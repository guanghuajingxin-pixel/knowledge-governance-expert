import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export interface Tab {
  path: string
  title: string
}

// 关闭页签后无页签可停留时的回落页
const DEFAULT_PATH = '/chat'

export const useTabsStore = defineStore('tabs', () => {
  const route = useRoute()
  const router = useRouter()

  const tabs = ref<Tab[]>([])

  function addTab(path: string, title: string) {
    const existing = tabs.value.find((t) => t.path === path)
    if (!existing) {
      tabs.value.push({ path, title })
    }
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

  return { tabs, addTab, removeTab, closeOthers, closeAll }
})
