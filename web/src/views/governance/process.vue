<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const activeTab = ref('overview')

// 加工总览 KPI
const kpis = [
  { label: '今日加工文档', value: '80', desc: 'AI 增强 76 · 待人确认 9', type: '' },
  { label: '生成分段', value: '1,412', desc: '低质自动打回 38', type: '' },
  { label: 'AI 图注/摘要/打标', value: '236', desc: '人确认采纳率 94%', type: '' },
  { label: '评测通过率', value: '91.2%', desc: '加工变更后自动回归', type: 'up' },
]

// 加工流水线
const pipeline = [
  { step: '1 · 解析', executor: '工具：minerU/OCR/ASR', executorType: 'info', action: '图文版面解析、音视频转写', signal: '失败 2（K7视频，已告警）' },
  { step: '2 · 分段', executor: '引擎：Dify', executorType: 'success', action: '按知识类型路由策略（父子/页级/FAQ）', signal: '低质分段 38 自动打回' },
  { step: '3 · AI 增强', executor: 'AI', executorType: 'primary', action: '文档/章节摘要、假设性问题、术语扩展', signal: '76 篇完成' },
  { step: '4 · AI 打标', executor: 'AI + 人确认', executorType: 'primary', action: '系统标签 + 自定义标签建议', signal: '9 篇待人工确认' },
  { step: '5 · 索引', executor: '引擎：Dify', executorType: 'success', action: '小/大 chunk 向量、FAQ、全文倒排', signal: '全部完成' },
  { step: '6 · 回归评测', executor: 'AI', executorType: 'primary', action: '评测集自动回归，不达标回滚', signal: '486+62 题通过' },
]

// 加工引擎策略路由
const routes = [
  { type: '制度流程类', engine: 'Dify', engineType: 'success', chunk: '层级摘要（HiQA）', index: '章节摘要向量 + 全文', tool: '摘要 AI', status: '启用', statusType: 'success' },
  { type: '产品手册类', engine: 'Dify', engineType: 'success', chunk: '父子分段 + 图片描述', index: '小/大 chunk 多索引', tool: 'OCR · 图注 AI', status: '启用', statusType: 'success' },
  { type: 'FAQ/参数类', engine: 'Dify', engineType: 'success', chunk: 'FAQ 问答对抽取', index: '结构化倒排 + 向量', tool: 'FAQ 抽取 AI', status: '启用', statusType: 'success' },
  { type: '视频类', engine: 'Dify', engineType: 'success', chunk: 'ASR 转写后按语义分段', index: '向量', tool: 'ASR(ffmpeg)', status: '2 转写失败', statusType: 'warning' },
]

// 工具注册表
const tools = [
  { name: 'Dify 知识库', type: '加工引擎', bearer: 'Dify 平台', purpose: '分段/索引/检索策略', url: 'http://10.10.166.81/', status: '在线', statusType: 'success' },
  { name: '知识同步后台', type: '搬运', bearer: '自研（已上线）', purpose: '钉钉→Dify 增量同步', url: 'https://6da29zbc.qwenwork.host/', status: '在线', statusType: 'success' },
  { name: 'minerU 解析', type: '解析', bearer: '自部署服务', purpose: 'PDF/图文版面解析', url: 'http://10.10.169.30:8010/', status: '在线', statusType: 'success' },
  { name: 'OCR 服务', type: '解析', bearer: '自部署服务', purpose: '图片文字识别', url: 'http://10.10.169.30:8020/', status: '在线', statusType: 'success' },
  { name: 'ASR 转写', type: '解析', bearer: 'ffmpeg + 模型', purpose: '音视频转文字', url: '—（命令行工具）', status: '2 任务失败', statusType: 'warning' },
  { name: 'Rerank 服务', type: '检索', bearer: 'Dify 内置', purpose: '语义重排', url: '随 Dify 配置', status: '在线', statusType: 'success' },
  { name: '模型网关', type: '模型接入', bearer: 'LiteLLM', purpose: '统一模型出口/限流', url: 'http://10.10.169.34:18080/', status: '在线', statusType: 'success' },
]

function openTool(url: string) {
  if (url.startsWith('http')) window.open(url, '_blank')
  else ElMessage.info('按配置 URL 跳转（原型演示）')
}
</script>

<template>
  <div class="page">
    <h2 class="pg-title">知识加工</h2>
    <p class="pg-sub">加工是应用的基础。Dify 只是加工工具之一——本页维护加工引擎（按知识类型路由策略）与工具注册表（含各工具管理入口跳转配置），加工动作由引擎自动执行。</p>

    <el-tabs v-model="activeTab">
      <!-- 加工总览 -->
      <el-tab-pane label="加工总览" name="overview">
        <el-row :gutter="16" class="kpi-row">
          <el-col :span="6" v-for="k in kpis" :key="k.label">
            <div class="kpi">
              <div class="l">{{ k.label }}</div>
              <div class="v">{{ k.value }}</div>
              <div class="d" :class="k.type">{{ k.desc }}</div>
            </div>
          </el-col>
        </el-row>
        <el-card shadow="never" style="margin-top: 16px">
          <template #header><span>加工流水线（AI 节点 + 人工确认点）</span></template>
          <el-table :data="pipeline" style="width: 100%">
            <el-table-column prop="step" label="环节" width="120" />
            <el-table-column label="执行方" width="180">
              <template #default="{ row }"><el-tag :type="row.executorType as any">{{ row.executor }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="action" label="动作" min-width="280">
              <template #default="{ row }"><span class="small">{{ row.action }}</span></template>
            </el-table-column>
            <el-table-column prop="signal" label="质量信号" min-width="200">
              <template #default="{ row }"><span class="small">{{ row.signal }}</span></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 加工引擎配置 -->
      <el-tab-pane label="加工引擎配置" name="engine">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>加工引擎策略路由 <el-tag size="small" type="primary">按知识类型自动路由，可维护</el-tag></span>
              <el-button size="small" type="primary" @click="ElMessage.info('新增策略路由（原型演示）')">＋ 新增路由</el-button>
            </div>
          </template>
          <el-table :data="routes" style="width: 100%">
            <el-table-column prop="type" label="知识类型" width="130" />
            <el-table-column label="加工引擎" width="110">
              <template #default="{ row }"><el-tag :type="row.engineType as any">{{ row.engine }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="chunk" label="分段策略" min-width="180">
              <template #default="{ row }"><span class="small">{{ row.chunk }}</span></template>
            </el-table-column>
            <el-table-column prop="index" label="索引结构" min-width="180">
              <template #default="{ row }"><span class="small">{{ row.index }}</span></template>
            </el-table-column>
            <el-table-column prop="tool" label="挂载工具" width="140" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><el-tag :type="row.statusType as any">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="ElMessage.info(`编辑「${row.type}」策略路由`)">编辑</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="small" style="margin-top: 8px">策略约定源出钉钉文档《知识治理标准》，本页将标准实例化为引擎可执行的路由配置；编辑后自动触发回归评测。</div>
        </el-card>
      </el-tab-pane>

      <!-- 工具与跳转配置 -->
      <el-tab-pane label="工具与跳转配置" name="tool">
        <div class="hl green">🧰 <span>工具注册表：Dify、同步后台、解析/转写/重排等工具统一登记，每个工具维护「管理入口 URL」——页面上所有「去维护/去配置」按钮都按此配置跳转，工具更换只需改这里。</span></div>
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>工具与跳转配置</span>
              <el-button size="small" type="primary" @click="ElMessage.info('注册新工具（原型演示）')">＋ 注册新工具</el-button>
            </div>
          </template>
          <el-table :data="tools" style="width: 100%">
            <el-table-column prop="name" label="工具" width="140">
              <template #default="{ row }"><b>{{ row.name }}</b></template>
            </el-table-column>
            <el-table-column prop="type" label="类型" width="100" />
            <el-table-column prop="bearer" label="承载方" width="130" />
            <el-table-column prop="purpose" label="用途" min-width="180">
              <template #default="{ row }"><span class="small">{{ row.purpose }}</span></template>
            </el-table-column>
            <el-table-column prop="url" label="管理入口 URL" min-width="220">
              <template #default="{ row }"><span class="mono">{{ row.url }}</span></template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-tag :type="row.statusType as any">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button size="small" @click="openTool(row.url)">↗ 跳转</el-button>
                <el-button size="small" link type="primary" @click="ElMessage.info(`编辑「${row.name}」`)">编辑</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px 48px; max-width: 1320px; margin: 0 auto; }
.pg-title { font-size: 19px; margin-bottom: 4px; }
.pg-sub { color: #6b7280; font-size: 13px; margin-bottom: 16px; line-height: 1.8; }
.kpi-row { margin-bottom: 16px; }
.kpi { background: #fff; border: 1px solid #e5e8ee; border-radius: 12px; padding: 14px 16px; box-shadow: 0 1px 3px rgba(16,24,40,.06); }
.kpi .l { font-size: 12px; color: #6b7280; margin-bottom: 6px; }
.kpi .v { font-size: 24px; font-weight: 700; }
.kpi .d { font-size: 11.5px; margin-top: 4px; color: #6b7280; }
.kpi .d.up { color: #16a34a; }
.small { font-size: 12.5px; color: #475569; line-height: 1.8; }
.mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #334155; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.hl { border-radius: 8px; padding: 10px 14px; font-size: 12.5px; margin-bottom: 14px; display: flex; gap: 8px; line-height: 1.7; }
.hl.green { background: #f0fdf4; border: 1px solid #bbf7d0; color: #065f46; }
</style>
