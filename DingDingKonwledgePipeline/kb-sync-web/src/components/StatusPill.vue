<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()
const map: Record<string, [string, string]> = {
  ok: ['ok', '正常'],
  err: ['err', '有失败'],
  off: ['off', '停用'],
  run: ['run', '运行中'],
  success: ['ok', '成功'],
  partial: ['warn', '部分成功'],
  failed: ['err', '失败'],
  running: ['run', '运行中'],
  enabled: ['ok', '启用'],
  disabled: ['off', '停用'],
}
const info = computed<[string, string]>(() => map[props.status] || ['off', props.status])
</script>

<template>
  <span class="pill" :class="info[0]">{{ info[1] }}</span>
</template>
