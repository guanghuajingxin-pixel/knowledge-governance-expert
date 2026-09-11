<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { retryFailure, retryAllFailures } from '@/api/runs'
import { errMsg } from '@/api/http'
import { fmtTime } from '@/utils/format'
import type { Run } from '@/types'
import StatusPill from '@/components/StatusPill.vue'

const app = useAppStore()
const pending = computed(() => app.failures.filter((f) => f.error))
const sources = computed(() => app.sources)

function sourceName(id: number) { return app.sourceName(id) }
function dur(r: Run) {
  if (!r.finished_at) return '运行中…'
  const s = new Date(r.started_at + (r.started_at.endsWith('Z') ? '' : 'Z')).getTime()
  const e = new Date(r.finished_at + (r.finished_at.endsWith('Z') ? '' : 'Z')).getTime()
  const sec = Math.max(0, Math.round((e - s) / 1000))
  if (sec < 60) return `${sec} 秒`
  const m = Math.floor(sec / 60); return `${m} 分 ${sec % 60} 秒`
}
function skippedOf(r: Run) { return Math.max(0, r.total - r.created_count - r.updated_count - r.deleted_count - r.failed_count) }
function statusOf(s: { enabled: boolean }) { return s.enabled ? 'ok' : 'off' }

async function retryOne(id: number) {
  try { await retryFailure(id); ElMessage.success('正在重试该失败项'); await app.refreshAll() }
  catch (e) { ElMessage.error(errMsg(e)) }
}
async function retryAll() {
  if (!pending.value.length) { ElMessage.warning('没有待重试的失败项'); return }
  try { await retryAllFailures(); ElMessage.success(`正在重试 ${pending.value.length} 个失败项`); await app.refreshAll() }
  catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(() => { app.refreshAll() })
</script>

<template>
  <div>
    <div class="page-head"><div><h2>运行监控</h2><div class="desc">运行看板、同步历史与失败清单</div></div></div>

    <div class="sect-title">失败清单（待处理）</div>
    <div class="card" style="margin-bottom:16px">
      <table class="table">
        <thead><tr><th>时间</th><th>同步源</th><th>文档</th><th>错误原因</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="f in pending" :key="f.id">
            <td style="font-size:12px">{{ fmtTime(f.created_at) }}</td>
            <td>{{ sourceName(f.source_id) }}</td>
            <td>{{ f.name || f.node_id || '—' }}</td>
            <td style="font-size:12px;color:var(--text-2)">{{ f.error }}</td>
            <td><StatusPill status="err" /></td>
            <td><el-button size="small" type="primary" @click="retryOne(f.id)">重试</el-button></td>
          </tr>
          <tr v-if="!pending.length"><td colspan="6" class="empty">暂无待处理失败，全部同步正常</td></tr>
        </tbody>
      </table>
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px"><el-button @click="retryAll">全部重试</el-button></div>
    </div>

    <div class="sect-title">运行看板</div>
    <div v-if="!sources.length" class="empty">暂无同步源</div>
    <div v-for="s in sources" :key="s.id" class="src-card">
      <div class="l">
        <div class="name">{{ s.name }} <StatusPill :status="statusOf(s)" /></div>
        <div class="meta">上次运行 {{ app.sourceStatsMap[s.id]?.last_run ? fmtTime(app.sourceStatsMap[s.id]!.last_run!.started_at) : '—' }} · 下次执行 见定时任务</div>
      </div>
      <div class="r">
        <div class="stat-line">
          <span class="up">新增 <b>{{ app.sourceStatsMap[s.id]?.last_run?.created_count ?? 0 }}</b></span>
          <span>更新 <b>{{ app.sourceStatsMap[s.id]?.last_run?.updated_count ?? 0 }}</b></span>
          <span>删除 <b>{{ app.sourceStatsMap[s.id]?.last_run?.deleted_count ?? 0 }}</b></span>
          <span class="fail">失败 <b>{{ app.sourceStatsMap[s.id]?.last_run?.failed_count ?? 0 }}</b></span>
        </div>
      </div>
    </div>

    <div class="sect-title" style="margin-top:20px">同步历史</div>
    <div class="card">
      <table class="table">
        <thead><tr><th>开始时间</th><th>触发方式</th><th>同步源</th><th>耗时</th><th>新增</th><th>更新</th><th>删除</th><th>跳过</th><th>失败</th><th>结果</th></tr></thead>
        <tbody>
          <tr v-for="r in app.runs" :key="r.id">
            <td style="font-size:12px">{{ fmtTime(r.started_at) }}</td>
            <td><StatusPill :status="r.trigger === 'manual' ? 'warn' : 'off'" />{{ r.trigger === 'manual' ? '手动' : '定时' }}</td>
            <td>{{ sourceName(r.source_id) }}</td>
            <td style="font-size:12px">{{ dur(r) }}</td>
            <td>{{ r.created_count }}</td><td>{{ r.updated_count }}</td><td>{{ r.deleted_count }}</td><td>{{ skippedOf(r) }}</td>
            <td style="color:var(--danger)">{{ r.failed_count }}</td>
            <td><StatusPill :status="r.status" /></td>
          </tr>
          <tr v-if="!app.runs.length"><td colspan="10" class="empty">暂无同步历史</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
