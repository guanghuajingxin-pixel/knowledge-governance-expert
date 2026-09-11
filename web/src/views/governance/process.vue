<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listDifyDatasets, type DifyDataset } from '@/api/dify'
import {
  listProcessedDocuments,
  enhanceDocument,
  enhanceAllDocuments,
  buildRelations,
  getDocumentRelations,
  getKnowledgeGraph,
  getProcessStats,
  listKnowledgeTags,
  type ProcessedDocumentItem,
  type KnowledgeRelationItem,
  type KnowledgeGraph,
  type KnowledgeTag,
  type ProcessStats,
} from '@/api/process'

const activeTab = ref('workbench')

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

async function loadStats() {
  try {
    stats.value = await getProcessStats()
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
  { name: 'LLM 加工服务', type: 'AI 增强', bearer: '系统配置 LLM', purpose: '打标/摘要/关系构建', url: '系统配置', status: '在线', statusType: 'success' },
  { name: 'Rerank 服务', type: '检索', bearer: 'Dify 内置', purpose: '语义重排', url: '随 Dify 配置', status: '在线', statusType: 'success' },
]

function openTool(url: string) {
  if (url.startsWith('http')) window.open(url, '_blank')
  else ElMessage.info('按配置 URL 跳转（原型演示）')
}

// ============================================================
// 知识加工工作台
// ============================================================
const datasets = ref<DifyDataset[]>([])
const datasetsLoading = ref(false)
const targetDatasetId = ref('')

const docList = ref<ProcessedDocumentItem[]>([])
const docListLoading = ref(false)
const enhancingIds = ref<Set<string>>(new Set())
const enhancingAll = ref(false)
const buildingRelations = ref(false)

const detailDoc = ref<ProcessedDocumentItem | null>(null)
const detailRelations = ref<KnowledgeRelationItem[]>([])
const detailDialogVisible = ref(false)

async function loadDatasets() {
  datasetsLoading.value = true
  try {
    const res = await listDifyDatasets()
    datasets.value = res.items || []
    if (!targetDatasetId.value && datasets.value.length) targetDatasetId.value = datasets.value[0].id
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载 Dify 知识库失败')
  } finally { datasetsLoading.value = false }
}

async function loadDocuments() {
  if (!targetDatasetId.value) return
  docListLoading.value = true
  try {
    const res = await listProcessedDocuments(targetDatasetId.value)
    docList.value = res.items || []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载文档列表失败')
  } finally { docListLoading.value = false }
}

function statusTag(s: string) {
  switch (s) {
    case 'completed': return { type: 'success', text: '已加工' }
    case 'processing': return { type: 'warning', text: '加工中' }
    case 'failed': return { type: 'danger', text: '失败' }
    default: return { type: 'info', text: '待加工' }
  }
}

async function doEnhance(doc: ProcessedDocumentItem) {
  if (!targetDatasetId.value) return
  enhancingIds.value.add(doc.document_id)
  try {
    const res = await enhanceDocument(targetDatasetId.value, doc.document_id)
    if (res.status === 'completed') {
      ElMessage.success(`「${doc.name}」加工完成`)
      await loadDocuments()
      await loadStats()
    } else {
      ElMessage.error(`加工失败：${res}`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加工失败')
  } finally {
    enhancingIds.value.delete(doc.document_id)
  }
}

async function doEnhanceAll() {
  if (!targetDatasetId.value) return
  enhancingAll.value = true
  try {
    const res = await enhanceAllDocuments(targetDatasetId.value)
    ElMessage.success(`批量加工完成：成功 ${res.completed} / 失败 ${res.failed}`)
    await loadDocuments()
    await loadStats()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '批量加工失败')
  } finally { enhancingAll.value = false }
}

async function doBuildRelations() {
  if (!targetDatasetId.value) return
  buildingRelations.value = true
  try {
    const res = await buildRelations(targetDatasetId.value)
    if (res.status === 'skipped') {
      ElMessage.warning(res.reason || '无法构建关系')
    } else {
      ElMessage.success(`知识关系构建完成：新增 ${res.created} 对关系`)
      await loadStats()
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '关系构建失败')
  } finally { buildingRelations.value = false }
}

async function openDetail(doc: ProcessedDocumentItem) {
  detailDoc.value = doc
  detailDialogVisible.value = true
  detailRelations.value = []
  try {
    const res = await getDocumentRelations(doc.document_id)
    detailRelations.value = res.items || []
  } catch { /* ignore */ }
}

// ============================================================
// 知识图谱
// ============================================================
const graphDatasets = ref<DifyDataset[]>([])
const graphDatasetId = ref('')
const graphLoading = ref(false)
const graph = ref<KnowledgeGraph>({ nodes: [], edges: [] })

async function loadGraphDatasets() {
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

onMounted(() => {
  loadStats()
  loadDatasets()
  loadGraphDatasets()
  loadTags()
})
</script>

<template>
  <div class="page">
    <h2 class="pg-title">知识加工</h2>
    <p class="pg-sub">
      加工是应用的基础。本模块对已进入 Dify 知识库的文档进行 AI 打标与摘要生成，
      并构建文档间的语义关系图谱，为智能问答提供更丰富的上下文工程能力。
    </p>

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

      <!-- 知识加工工作台 -->
      <el-tab-pane label="知识加工工作台" name="workbench">
        <el-card shadow="never">
          <div class="toolbar">
            <div class="toolbar-left">
              <span class="label">选择知识库：</span>
              <el-select
                v-model="targetDatasetId"
                placeholder="请选择 Dify 知识库"
                style="width: 320px"
                :loading="datasetsLoading"
                @change="loadDocuments"
              >
                <el-option
                  v-for="d in datasets"
                  :key="d.id"
                  :label="`${d.name}（${d.document_count} 篇）`"
                  :value="d.id"
                />
              </el-select>
              <el-button type="primary" plain @click="loadDocuments" :loading="docListLoading">刷新</el-button>
            </div>
            <div class="toolbar-right">
              <el-button type="primary" :loading="enhancingAll" :disabled="!targetDatasetId" @click="doEnhanceAll">
                全部 AI 加工
              </el-button>
              <el-button type="success" :loading="buildingRelations" :disabled="!targetDatasetId" @click="doBuildRelations">
                构建知识关系
              </el-button>
            </div>
          </div>

          <el-table
            v-loading="docListLoading"
            :data="docList"
            style="width: 100%; margin-top: 16px"
            empty-text="暂无文档或请先选择知识库"
          >
            <el-table-column prop="name" label="文档名称" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="doc-name" @click="openDetail(row as ProcessedDocumentItem)">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="doc_type" label="文档类型" width="120">
              <template #default="{ row }">
                <el-tag v-if="row.doc_type" size="small" type="info">{{ row.doc_type }}</el-tag>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="标签" min-width="200">
              <template #default="{ row }">
                <template v-if="row.tags && row.tags.length">
                  <el-tag
                    v-for="t in row.tags.slice(0, 4)"
                    :key="t"
                    size="small"
                    style="margin: 2px"
                  >{{ t }}</el-tag>
                  <span v-if="row.tags.length > 4" class="muted">+{{ row.tags.length - 4 }}</span>
                </template>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column prop="summary" label="摘要" min-width="280" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="small">{{ row.summary || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="加工状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTag(row.process_status).type as any" size="small">
                  {{ statusTag(row.process_status).text }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button
                  size="small"
                  type="primary"
                  link
                  :loading="enhancingIds.has((row as ProcessedDocumentItem).document_id)"
                  @click="doEnhance(row as ProcessedDocumentItem)"
                >AI 加工</el-button>
                <el-button size="small" link @click="openDetail(row as ProcessedDocumentItem)">详情</el-button>
              </template>
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
              <el-button type="primary" plain @click="loadGraph" :loading="graphLoading">刷新图谱</el-button>
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
            <el-empty v-else description="暂无图谱数据，请先在「知识加工工作台」中构建知识关系" />
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
          <div class="small" style="margin-top: 8px">策略约定源出钉钉文档《知识治理标准》，本页将标准实例化为引擎可执行的路由配置。</div>
        </el-card>
      </el-tab-pane>

      <!-- 工具与跳转配置 -->
      <el-tab-pane label="工具与跳转配置" name="tool">
        <div class="hl green">🧰 <span>工具注册表：Dify、同步后台、解析/转写/LLM 加工等工具统一登记，每个工具维护「管理入口 URL」。</span></div>
        <el-card shadow="never">
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
              </template>
            </el-table-column>
          </el-table>
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
              <li><b>选择知识库</b>：在「知识加工工作台」选择一个 Dify 知识库，加载文档列表。</li>
              <li><b>AI 加工</b>：点击「AI 加工」对单篇文档打标+摘要，或「全部 AI 加工」批量处理。</li>
              <li><b>构建关系</b>：加工完成后点击「构建知识关系」，自动分析文档间语义关联。</li>
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

    <!-- 文档加工详情弹窗 -->
    <el-dialog v-model="detailDialogVisible" :title="detailDoc?.name || '文档详情'" width="720px">
      <div v-if="detailDoc" class="detail-content">
        <div class="detail-row">
          <span class="detail-label">文档类型：</span>
          <el-tag v-if="detailDoc.doc_type" size="small">{{ detailDoc.doc_type }}</el-tag>
          <span v-else class="muted">—</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">加工状态：</span>
          <el-tag :type="statusTag(detailDoc.process_status).type as any" size="small">
            {{ statusTag(detailDoc.process_status).text }}
          </el-tag>
        </div>
        <div class="detail-row">
          <span class="detail-label">标签：</span>
          <el-tag v-for="t in detailDoc.tags" :key="t" size="small" style="margin: 2px">{{ t }}</el-tag>
          <span v-if="!detailDoc.tags?.length" class="muted">—</span>
        </div>
        <div class="detail-block">
          <div class="detail-label">摘要：</div>
          <p class="small">{{ detailDoc.summary || '暂无摘要，请先执行 AI 加工' }}</p>
        </div>

        <el-divider />
        <div class="detail-block">
          <div class="detail-label">关联文档（{{ detailRelations.length }}）：</div>
          <el-table v-if="detailRelations.length" :data="detailRelations" size="small" style="width: 100%">
            <el-table-column prop="target_name" label="文档名称" min-width="160" show-overflow-tooltip />
            <el-table-column prop="relation_type" label="关系类型" width="110">
              <template #default="{ row }">
                <el-tag :style="{ color: relationColor[row.relation_type] || '#909399', borderColor: relationColor[row.relation_type] || '#909399', background: (relationColor[row.relation_type] || '#909399') + '15' }" size="small">
                  {{ row.relation_type }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="weight" label="权重" width="80">
              <template #default="{ row }">{{ row.weight?.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="description" label="关系描述" min-width="200" show-overflow-tooltip />
          </el-table>
          <el-empty v-else description="暂无关联文档，请先构建知识关系" :image-size="80" />
        </div>
      </div>
    </el-dialog>
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
.muted { color: #909399; }
.mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #334155; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.hl { border-radius: 8px; padding: 10px 14px; font-size: 12.5px; margin-bottom: 14px; display: flex; gap: 8px; line-height: 1.7; }
.hl.green { background: #f0fdf4; border: 1px solid #bbf7d0; color: #065f46; }

.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.toolbar-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.toolbar-right { display: flex; align-items: center; gap: 8px; }
.label { font-size: 13px; color: #606266; white-space: nowrap; }
.doc-name { color: #409EFF; cursor: pointer; }
.doc-name:hover { text-decoration: underline; }

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

/* 详情弹窗 */
.detail-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.detail-block { margin-bottom: 16px; }
.detail-label { font-weight: 600; color: #303133; font-size: 13px; margin-bottom: 4px; display: block; }
</style>
