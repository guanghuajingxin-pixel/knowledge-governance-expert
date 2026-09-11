<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { listLogs } from '@/api/runs'
import { fmtTime } from '@/utils/format'
import type { Log } from '@/types'

const app = useAppStore()
const logs = ref<Log[]>([])
const src = ref('')
const lv = ref('')
const date = ref('')

const filtered = computed(() => {
  const now = Date.now()
  return logs.value.filter((l) => {
    if (lv.value && l.level.toLowerCase() !== lv.value) return false
    if (src.value && !l.message.includes(src.value)) return false
    if (date.value) {
      const t = new Date(l.created_at + (l.created_at.endsWith('Z') ? '' : 'Z')).getTime()
      const days = date.value === '今天' ? 1 : date.value === '最近 3 天' ? 3 : 7
      if (now - t > days * 86400000) return false
    }
    return true
  })
})
function lvClass(level: string) { const v = level.toLowerCase(); return v === 'error' ? 'error' : v === 'warn' ? 'warn' : 'info' }
async function load() {
  try { logs.value = await listLogs({ limit: 500 }) } catch (e) { logs.value = [] }
}
onMounted(load)
</script>

<template>
  <div>
    <div class="page-head"><div><h2>运行日志</h2><div class="desc">按时间、同步源与级别检索运行日志</div></div></div>
    <div class="filters">
      <el-select v-model="src" placeholder="全部同步源" clearable style="width:200px">
        <el-option v-for="s in app.sources" :key="s.id" :label="s.name" :value="s.name" />
      </el-select>
      <el-select v-model="lv" placeholder="全部级别" clearable style="width:160px">
        <el-option label="info" value="info" /><el-option label="warn" value="warn" /><el-option label="error" value="error" />
      </el-select>
      <el-select v-model="date" placeholder="全部时间" clearable style="width:160px">
        <el-option label="今天" value="今天" /><el-option label="最近 3 天" value="最近 3 天" /><el-option label="最近 7 天" value="最近 7 天" />
      </el-select>
    </div>
    <div class="card">
      <div v-if="!filtered.length" class="empty">无匹配日志</div>
      <div v-for="l in filtered" :key="l.id" class="log-line">
        <span class="t">{{ fmtTime(l.created_at) }}</span>
        <span class="lv" :class="lvClass(l.level)">{{ l.level.toLowerCase() }}</span>
        <span class="msg">{{ l.message }}</span>
      </div>
    </div>
  </div>
</template>
