<script setup lang="ts">
/**
 * 知识加工
 * 页签：钉钉知识 / 本地上传知识（原「知识中心」页迁入）+ 加工总览 / 知识图谱 / 标签库 / 加工说明
 * 默认落地「钉钉知识」页签
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listDifyDatasets, type DifyDataset } from '@/api/dify'
import {
  getKnowledgeGraph,
  getProcessStats,
  listKnowledgeTags,
  type KnowledgeGraph,
  type KnowledgeTag,
  type ProcessStats,
} from '@/api/process'
import { fetchTaskStats } from '@/api/knowledge-center'
import type { TaskQueueStats } from '@/types/knowledge-center'
import DingTalkKnowledgeTab from '@/views/knowledge-center/components/DingTalkKnowledgeTab.vue'
import KnowledgeManageTab from '@/views/knowledge-center/components/KnowledgeManageTab.vue'
import RecycleBinDialog from '@/views/knowledge-center/components/RecycleBinDialog.vue'
import KnowledgeDetailDialog from '@/views/knowledge-center/components/KnowledgeDetailDialog.vue'

// 默认页签：钉钉知识
const activeTab = ref('dingtalk')

// ============================================================
// 钉钉知识 / 本地上传知识（知识列表，原「知识中心」页）
// ============================================================
// 任务队列（仅本地上传文档有处理状态）
const taskStats = ref<TaskQueueStats>({ total: 0, executing: 0, completed: 0, failed: 0 })

// 弹窗（本地上传知识）
const recycleVisible = ref(false)
const detailVisible = ref(false)
const detailDocId = ref<string>('')

async function loadTaskStats() {
  try {
    taskStats.value = await fetchTaskStats('DOCUMENT')
  } catch {
    // silently fail
  }
}

function handleRecycleOpen() {
  recycleVisible.value = true
}

function handleDetailOpen(docId: string) {
  detailDocId.value = docId
  detailVisible.value = true
}

// ============================================================
// 加工总览 KPI
// ============================================================
const stats = ref<ProcessStats>({ total_documents: 0, completed: 0, failed: 0, relations: 0, tags: 0 })

const kpis = computed(() => [
  { label: '已加工文档', value: stats.value.total_documents, desc: `完成 ${stats.value.completed} · 失败 ${stats.value.failed}`, type: '' },
  { label: '知识关系数', value: stats.value.relations, desc: '文档间语义关联', type: '' },
  { label: '标签总数', value: stats.value.tags, desc: 'AI 自动生成 + 人工维护', type: '' },
  { label: '加工完成率', value: stats.value.total_documents ? `${Math.round((stats.value.completed / stats.value.total_documents) * 100)}%` : '0%', desc: '已完成 / 已加工文档', type: stats.value.completed > 0 ? 'up' : '' },
])

const statsLoaded = ref(false)
async function loadStats() {
  try {
    stats.value = await getProcessStats()
    statsLoaded.value = true
  } catch { /* ignore */ }
}

// 加工流水线（展示加工流程）
const pipeline = [
  { step: '1 · 采集', executor: '知识采集', executorType: 'info', action: '钉钉同步/手动上传 → Dify 知识库', signal: '文档已入 Dify' },
  { step: '2 · AI 打标', executor: 'LLM', executorType: 'primary', action: '主题标签、关键词、文档类型自动生成', signal: '支持人工微调' },
  { step: '3 · AI 摘要', executor: 'LLM', executorType: 'primary', action: '200字摘要，概括核心内容与适用场景', signal: '问答时注入上下文' },
  { step: '4 · 关系构建', executor: 'LLM', executorType: 'primary', action: '文档间引用/相似/因果等语义关系', signal: '知识图谱可视化' },
  { step: '5 · 上下文工程', executor: '智能问答', executorType: 'success', action: '摘要+关系扩展检索上下文', signal: '提升回答深度' },
]

// ============================================================
// 知识图谱
// ============================================================
const graphDatasets = ref<DifyDataset[]>([])
const graphDatasetId = ref('')
const graphLoading = ref(false)
const graph = ref<KnowledgeGraph>({ nodes: [], edges: [] })

async function loadGraphDatasets() {
  // 复用全局 Dify 数据集持久缓存（kge:dify_datasets_v1，1 小时）：
  // 命中秒开，后台校准；与知识采集两个页签共享
  try {
    const raw = localStorage.getItem('kge:dify_datasets_v1')
    if (raw) {
      const c = JSON.parse(raw) as { ts: number; items: DifyDataset[] }
      if (Date.now() - c.ts <= 3_600_000 && c.items?.length) {
        graphDatasets.value = c.items
        if (!graphDatasetId.value && graphDatasets.value.length) graphDatasetId.value = graphDatasets.value[0].id
        listDifyDatasets().then((res) => {
          const items = res.items || []
          if (items.length) graphDatasets.value = items
        }).catch(() => { /* 保留缓存 */ })
        return
      }
    }
  } catch { /* 走网络 */ }
  try {
    const res = await listDifyDatasets()
    graphDatasets.value = res.items || []
    if (!graphDatasetId.value && graphDatasets.value.length) graphDatasetId.value = graphDatasets.value[0].id
  } catch { /* ignore */ }
}

async function loadGraph() {
  if (!graphDatasetId.value) return
  graphLoading.value = true
  try {
    graph.value = await getKnowledgeGraph(graphDatasetId.value)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载知识图谱失败')
  } finally { graphLoading.value = false }
}

// 简单的圆形布局计算
const graphLayout = computed(() => {
  const nodes = graph.value.nodes
  const edges = graph.value.edges
  const n = nodes.length
  const cx = 400, cy = 300, r = Math.min(260, Math.max(100, n * 18))
  const positions: Record<string, { x: number; y: number }> = {}
  nodes.forEach((node, i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2
    positions[node.id] = {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
    }
  })
  return { positions, nodes, edges }
})

const relationColor: Record<string, string> = {
  '引用': '#409EFF', '相似主题': '#67C23A', '因果': '#E6A23C',
  '包含': '#F56C6C', '并列': '#909399', '前置知识': '#9C27B0',
  '依赖': '#00BCD4', '对比': '#FF9800',
}

// ============================================================
// 标签云
// ============================================================
const tags = ref<KnowledgeTag[]>([])
async function loadTags() {
  try {
    const res = await listKnowledgeTags()
    tags.value = res.items || []
  } catch { /* ignore */ }
}

// 各页签数据「切到才拉」：知识加工页默认停在「钉钉知识」，
// 加工总览 / 知识图谱 / 标签库的数据在挂载时并不用，
// 原先无条件并发 3 个请求，白占后端连接也拖慢首屏。
watch(activeTab, (v) => {
  if (v === 'local') loadTaskStats()
  else if (v === 'overview' && !statsLoaded.value) loadStats()
  else if (v === 'graph' && !graphDatasets.value.length) loadGraphDatasets()
  else if (v === 'tags' && !tags.value.length) loadTags()
}, { immediate: true })

onMounted(() => {
  setInterval(() => {
    if (activeTab.value === 'local') loadTaskStats()
  }, 30000)
})
</script>

<template>
  <div class="kge-page">

    <el-tabs v-model="activeTab">
      <!-- 钉钉知识：钉钉开放平台实时文件列表 -->
      <el-tab-pane label="钉钉知识" name="dingtalk">
        <DingTalkKnowledgeTab />
      </el-tab-pane>

      <!-- 本地上传知识：平台内上传的文档（lazy：内部组件挂载即发 3 个请求，首屏不需要） -->
      <el-tab-pane label="本地上传知识" name="local" lazy>
        <KnowledgeManageTab
          scope-tab="DOCUMENT"
          :stats="taskStats"
          @recycle="handleRecycleOpen"
          @detail="handleDetailOpen"
        />
      </el-tab-pane>

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

      <!-- 知识图谱 -->
      <el-tab-pane label="知识图谱" name="graph">
        <el-card shadow="never">
          <div class="toolbar">
            <div class="toolbar-left">
              <span class="label">选择知识库：</span>
              <el-select
                v-model="graphDatasetId"
                placeholder="请选择 Dify 知识库"
                style="width: 320px"
                @change="loadGraph"
              >
                <el-option
                  v-for="d in graphDatasets"
                  :key="d.id"
                  :label="d.name"
                  :value="d.id"
                />
              </el-select>
              <el-button type="primary" plain :loading="graphLoading" @click="loadGraph">刷新图谱</el-button>
            </div>
            <div class="toolbar-right">
              <span class="small muted">共 {{ graph.nodes.length }} 个节点 · {{ graph.edges.length }} 条关系</span>
            </div>
          </div>

          <div v-loading="graphLoading" class="graph-container" style="margin-top: 16px">
            <svg v-if="graph.nodes.length" :width="800" :height="600" class="graph-svg">
              <!-- 边 -->
              <line
                v-for="(e, i) in graphLayout.edges"
                :key="'e' + i"
                :x1="graphLayout.positions[e.source]?.x"
                :y1="graphLayout.positions[e.source]?.y"
                :x2="graphLayout.positions[e.target]?.x"
                :y2="graphLayout.positions[e.target]?.y"
                :stroke="relationColor[e.relation_type] || '#909399'"
                :stroke-width="1 + e.weight * 3"
                :stroke-opacity="0.4 + e.weight * 0.6"
              />
              <!-- 节点 -->
              <g v-for="node in graphLayout.nodes" :key="node.id">
                <circle
                  :cx="graphLayout.positions[node.id].x"
                  :cy="graphLayout.positions[node.id].y"
                  r="8"
                  fill="#409EFF"
                  stroke="#fff"
                  stroke-width="2"
                />
                <text
                  :x="graphLayout.positions[node.id].x"
                  :y="graphLayout.positions[node.id].y - 14"
                  text-anchor="middle"
                  font-size="12"
                  fill="#303133"
                >{{ node.name.length > 16 ? node.name.slice(0, 16) + '…' : node.name }}</text>
              </g>
            </svg>
            <el-empty v-else description="暂无图谱数据，请先构建知识关系" />
          </div>

          <el-divider v-if="graph.edges.length" />
          <div v-if="graph.edges.length" class="legend">
            <span class="small muted">关系类型图例：</span>
            <el-tag
              v-for="(color, type) in relationColor"
              :key="type"
              size="small"
              :style="{ background: color, borderColor: color, color: '#fff' }"
              style="margin: 0 4px"
            >{{ type }}</el-tag>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- 标签库 -->
      <el-tab-pane label="标签库" name="tags">
        <el-card shadow="never">
          <div class="tag-cloud" v-if="tags.length">
            <el-tag
              v-for="t in tags"
              :key="t.id"
              :style="{ background: t.color + '20', color: t.color, borderColor: t.color, fontSize: Math.max(12, Math.min(22, 12 + t.count)) + 'px' }"
              style="margin: 6px; padding: 4px 12px"
            >
              {{ t.name }} <span class="small">×{{ t.count }}</span>
            </el-tag>
          </div>
          <el-empty v-else description="暂无标签，请先对文档进行 AI 加工" />
        </el-card>
      </el-tab-pane>

      <!-- 加工说明 -->
      <el-tab-pane label="加工说明" name="guide">
        <el-card shadow="never">
          <div class="guide-content">
            <h3>📌 知识加工是什么</h3>
            <p class="small">
              知识加工是对已采集入库的文档进行 <b>结构化增强</b> 的过程。原始文档进入 Dify 知识库后，
              仅被切分为向量片段用于语义检索，缺乏主题标签、摘要和文档间关联。
              本模块通过 LLM 对文档进行二次加工，产出可被智能体直接利用的结构化知识。
            </p>

            <h3>🔧 核心能力</h3>
            <div class="feature-grid">
              <div class="feature-card">
                <div class="feature-icon">🏷️</div>
                <div class="feature-title">AI 打标</div>
                <div class="feature-desc small">自动生成 3-6 个主题标签、3-8 个检索关键词，识别文档类型（制度/技术/产品/FAQ 等）。标签写入统一标签库，支持统计与过滤。</div>
              </div>
              <div class="feature-card">
                <div class="feature-icon">📝</div>
                <div class="feature-title">摘要生成</div>
                <div class="feature-desc small">生成 200 字以内的文档摘要，概括核心内容与适用场景。问答时摘要作为上下文前置注入，帮助模型快速理解文档全貌。</div>
              </div>
              <div class="feature-card">
                <div class="feature-icon">🕸️</div>
                <div class="feature-title">知识关系构建</div>
                <div class="feature-desc small">对已加工文档两两分析，识别引用、相似主题、因果、包含、并列、前置知识等语义关系，构建知识图谱。</div>
              </div>
              <div class="feature-card">
                <div class="feature-icon">🧠</div>
                <div class="feature-title">上下文工程</div>
                <div class="feature-desc small">提供 <code>GET /api/v1/process/context/expand</code> 接口，问答时根据命中文档扩展关联文档与摘要，提升回答深度。</div>
              </div>
            </div>

            <h3>📋 操作流程</h3>
            <ol class="steps">
              <li><b>文档入库</b>：文档经钉钉同步 / 手动上传进入 Dify 知识库（入库结果见「钉钉知识」「本地上传知识」页签）。</li>
              <li><b>AI 加工</b>：对入库文档执行打标 + 摘要，识别文档类型，产出结构化知识。</li>
              <li><b>构建关系</b>：加工完成后分析文档间引用、相似主题、因果等语义关联。</li>
              <li><b>查看图谱</b>：在「知识图谱」页签可视化文档关系网络。</li>
              <li><b>问答应用</b>：智能问答时自动调用加工结果扩展上下文。</li>
            </ol>

            <h3>🔌 上下文扩展接口（供智能问答调用）</h3>
            <div class="code-block">
              <pre>GET /api/v1/process/context/expand
  ?document_ids=doc1,doc2,doc3
  &query=用户问题
  &max_related=3

响应：
{
  "summaries": [{"document_id", "name", "summary", "tags", "doc_type"}],
  "related":   [{"document_id", "name", "relation_type", "weight", "description", "summary", "tags"}],
  "tags":      ["标签1", "标签2"]
}</pre>
            </div>
            <p class="small muted">
              智能问答检索到命中文档后，调用此接口获取：① 命中文档摘要（注入 system prompt）；
              ② 关联文档（用于深度探索/多文档引用）；③ 标签聚合（用于主题过滤或路由）。
            </p>

            <h3>⚙️ 数据存储</h3>
            <table class="data-table">
              <thead>
                <tr><th>表名</th><th>用途</th></tr>
              </thead>
              <tbody>
                <tr><td><code>processed_documents</code></td><td>文档加工记录：标签、摘要、关键词、文档类型、加工状态</td></tr>
                <tr><td><code>knowledge_relations</code></td><td>知识关系：源文档→目标文档，关系类型、权重、描述</td></tr>
                <tr><td><code>knowledge_tags</code></td><td>标签库：标签名、颜色、使用次数</td></tr>
              </tbody>
            </table>

            <h3>💡 设计思路</h3>
            <p class="small">
              本模块遵循「<b>加工与检索解耦</b>」原则：Dify 负责文档分段与向量索引（检索层），
              本模块负责元数据增强（标签/摘要/关系）。两者通过 Dify document_id 关联。
              智能问答时，先由 Dify 检索命中片段，再通过本模块的加工结果扩展上下文，
              实现「向量检索 + 结构化知识」的融合，让智能体不仅能找到答案，还能理解文档全貌与关联。
            </p>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 回收站弹窗（本地文档） -->
    <RecycleBinDialog v-model="recycleVisible" />

    <!-- 知识详情弹窗（本地文档） -->
    <KnowledgeDetailDialog v-model="detailVisible" :doc-id="detailDocId" />
  </div>
</template>

<style scoped>
.pg-title { font-size: 19px; margin-bottom: 12px; }
.kpi-row { margin-bottom: 16px; }
.kpi { background: #fff; border: 1px solid #e5e8ee; border-radius: 12px; padding: 14px 16px; box-shadow: 0 1px 3px rgba(16,24,40,.06); }
.kpi .l { font-size: 12px; color: #6b7280; margin-bottom: 6px; }
.kpi .v { font-size: 24px; font-weight: 700; }
.kpi .d { font-size: 11.5px; margin-top: 4px; color: #6b7280; }
.kpi .d.up { color: #16a34a; }
.small { font-size: 12.5px; color: #475569; line-height: 1.8; }
.muted { color: #909399; }

.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.toolbar-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.toolbar-right { display: flex; align-items: center; gap: 8px; }
.label { font-size: 13px; color: #606266; white-space: nowrap; }

/* 知识图谱 */
.graph-container { display: flex; justify-content: center; background: #fafafa; border-radius: 8px; padding: 12px; min-height: 400px; }
.graph-svg { max-width: 100%; }
.legend { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }

/* 标签云 */
.tag-cloud { display: flex; flex-wrap: wrap; gap: 4px; min-height: 120px; }

/* 加工说明 */
.guide-content h3 { font-size: 15px; margin: 24px 0 10px; color: #1a1a2e; }
.guide-content h3:first-child { margin-top: 0; }
.feature-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.feature-card { border: 1px solid #e5e8ee; border-radius: 10px; padding: 16px; background: #fafbfc; }
.feature-icon { font-size: 24px; margin-bottom: 8px; }
.feature-title { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
.feature-desc { color: #475569; }
.steps { padding-left: 20px; line-height: 2; }
.steps li { font-size: 13px; }
.code-block { background: #1e1e1e; border-radius: 8px; padding: 16px; overflow-x: auto; margin: 8px 0; }
.code-block pre { color: #d4d4d4; font-size: 12px; line-height: 1.7; margin: 0; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th, .data-table td { border: 1px solid #e5e8ee; padding: 8px 12px; text-align: left; }
.data-table th { background: #f5f7fa; font-weight: 600; }
.data-table code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 12px; }
</style>
