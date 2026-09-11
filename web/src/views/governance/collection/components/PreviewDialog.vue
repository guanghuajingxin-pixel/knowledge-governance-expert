<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { syncSource, updatePreviewSettings } from '@/api/sync'
import type { PreviewItem } from '@/types/sync'

const props = defineProps<{ visible: boolean; name: string; sourceId: number; items: PreviewItem[] }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'done'): void }>()
const running = ref(false)

function badge(action: string) {
  if (action === '新增') return 'ok'
  if (action === '更新') return 'run'
  if (action === '删除') return 'warn'
  return 'off'
}
async function confirm() {
  running.value = true
  try {
    await updatePreviewSettings(props.sourceId, props.items.filter((item) => item.node_id).map((item) => ({
      node_id: item.node_id!, name: item.name || item.doc, category: item.category || 'DOCUMENT', enabled: item.enabled !== false,
    })))
    await syncSource(props.sourceId)
    ElMessage.success('同步任务已启动，可在运行监控中查看结果')
    emit('done')
    emit('update:visible', false)
  } finally { running.value = false }
}
</script>

<template>
  <el-dialog :model-value="visible" width="680px" :title="`预演（dry-run）结果 · ${name}`" @close="emit('update:visible', false)">
    <div style="font-size:13px;color:var(--el-text-color-secondary);margin-bottom:10px">只采集与比对，未写入 Dify。以下为本次将执行的变更清单：</div>
    <el-table :data="items" size="small" border>
      <el-table-column label="动作" width="90">
        <template #default="{ row }">
          <span class="preview-pill" :class="badge(row.action)">{{ row.action }}</span>
        </template>
      </el-table-column>
      <el-table-column label="文档" prop="doc" min-width="320" show-overflow-tooltip />
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <div v-if="row.node_id" class="preview-toggle">
            <el-switch v-model="row.enabled" :aria-label="`${row.doc}参与同步`" />
            <span>{{ row.enabled ? '参与同步' : '不参与' }}</span>
          </div>
          <span v-else style="font-size:12px;color:var(--el-text-color-secondary)">{{ row.note || '无需操作' }}</span>
        </template>
      </el-table-column>
      <template #empty><div style="padding:20px;color:var(--el-text-color-secondary)">无待处理变更</div></template>
    </el-table>
    <template #footer>
      <el-button @click="emit('update:visible', false)">关闭</el-button>
      <el-button type="primary" :loading="running" @click="confirm">确认并开始同步</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.preview-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}
.preview-pill {
  display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; line-height: 18px;
  border: 1px solid var(--el-border-color); color: var(--el-text-color-secondary); background: var(--el-fill-color-light);
}
.preview-pill.ok { color: #67c23a; border-color: #b3e19d; background: #f0f9eb; }
.preview-pill.run { color: #409eff; border-color: #a0cfff; background: #ecf5ff; }
.preview-pill.warn { color: #e6a23c; border-color: #f5dab1; background: #fdf6ec; }
.preview-pill.off { color: #909399; border-color: #d3d4d6; background: #f4f4f5; }
</style>
