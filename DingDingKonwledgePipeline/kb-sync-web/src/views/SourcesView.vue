<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { deleteSource, previewSource as fetchPreview, syncSource, updateSource } from '@/api/sources'
import { errMsg } from '@/api/http'
import { fmtTime } from '@/utils/format'
import type { PreviewItem, Source } from '@/types'
import StatusPill from '@/components/StatusPill.vue'
import SourceFormDialog from '@/components/SourceFormDialog.vue'
import PreviewDialog from '@/components/PreviewDialog.vue'

const app = useAppStore()
const formVisible = ref(false)
const editingSource = ref<Source | null>(null)
const previewVisible = ref(false)
const previewItems = ref<PreviewItem[]>([])
const previewSourceObj = ref<Source | null>(null)

function statusOf(s: Source) { return s.enabled ? 'ok' : 'off' }
function lastRunOf(id: number) { return app.sourceStatsMap[id]?.last_run }
function docsOf(id: number) { return app.sourceStatsMap[id]?.doc_count ?? '—' }

function openAdd() { editingSource.value = null; formVisible.value = true }
function openEdit(s: Source) { editingSource.value = s; formVisible.value = true }
async function onSaved() { await app.refreshAll() }

async function run(s: Source) {
  try { await syncSource(s.id); ElMessage.success(`「${s.name}」同步任务已启动`) } catch (e) { ElMessage.error(errMsg(e)) }
}
async function toggle(s: Source) {
  try {
    await updateSource(s.id, { enabled: !s.enabled })
    ElMessage.success(`已${s.enabled ? '停用' : '启用'}「${s.name}」`)
    await app.refreshAll()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function remove(s: Source) {
  try {
    await ElMessageBox.confirm(`确定删除同步任务「${s.name}」吗？其 Dify 知识库与已同步文档不会被删除，仅移除该同步配置。`, '删除同步任务', { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' })
    await deleteSource(s.id)
    ElMessage.success(`已删除同步任务「${s.name}」（仅移除配置，Dify 文档保留）`)
    await app.refreshAll()
  } catch (e) { if (e !== 'cancel') ElMessage.error(errMsg(e)) }
}
async function preview(s: Source) {
  try {
    previewSourceObj.value = s
    previewItems.value = await fetchPreview(s.id)
    previewVisible.value = true
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function onPreviewDone() { app.refreshAll() }
onMounted(() => { app.refreshSources(); app.refreshRuns(); app.refreshFailures(); app.refreshWorkspaces().catch(() => {}) })
</script>

<template>
  <div>
    <div class="page-head">
      <div><h2>同步任务管理</h2><div class="desc">配置钉钉知识库目录与目标 Dify 知识库的映射关系</div></div>
      <el-button type="primary" @click="openAdd">+ 新增同步任务</el-button>
    </div>
    <div class="card">
      <table class="table">
        <thead><tr><th>名称</th><th>钉钉知识库 / 起始目录</th><th>Dify 知识库</th><th>状态</th><th>上次同步</th><th>本次结果</th><th>文档数</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="s in app.sources" :key="s.id">
            <td><b>{{ s.name }}</b></td>
            <td>{{ app.workspaceName(s.workspace_id) }}<br><span style="color:var(--text-3);font-size:12px">{{ s.start_dir || '根目录' }}</span></td>
            <td style="font-size:12px">{{ s.dify_dataset_name || s.start_dir || '—' }}</td>
            <td><StatusPill :status="statusOf(s)" /></td>
            <td style="font-size:12px">{{ lastRunOf(s.id) ? fmtTime(lastRunOf(s.id)!.started_at) : (s.enabled ? '—' : '—') }}</td>
            <td style="font-size:12px">
              <template v-if="lastRunOf(s.id)">
                新 {{ lastRunOf(s.id)!.created_count }} / 更 {{ lastRunOf(s.id)!.updated_count }} / 删 {{ lastRunOf(s.id)!.deleted_count }} /
                <span :style="lastRunOf(s.id)!.failed_count ? 'color:var(--danger)' : 'color:var(--text-3)'">败 {{ lastRunOf(s.id)!.failed_count }}</span>
              </template>
              <template v-else>—</template>
            </td>
            <td>{{ docsOf(s.id) }}</td>
            <td><div class="row-actions">
              <el-button size="small" @click="preview(s)">预演</el-button>
              <el-button size="small" @click="run(s)">立即同步</el-button>
              <el-button size="small" @click="openEdit(s)">编辑</el-button>
              <el-button size="small" @click="toggle(s)">{{ s.enabled ? '停用' : '启用' }}</el-button>
              <el-button size="small" type="danger" plain @click="remove(s)">删除</el-button>
            </div></td>
          </tr>
        <tr v-if="!app.sources.length"><td colspan="8" class="empty">暂无同步任务，点击右上角新增同步任务</td></tr>
        </tbody>
      </table>
    </div>

    <SourceFormDialog v-model:visible="formVisible" :source="editingSource" @saved="onSaved" />
    <PreviewDialog v-model:visible="previewVisible" :source-id="previewSourceObj?.id || 0" :name="previewSourceObj?.name || ''" :items="previewItems" @done="onPreviewDone" />
  </div>
</template>
