<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { deleteJob, runJob, toggleJob } from '@/api/jobs'
import { errMsg } from '@/api/http'
import { cronDesc } from '@/utils/cron'
import { fmtTime } from '@/utils/format'
import type { Job } from '@/types'
import StatusPill from '@/components/StatusPill.vue'
import JobFormDialog from '@/components/JobFormDialog.vue'

const app = useAppStore()
const formVisible = ref(false)
const editingJob = ref<Job | null>(null)

function openAdd() { editingJob.value = null; formVisible.value = true }
function openEdit(j: Job) { editingJob.value = j; formVisible.value = true }
async function onSaved() { await app.refreshJobs(); await app.refreshDashboard() }
async function toggle(j: Job) {
  try { await toggleJob(j.id); ElMessage.success(`已${j.enabled ? '停用' : '启用'}「${j.name}」`); await app.refreshJobs() }
  catch (e) { ElMessage.error(errMsg(e)) }
}
async function run(j: Job) {
  try { await runJob(j.id); ElMessage.success('任务已提交') } catch (e) { ElMessage.error(errMsg(e)) }
}
async function remove(j: Job) {
  try {
    await ElMessageBox.confirm(`确定删除定时任务「${j.name}」？`, '删除定时任务', { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' })
    await deleteJob(j.id); ElMessage.success('已删除'); await app.refreshJobs()
  } catch (e) { if (e !== 'cancel') ElMessage.error(errMsg(e)) }
}
onMounted(() => { app.refreshSources(); app.refreshJobs() })
</script>

<template>
  <div>
    <div class="page-head">
      <div><h2>定时任务</h2><div class="desc">配置同步执行时间：常用预设或自定义 cron 表达式</div></div>
      <el-button type="primary" @click="openAdd">+ 新增定时任务</el-button>
    </div>
    <div class="card">
      <table class="table">
        <thead><tr><th>任务名称</th><th>关联同步源</th><th>执行时间</th><th>可读描述</th><th>下次执行</th><th>状态</th><th>上次结果</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="j in app.jobs" :key="j.id">
            <td><b>{{ j.name }}</b></td>
            <td>{{ j.source_id === null ? '全部同步源' : app.sourceName(j.source_id) }}</td>
            <td style="font-family:ui-monospace,monospace;font-size:12px">{{ j.cron }}</td>
            <td>{{ j.description || cronDesc(j.cron) }}</td>
            <td>{{ fmtTime(j.next_run_at) }}</td>
            <td><StatusPill :status="j.enabled ? 'enabled' : 'disabled'" /></td>
            <td style="font-size:12px">{{ j.last_run_at ? fmtTime(j.last_run_at) : '—' }}</td>
            <td><div class="row-actions">
              <el-button size="small" @click="toggle(j)">{{ j.enabled ? '停用' : '启用' }}</el-button>
              <el-button size="small" @click="openEdit(j)">编辑</el-button>
              <el-button size="small" @click="run(j)">立即执行</el-button>
              <el-button size="small" type="danger" plain @click="remove(j)">删除</el-button>
            </div></td>
          </tr>
          <tr v-if="!app.jobs.length"><td colspan="8" class="empty">暂无定时任务，点击右上角新增</td></tr>
        </tbody>
      </table>
    </div>

    <JobFormDialog v-model:visible="formVisible" :job="editingJob" :sources="app.sources" @saved="onSaved" />
  </div>
</template>
