<template>
  <div class="kge-page">
    <el-tabs v-model="activeTab" class="operate-tabs">
      <el-tab-pane label="运营看板" name="dashboard">
        <Dashboard v-if="loaded.dashboard" />
      </el-tab-pane>
      <el-tab-pane label="问答明细" name="qa">
        <QaDetails v-if="loaded.qa" />
      </el-tab-pane>
      <el-tab-pane label="知识纠错" name="corrections">
        <Corrections v-if="loaded.corrections" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import Dashboard from './Dashboard.vue'
import QaDetails from './QaDetails.vue'
import Corrections from './Corrections.vue'

const activeTab = ref('dashboard')
// 懒加载：切到哪个页签才挂载哪个组件（看板遍历任务重，避免无谓请求）
const loaded = reactive({ dashboard: true, qa: false, corrections: false })

watch(activeTab, (name) => {
  if (name === 'qa') loaded.qa = true
  if (name === 'corrections') loaded.corrections = true
})
</script>

<style scoped>
.operate-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}
.operate-tabs :deep(.el-tabs__item) {
  font-size: 15px;
  font-weight: 600;
}
</style>
