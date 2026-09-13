<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { syncSource } from '@/api/sources'
import { errMsg } from '@/api/http'
import { fmtTime } from '@/utils/format'
import StatusPill from '@/components/StatusPill.vue'

const router = useRouter()
const app = useAppStore()

const dashboard = computed(() => app.dashboard)
const pendingFailures = computed(() => app.failures.filter((f) => f.error))
const sevenDayRuns = computed(() => {
  const now = Date.now()
  return app.runs.filter((r) => now - new Date(r.started_at + (r.started_at.endsWith('Z') ? '' : 'Z')).getTime() < 7 * 86400000)
})
const sevenDayFailed = computed(() => sevenDayRuns.value.filter((r) => r.failed_count > 0).length)

function statusOf(s: { enabled: boolean }) { return s.enabled ? 'ok' : 'off' }
function statsOf(id: number) {
  const st = app.sourceStatsMap[id]
  const r = st?.last_run
  return r || { created_count: 0, updated_count: 0, deleted_count: 0, failed_count: 0 }
}
async function runAll() {
  const enabled = app.sources.filter((s) => s.enabled)
  if (!enabled.length) { ElMessage.warning('没有启用中的同步源'); return }
  ElMessage.success(`已触发全部启用中的同步源（${enabled.length} 个）`)
  for (const s of enabled) {
    try { await syncSource(s.id) } catch (e) { ElMessage.error(`${s.name}: ${errMsg(e)}`) }
  }
}
async function runOne(id: number) {
  try { await syncSource(id); ElMessage.success('同步任务已启动') } catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(() => { app.refreshAll().catch(() => {}) })
</script>

<template>
  <div>
    <div class="page-head">
      <div><h2>工作台</h2><div class="desc">各同步源运行状态与最近同步情况</div></div>
      <div style="display:flex;gap:10px">
        <el-button @click="router.push('/sources')">+ 新增同步任务</el-button>
        <el-button type="primary" @click="runAll">立即同步全部</el-button>
      </div>
    </div>

    <div class="stat-cards">
      <div class="stat-card"><div class="k">同步源总数</div><div class="v">{{ dashboard?.source_count ?? 0 }}</div><div class="foot">启用 {{ app.sources.filter(s => s.enabled).length }} · 停用 {{ app.sources.filter(s => !s.enabled).length }}</div></div>
      <div class="stat-card"><div class="k">文档累计入库</div><div class="v">{{ dashboard?.doc_count ?? 0 }}</div><div class="foot">Dify 文档映射</div></div>
      <div class="stat-card"><div class="k">最近 7 天同步</div><div class="v">{{ sevenDayRuns.length }}<small>次</small></div><div class="foot">全部成功 {{ sevenDayRuns.length - sevenDayFailed }} · 有失败 {{ sevenDayFailed }}</div></div>
      <div class="stat-card"><div class="k">待处理失败</div><div class="v" style="color:var(--danger)">{{ pendingFailures.length }}</div><div class="foot">点击前往运行监控处理</div></div>
    </div>

    <div class="card">
      <div class="sect-title">同步源概览</div>
      <div v-if="!app.sources.length" class="empty">暂无同步源，点击右上角新增</div>
      <div v-for="s in app.sources" :key="s.id" class="src-card">
        <div class="l">
          <div class="name">{{ s.name }} <StatusPill :status="statusOf(s)" /></div>
          <div class="meta">
            钉钉：{{ app.workspaceName(s.workspace_id) }} / {{ s.start_dir || '根目录' }}<br>
            Dify 知识库：{{ s.dify_dataset_name || s.start_dir || '—' }}<br>
            文档 {{ app.sourceStatsMap[s.id]?.doc_count ?? '—' }} 篇 · 上次同步 {{ app.sourceStatsMap[s.id]?.last_run ? fmtTime(app.sourceStatsMap[s.id]!.last_run!.started_at) : (s.enabled ? '—' : '（停用）') }}
          </div>
        </div>
        <div class="r">
          <div class="stat-line">
            <span class="up">新增 <b>{{ statsOf(s.id).created_count }}</b></span>
            <span>更新 <b>{{ statsOf(s.id).updated_count }}</b></span>
            <span>删除 <b>{{ statsOf(s.id).deleted_count }}</b></span>
            <span class="fail">失败 <b>{{ statsOf(s.id).failed_count }}</b></span>
          </div>
          <div style="margin-top:12px"><el-button size="small" @click="runOne(s.id)">立即同步</el-button></div>
        </div>
      </div>
    </div>
  </div>
</template>
