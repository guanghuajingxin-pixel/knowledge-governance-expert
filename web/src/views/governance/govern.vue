<script setup lang="ts">
import { onMounted, ref } from 'vue'
import KnowledgeGaps from './components/KnowledgeGaps.vue'
import { ElMessage } from 'element-plus'
import { getStandards, type StandardDoc } from '@/api/governance'

const activeTab = ref('gaps')

// 工单分诊
interface Ticket {
  id: number
  feedback: string
  rootCause: string
  rootCauseType: string
  action: string
  owner: string
  confidence: number
  status: 'pending' | 'confirmed' | 'reassigned'
}
const tickets = ref<Ticket[]>([
  { id: 1, feedback: '针距参数答错（答成 JK-5890 规格）', rootCause: '版本冲突', rootCauseType: 'warning', action: '下线 V2 残留分段 → 重加工', owner: '王品控', confidence: 0.94, status: 'pending' },
  { id: 2, feedback: '阶梯返利政策检索不到', rootCause: '知识缺口', rootCauseType: 'primary', action: '发起征集 → 销售运营', owner: '销售运营', confidence: 0.91, status: 'pending' },
  { id: 3, feedback: '规程截图匹配差', rootCause: '分段劣化', rootCauseType: 'success', action: '补图注 → 回流重索引', owner: '王品控', confidence: 0.88, status: 'pending' },
  { id: 4, feedback: '引用了已废止的 2024 版制度', rootCause: '不确定', rootCauseType: 'info', action: '版本治理 · 需人核实', owner: '—', confidence: 0.62, status: 'pending' },
])

function adjudicate(row: any, mode: 'confirmed' | 'reassigned') {
  const t = row as Ticket
  t.status = mode
  ElMessage.success(mode === 'confirmed' ? '工单进入处置流：钉钉待办已通知 Owner，完成后 AI 自动回归评测' : '已改派')
}

const rootCauseTag: Record<string, string> = {
  '版本冲突': 'warning',
  '知识缺口': 'primary',
  '分段劣化': 'success',
  '不确定': 'info',
}

// 质检台账
const qualityLedger = [
  { doc: '《高速绷缝机检验规程V3.docx》', rule: '命名不规范', ruleType: 'warning', suggestion: '改名 JK-8669D_检验规程_金加工过程_V3', owner: '王品控', status: '待人判断' },
  { doc: '《AI 智能体活动照片集.pptx》', rule: '3 张图片无描述', ruleType: 'warning', suggestion: 'AI 已起草图注，待采纳', owner: '黄景新', status: '待采纳' },
  { doc: '《2026 渠道政策(草稿).docx》', rule: '密级未定级', ruleType: 'danger', suggestion: 'AI 建议：内部（含商务条款）', owner: '销售运营', status: '待定密级' },
]

// 生命周期巡检
const lifecycle = [
  { item: '有效期到期（30天内）', count: '64 份', advice: '按 Owner 聚合，一键生成待办', action: 'Owner 更新原文档有效期' },
  { item: '90 天零引用', count: '12 份', advice: 'AI 评估：7 份建议归档，5 份建议保留', action: 'Owner 确认归档/保留' },
  { item: 'Owner 调岗/离职', count: '5 份', advice: '推荐继任 Owner（按部门与历史引用）', action: '重新认领（钉钉待办）' },
  { item: '版本冲突', count: '3 组', advice: 'AI 比对差异，建议取代关系', action: 'Owner 确认 → 通知同步换版' },
]

// 治理标准（数据源：钉钉 AI 多维表《杰克知识管理规范》
// baseId=N7dx2rn0JbNoBXLeuNw2ONvPJMGjLRb3 tableId=29Wa4h3，
// 通过 /governance/standards 接口实时拉取，下列快照仅作后端不可用时的兜底展示）
const standards = ref<StandardDoc[]>([
  { record_id: 'sRF8johAIq', doc_type: '管理制度类', code: 'DOC-20260905-0001', version: 'V2.3', status: '已发布', effective_date: '2023-01-15', link: 'https://example.com/docs/data-security-v1', maintainer: '黄景新' },
  { record_id: 'JPdupECG4e', doc_type: '产品操作手册类', code: 'DOC-20260905-0002', version: 'V1.7', status: '草稿', effective_date: '2023-06-01', link: 'https://example.com/docs/customer-privacy', maintainer: '黄景新' },
  { record_id: '70tKUx9iKr', doc_type: 'API接口调用说明类', code: 'DOC-20260905-0003', version: 'V3.1', status: '已发布', effective_date: '2022-11-20', link: 'https://example.com/docs/api-spec', maintainer: '黄景新' },
  { record_id: 'cdmHMjqz0Z', doc_type: '公文类', code: 'DOC-20260905-0004', version: 'V4.0', status: '已发布', effective_date: '2024-01-08', link: 'https://example.com/docs/kb-training', maintainer: '黄景新' },
  { record_id: 'cWSJnOlC2U', doc_type: '软件需求文档类', code: 'DOC-20260905-0005', version: 'V2.0', status: '审核中', effective_date: '2023-09-12', link: 'https://example.com/docs/version-control', maintainer: '黄景新' },
])
const standardsLoading = ref(false)
const standardsSyncedAt = ref('')

async function loadStandards() {
  standardsLoading.value = true
  try {
    const res = await getStandards()
    if (res.error) {
      ElMessage.error(res.error)
      return
    }
    standards.value = res.items
    standardsSyncedAt.value = res.fetched_at ? res.fetched_at.replace('T', ' ') : ''
  } finally {
    standardsLoading.value = false
  }
}

onMounted(loadStandards)

// 文档状态标签配色（与多维表选项：草稿/评审中/已发布/已废止/修订中/审核中）
const statusTag: Record<string, string> = {
  '已发布': 'success',
  '草稿': 'info',
  '审核中': 'warning',
  '评审中': 'warning',
  '修订中': 'warning',
  '已废止': 'danger',
}
</script>

<template>
  <div class="page">
    <h2 class="pg-title">知识治理</h2>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="知识缺口" name="gaps" lazy><KnowledgeGaps /></el-tab-pane>
      <!-- 工单智能分诊 -->
      <el-tab-pane label="工单智能分诊" name="triage">
        <div class="hl">
          🤖 <span><b>AI 分诊 · 人裁决：</b>应用端反馈进来后，AI 判定根因（知识缺口/版本冲突/分段劣化/权限/模型错误）、建议严重级与 Owner，并给出处置动作；置信度 <0.7 自动转人工。人在下表逐单确认或改派。</span>
        </div>
        <el-card class="card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>待人工确认（AI 已分诊）</span>
              <div class="src">
                <span class="srcinfo">源：<b>多维表《知识纠错工单》</b></span>
                <el-button size="small" @click="ElMessage.success('已从数据源刷新')">🔄 刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="tickets" style="width: 100%">
            <el-table-column prop="feedback" label="反馈" min-width="200">
              <template #default="{ row }"><span class="small">{{ row.feedback }}</span></template>
            </el-table-column>
            <el-table-column label="AI 根因判定" width="120">
              <template #default="{ row }">
                <el-tag :type="rootCauseTag[row.rootCause] as any">{{ row.rootCause }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="AI 建议处置" min-width="200">
              <template #default="{ row }">
                <div class="small">{{ row.action }} · Owner：{{ row.owner }}</div>
              </template>
            </el-table-column>
            <el-table-column label="置信度" width="90">
              <template #default="{ row }">
                <el-tag :type="row.confidence >= 0.7 ? 'success' : 'warning'">{{ row.confidence.toFixed(2) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="人裁决" width="180">
              <template #default="{ row }">
                <template v-if="row.status === 'pending'">
                  <el-button size="small" type="primary" @click="adjudicate(row, 'confirmed')">✓ 确认执行</el-button>
                  <el-button size="small" @click="adjudicate(row, 'reassigned')">改派</el-button>
                </template>
                <el-tag v-else :type="row.status === 'confirmed' ? 'success' : 'info'">
                  {{ row.status === 'confirmed' ? '已确认' : '已改派' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
        <el-row :gutter="16" class="kpi-row">
          <el-col :span="8"><div class="kpi"><div class="l">今日 AI 分诊 / 人确认</div><div class="v">18/15</div><div class="d">采纳率 83% · 3 单改派</div></div></el-col>
          <el-col :span="8"><div class="kpi"><div class="l">本周回流加工</div><div class="v">7 项</div><div class="d">重分段 3 · 重索引 2 · 转写重跑 2</div></div></el-col>
          <el-col :span="8"><div class="kpi"><div class="l">验证关单率</div><div class="v">78%</div><div class="d up">回归评测通过才关单</div></div></el-col>
        </el-row>
      </el-tab-pane>

      <!-- 质检台账 -->
      <el-tab-pane label="质检台账" name="quality">
        <el-card class="card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>入库质检台账 <el-tag size="small" type="info">AI 预检结果留痕 · 拦截≠删除</el-tag></span>
              <div class="src">
                <span class="srcinfo">源：<b>多维表《入库质检台账》</b></span>
                <el-button size="small" @click="ElMessage.success('已刷新')">🔄 刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="qualityLedger" style="width: 100%">
            <el-table-column prop="doc" label="文档" min-width="240" />
            <el-table-column label="命中规则" width="140">
              <template #default="{ row }"><el-tag :type="row.ruleType as any">{{ row.rule }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="suggestion" label="AI 建议" min-width="220">
              <template #default="{ row }"><span class="small">{{ row.suggestion }}</span></template>
            </el-table-column>
            <el-table-column prop="owner" label="Owner" width="100" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><el-tag type="primary">{{ row.status }}</el-tag></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 生命周期巡检 -->
      <el-tab-pane label="生命周期巡检" name="lifecycle">
        <el-card class="card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>自动巡检（每日） <el-tag size="small" type="info">AI 汇总异常 + 生成建议，人确认后推送钉钉待办</el-tag></span>
              <div class="src">
                <span class="srcinfo">源：<b>多维表《巡检结果》</b></span>
                <el-button size="small" @click="ElMessage.success('已刷新')">🔄 刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="lifecycle" style="width: 100%">
            <el-table-column prop="item" label="巡检项" min-width="180" />
            <el-table-column prop="count" label="今日发现" width="110" />
            <el-table-column prop="advice" label="AI 建议" min-width="260">
              <template #default="{ row }"><span class="small">{{ row.advice }}</span></template>
            </el-table-column>
            <el-table-column prop="action" label="动作（钉钉侧）" min-width="200">
              <template #default="{ row }"><span class="small">{{ row.action }}</span></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 治理标准 -->
      <el-tab-pane label="治理标准" name="standard">
        <el-card class="card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>知识治理标准 <el-tag size="small" type="info">钉钉多维表 · 单一维护入口</el-tag></span>
              <div class="src">
                <span class="srcinfo">源：<b>钉钉多维表《杰克知识管理规范》</b><template v-if="standardsSyncedAt"> · 同步于 {{ standardsSyncedAt }}</template></span>
                <el-button size="small" :loading="standardsLoading" @click="loadStandards">🔄 刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="standards" v-loading="standardsLoading" style="width: 100%">
            <el-table-column prop="doc_type" label="文档类型" min-width="150" />
            <el-table-column prop="code" label="类型编号" width="170" />
            <el-table-column prop="version" label="版本号" width="90" />
            <el-table-column label="文档状态" width="100">
              <template #default="{ row }">
                <el-tag :type="(statusTag[row.status] || 'info') as any">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="effective_date" label="生效日期" width="110" />
            <el-table-column prop="maintainer" label="维护人" width="100" />
            <el-table-column label="规范链接" min-width="200">
              <template #default="{ row }">
                <el-link type="primary" :href="row.link" target="_blank" style="font-size: 12.5px">{{ row.link }}</el-link>
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
.pg-title { font-size: 19px; margin-bottom: 16px; }
.card { margin-bottom: 16px; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.src { display: flex; align-items: center; gap: 8px; }
.srcinfo { font-size: 11px; color: #9ca3af; }
.srcinfo b { color: #64748b; font-weight: 500; }
.hl { border: 1px solid #fde68a; background: #fffbeb; border-radius: 8px; padding: 10px 14px; font-size: 12.5px; color: #92400e; margin-bottom: 14px; display: flex; gap: 8px; line-height: 1.7; }
.small { font-size: 12.5px; color: #475569; line-height: 1.8; }
.kpi-row { margin-top: 16px; }
.kpi { background: #fff; border: 1px solid #e5e8ee; border-radius: 12px; padding: 14px 16px; box-shadow: 0 1px 3px rgba(16,24,40,.06); }
.kpi .l { font-size: 12px; color: #6b7280; margin-bottom: 6px; }
.kpi .v { font-size: 24px; font-weight: 700; }
.kpi .d { font-size: 11.5px; margin-top: 4px; color: #6b7280; }
.kpi .d.up { color: #16a34a; }
</style>
