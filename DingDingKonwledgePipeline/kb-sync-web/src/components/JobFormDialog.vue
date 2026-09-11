<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createJob, updateJob } from '@/api/jobs'
import { errMsg } from '@/api/http'
import { cronDesc, PRESET_DESC } from '@/utils/cron'
import type { Job, Source } from '@/types'

const props = defineProps<{ visible: boolean; job: Job | null; sources: Source[] }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'saved'): void }>()

const form = reactive({
  name: '',
  source_id: null as number | null,
  cron: '0 2 * * *',
  description: '',
  enabled: true,
})
const preset = ref('0 2 * * *')
const custom = ref(false)
const saving = ref(false)

const desc = computed(() => custom.value ? cronDesc(form.cron) : (PRESET_DESC[form.cron] || cronDesc(form.cron)))

watch(() => props.visible, (v) => {
  if (!v) return
  const j = props.job
  form.name = j?.name || ''
  form.source_id = j?.source_id ?? null
  form.cron = j?.cron || '0 2 * * *'
  form.description = j?.description || ''
  form.enabled = j?.enabled ?? true
  preset.value = ['0 2 * * *', '0 8 * * *', '0 9 * * 1', '0 */6 * * *'].includes(form.cron) ? form.cron : 'custom'
  custom.value = preset.value === 'custom'
})
function onPreset(v: string) {
  if (v === 'custom') { custom.value = true; return }
  custom.value = false
  form.cron = v
  form.description = PRESET_DESC[v]
}
function close() { emit('update:visible', false) }
async function save() {
  if (!form.name.trim()) { ElMessage.error('请填写任务名称'); return }

  saving.value = true
  try {
    const payload = { name: form.name, source_id: form.source_id, cron: form.cron, description: form.description || desc.value, enabled: form.enabled }
    if (props.job) await updateJob(props.job.id, payload)
    else await createJob(payload)
    ElMessage.success(props.job ? '定时任务已更新' : '定时任务已创建')
    emit('saved')
    close()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { saving.value = false }
}
</script>

<template>
  <el-dialog :model-value="visible" width="560px" :title="job ? '编辑定时任务' : '新增定时任务'" @close="close">
    <el-form label-position="top">
      <el-form-item label="任务名称" required><el-input v-model="form.name" placeholder="如：每日凌晨同步" /></el-form-item>
      <el-form-item label="关联同步源">
        <el-select v-model="form.source_id" style="width:100%" placeholder="请选择">
          <el-option label="全部同步源" :value="null" />
          <el-option v-for="s in sources" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="执行时间（常用预设）">
        <el-select v-model="preset" style="width:100%" @change="onPreset">
          <el-option label="每天凌晨 02:00" value="0 2 * * *" />
          <el-option label="每天 08:00" value="0 8 * * *" />
          <el-option label="每周一 09:00" value="0 9 * * 1" />
          <el-option label="每 6 小时" value="0 */6 * * *" />
          <el-option label="自定义 cron 表达式" value="custom" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="custom" label="自定义 cron 表达式">
        <el-input v-model="form.cron" placeholder="分 时 日 月 周，如：30 3 * * *" />
      </el-form-item>
      <el-form-item label="可读描述"><el-input :model-value="desc" disabled /></el-form-item>
      <el-form-item label="启用任务">
        <el-switch v-model="form.enabled" active-text="不启用则仅支持手动触发" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
