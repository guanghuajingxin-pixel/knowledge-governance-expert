<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { fmtTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const app = useAppStore()
const auth = useAuthStore()

const title = computed(() => (route.meta.title as string) || '工作台')
const nextRun = computed(() => {
  const jobs = app.jobs.filter((j) => j.enabled && j.next_run_at)
  if (!jobs.length) return '下次同步：待配置定时任务'
  const t = jobs.map((j) => new Date(j.next_run_at! + (j.next_run_at!.endsWith('Z') ? '' : 'Z'))).sort((a, b) => a.getTime() - b.getTime())[0]
  return `下次同步：${fmtTime(t.toISOString())}`
})
const nav = [
  { page: 'dashboard', label: '工作台', dot: 'ok' },
  { page: 'sources', label: '同步源管理', dot: 'ok' },
  { page: 'jobs', label: '定时任务', dot: 'ok' },
  { page: 'monitor', label: '运行监控', dot: 'err' },
  { page: 'logs', label: '运行日志', dot: 'ok' },
  { page: 'settings', label: '设置', dot: 'off' },
]
function logout() {
  auth.logout()
  router.push('/login')
}
onMounted(() => { app.refreshAll().catch(() => {}) })
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand"><div class="badge">知</div>知识同步后台</div>
      <nav class="nav">
        <router-link v-for="n in nav" :key="n.page" :to="'/' + n.page" class="nav-item" :class="{ active: route.name === n.page }">
          <span class="dot" :class="n.dot"></span>{{ n.label }}
        </router-link>
      </nav>
      <div class="foot">v0.1.0 · 单服务一体化部署</div>
    </aside>
    <div class="main">
      <header class="topbar">
        <div class="title">{{ title }}</div>
        <div class="right">
          <span>{{ nextRun }}</span>
          <div class="user"><div class="avatar">管</div>知识管理员</div>
          <button class="el-button el-button--default is-text" @click="logout">退出</button>
        </div>
      </header>
      <div class="content">
        <router-view />
      </div>
    </div>
  </div>
</template>
