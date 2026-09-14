<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

const router = useRouter()

// 问答日志
const logs = [
  { time: '10:21', app: '本插件·智能问答', query: 'JK-8669D 针距偏差？', kb: '产品手册', result: '已引用作答', type: 'success' },
  { time: '10:05', app: '千问办公', query: '大客户 VIP 折扣怎么算', kb: '路由 → 渠道政策', result: '无结果 → AI 判定缺口', type: 'danger' },
  { time: '09:47', app: '人类门户', query: 'CE 认证流程', kb: '制度标准', result: '仅外网资料', type: 'warning' },
  { time: '09:12', app: 'Dify·新员工导师', query: '试用期考核标准', kb: '制度标准', result: '已引用作答', type: 'success' },
]

function goSearch() {
  router.push('/search')
}
</script>

<template>
  <div class="kge-page kge-page--scroll">
    <h2 class="pg-title">知识应用</h2>
    <p class="pg-sub">问答日志是治理最重要的数据来源，每条记录都带引用与反馈入口，是命中率分析、缺口识别与纠错回流的基础。</p>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>问答日志与溯源 <el-tag size="small" type="info">治理数据源 · 今日 603 次</el-tag></span>
          <div class="src">
            <span class="srcinfo">源：<b>Dify 问答日志</b></span>
            <el-button size="small" @click="ElMessage.success('已刷新')">🔄 刷新</el-button>
            <el-button size="small" @click="goSearch">↗ 去统一检索</el-button>
          </div>
        </div>
      </template>
      <el-table :data="logs" style="width: 100%">
        <el-table-column prop="time" label="时间" width="80">
          <template #default="{ row }"><span class="mono">{{ row.time }}</span></template>
        </el-table-column>
        <el-table-column prop="app" label="应用方" width="150" />
        <el-table-column prop="query" label="问题" min-width="220">
          <template #default="{ row }"><span class="small">{{ row.query }}</span></template>
        </el-table-column>
        <el-table-column prop="kb" label="命中库" width="160" />
        <el-table-column label="结果" width="160">
          <template #default="{ row }"><el-tag :type="row.type as any">{{ row.result }}</el-tag></template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.pg-title { font-size: 19px; margin-bottom: 4px; }
.pg-sub { color: #6b7280; font-size: 13px; margin-bottom: 16px; line-height: 1.8; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.src { display: flex; align-items: center; gap: 8px; }
.srcinfo { font-size: 11px; color: #9ca3af; }
.srcinfo b { color: #64748b; }
.small { font-size: 12.5px; color: #475569; line-height: 1.8; }
.mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
</style>
