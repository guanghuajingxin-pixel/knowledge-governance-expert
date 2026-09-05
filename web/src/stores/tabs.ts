import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export interface Tab {
  path: string
  title: string
  closable: boolean
}

const HOME_TAB: Tab = {
  path: '/dashboard',
  title: '工作台',
  closable: false,
}

export const useTabsStore = defineStore('tabs', () => {
  const route = useRoute()
  const router = useRouter()

  const tabs = ref<Tab[]>([{ ...HOME_TAB }])

  function addTab(path: string, title: string) {
    const existing = tabs.value.find((t) => t.path === path)
    if (!existing) {
      tabs.value.push({ path, title, closable: true })
    }
  }

  function removeTab(path: string) {
    const tab = tabs.value.find((t) => t.path === path)
    if (!tab || !tab.closable) return

    const idx = tabs.value.indexOf(tab)
    tabs.value.splice(idx, 1)

    // If closed tab was active, navigate to nearest sibling
    if (route.path === path || route.path.startsWith(path + '/') || route.path.startsWith(path + '?')) {
      const next = tabs.value[idx] || tabs.value[idx - 1]
      if (next) {
        router.push(next.path)
      }
    }
  }

  function closeOthers(path: string) {
    tabs.value = tabs.value.filter((t) => !t.closable || t.path === path)
  }

  function closeAll() {
    tabs.value = tabs.value.filter((t) => !t.closable)
    router.push(HOME_TAB.path)
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
