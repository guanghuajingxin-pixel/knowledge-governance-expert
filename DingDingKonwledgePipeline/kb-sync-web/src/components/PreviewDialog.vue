<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { syncSource } from '@/api/sources'
import { errMsg } from '@/api/http'
import type { PreviewItem } from '@/types'

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
    await syncSource(props.sourceId)
    ElMessage.success('已启动正式同步')
    emit('done')
    emit('update:visible', false)
  } catch (e) { ElMessage.error(errMsg(e)) } finally { running.value = false }
}
</script>

<template>
  <el-dialog :model-value="visible" width="680px" :title="`预演（dry-run）结果 · ${name}`" @close="emit('update:visible', false)">
    <div class="form-note">只采集与比对，未写入 Dify。以下为本次将执行的变更清单：</div>
    <table class="table">
      <thead><tr><th>动作</th><th>文档</th><th>说明</th></tr></thead>
      <tbody>
        <tr v-for="(it, i) in items" :key="i">
          <td><span class="pill" :class="badge(it.action)">{{ it.action }}</span></td>
          <td>{{ it.doc }}</td>
          <td style="font-size:12px;color:var(--text-2)">{{ it.note || '预演 · 未写入 Dify' }}</td>
        </tr>
        <tr v-if="!items.length"><td colspan="3" class="empty">无待处理变更</td></tr>
      </tbody>
    </table>
    <template #footer>
      <el-button @click="emit('update:visible', false)">关闭</el-button>
      <el-button type="primary" :loading="running" @click="confirm">确认并开始同步</el-button>
    </template>
  </el-dialog>
</template>
