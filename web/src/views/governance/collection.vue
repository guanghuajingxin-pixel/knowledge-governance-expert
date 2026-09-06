<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { UploadUserFile } from 'element-plus'
import { getSettings, type SettingsResponse } from '@/api/settings'
import { listDifyDatasets, uploadDifyDocument, type DifyDataset } from '@/api/dify'

const router = useRouter()

const activeTab = ref('upload')

// ============ 上传到 Dify 知识库（核心功能） ============
const difyBaseUrl = ref('')
const datasets = ref<DifyDataset[]>([])
const loadingDatasets = ref(false)
const datasetsError = ref('')
const datasetsLoaded = ref(false)
const notConfigured = ref(false)
const selectedDatasetId = ref('')
const selectedDatasetName = computed(() =>
  datasets.value.find((d) => d.id === selectedDatasetId.value)?.name || '')

// Dify 知识库管理页地址（去掉 API 路径中的 /v1，指向 Web UI 的 /datasets）
const difyDatasetsUrl = computed(() => {
  if (!difyBaseUrl.value) return ''
  return difyBaseUrl.value.replace(/\/v1\/?$/, '') + '/datasets'
})

function goCreateDataset() {
  if (difyDatasetsUrl.value) {
    window.open(difyDatasetsUrl.value, '_blank')
  } else {
    ElMessage.warning('Dify 服务地址未配置，请先在系统配置中设置')
  }
}

async function loadDatasets() {
  loadingDatasets.value = true
  datasetsError.value = ''
  notConfigured.value = false
  try {
    const res = await listDifyDatasets()
    datasets.value = res.items || []
    datasetsError.value = res.error || ''
    if (res.error) {
      datasets.value = []
      selectedDatasetId.value = ''
      if (res.error.includes('尚未配置')) notConfigured.value = true
    } else if (!datasets.value.find((d) => d.id === selectedDatasetId.value)) {
      selectedDatasetId.value = datasets.value[0]?.id || ''
    }
  } catch (e: any) {
    datasetsError.value = e?.response?.data?.detail || e?.message || '加载失败'
    datasets.value = []
    selectedDatasetId.value = ''
  } finally {
    datasetsLoaded.value = true
    loadingDatasets.value = false
  }
}

// 上传文档
const MAX_FILES = 5
const MAX_SIZE_MB = 15
const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
const ACCEPT_EXTS = '.docx,.xls,.md,.html,.csv,.markdown,.pdf,.mdx,.xlsx,.txt,.vtt,.properties,.htm'
const uploadFiles = ref<UploadUserFile[]>([])
const uploading = ref(false)
const currentUploading = ref('')
interface UploadResult { name: string; ok: boolean; message: string }
const uploadResults = ref<UploadResult[]>([])

function beforeUpload(file: File) {
  if (file.size > MAX_SIZE_BYTES) {
    ElMessage.error(`文件「${file.name}」超过 ${MAX_SIZE_MB} MB，已跳过`)
    return false
  }
  return true
}

function onExceed() {
  ElMessage.warning(`每批最多上传 ${MAX_FILES} 个文件`)
}

async function startUpload() {
  if (!selectedDatasetId.value) {
    ElMessage.warning('请先选择目标知识库')
    return
  }
  const files = uploadFiles.value.map((f) => f.raw).filter(Boolean) as File[]
  if (!files.length) {
    ElMessage.warning('请先选择要上传的文档')
    return
  }
  // 二次校验：过滤超过 15MB 的文件（防止 before-upload 在某些场景下未拦截）
  const validFiles: File[] = []
  for (const f of files) {
    if (f.size > MAX_SIZE_BYTES) {
      uploadResults.value.push({ name: f.name, ok: false, message: `文件超过 ${MAX_SIZE_MB} MB 最大上传限制，已跳过` })
    } else {
      validFiles.push(f)
    }
  }
  if (!validFiles.length) {
    ElMessage.warning(`所有文件均超过 ${MAX_SIZE_MB} MB 限制`)
    uploadFiles.value = []
    return
  }
  uploading.value = true
  for (const f of validFiles) {
    currentUploading.value = f.name
    try {
      await uploadDifyDocument(selectedDatasetId.value, f)
      uploadResults.value.push({ name: f.name, ok: true, message: '已上传，Dify 自动分段索引中' })
    } catch (e: any) {
      uploadResults.value.push({ name: f.name, ok: false, message: e?.response?.data?.detail || e?.message || '上传失败' })
    }
  }
  currentUploading.value = ''
  uploading.value = false
  uploadFiles.value = []
  await loadDatasets()
}

onMounted(async () => {
  try {
    const s: SettingsResponse = await getSettings()
    difyBaseUrl.value = (s.dify_base_url?.value || '').replace(/\*+$/, '').trim()
  } catch {
    difyBaseUrl.value = ''
  }
  loadDatasets()
})

// AI 预检
const showCheck = ref(false)
let judged = 0
const totalChecks = 4
const checkCount = ref(`尚有 ${totalChecks} 项待判断`)

interface CheckItem {
  title: string
  badge: string
  badgeType: string
  content: string
  judged: boolean
}
const checkItems = ref<CheckItem[]>([
  { title: '🏷️ 命名规则校验', badge: '不通过', badgeType: 'warning', content: '检测到命名不符合规范《机型_文档类型_主题_版本》——缺少机型前缀。<br>AI 建议：改为 <b>《JK-8669D_检验规程_金加工过程_V3》</b>', judged: false },
  { title: '🧾 元数据推荐', badge: '已生成', badgeType: 'success', content: 'AI 推荐元数据：密级=<b>内部</b> · 分类=<b>品质检验</b> · 适用机型=<b>JK-8669D</b> · 标签=<b>金加工 / 绷缝机系列</b> · 有效期建议=<b>2027-09-05</b>', judged: false },
  { title: '🔁 重复/冲突检测', badge: '发现相似', badgeType: 'warning', content: '与库内《高速绷缝机检验规程V2》相似度 <b>92.4%</b>。AI 判断为版本迭代而非重复文档，建议声明「V3 取代 V2」。', judged: false },
  { title: '🖼️ 图片预检', badge: 'AI 已起草 3 条图注', badgeType: 'info', content: '检测到 3 张图片无文字描述（无图注将无法被自然语言召回）。AI 已生成图注草稿。', judged: false },
])

function simUpload() {
  showCheck.value = true
  judged = 0
  checkCount.value = `尚有 ${totalChecks} 项待判断`
  checkItems.value.forEach((i) => (i.judged = false))
  ElMessage.success('AI 预检完成：4 项检查，待您判断')
}

function judge(idx: number, action: string) {
  checkItems.value[idx].judged = true
  judged = Math.min(judged + 1, totalChecks)
  checkCount.value = `已完成 ${judged}/${totalChecks} 项`
  ElMessage.success(`已判断：${action}`)
}

function release() {
  if (judged < totalChecks) {
    ElMessage.warning('请先完成所有预检项判断')
    return
  }
  ElMessage.success('已放行：进入同步后台 → 加工（原型演示）')
}

// 预检规则
const precheckRules = [
  { rule: '命名规则：机型_文档类型_主题_版本', tag: 'AI 校验' },
  { rule: '元数据必填：密级/Owner/适用范围/有效期', tag: 'AI 推荐' },
  { rule: '重复检测：相似度 >92% 提示取代/裁决', tag: 'AI 判定' },
  { rule: '图片必须有描述，缺图注 AI 起草', tag: 'AI 起草' },
  { rule: '密级映射权限过滤规则', tag: 'AI 建议' },
]

// 同步源状态
const syncSources = [
  { name: '产品手册', dingtalk: '产品中心/产品手册', target: 'Dify·产品手册', docs: 328, lastSync: '今日 02:00', result: '新 3 · 更 11 · 败 0', status: '正常', statusType: 'success' },
  { name: '营销-SR方案库', dingtalk: '营销中心/SR方案', target: 'Dify·SR方案库', docs: 96, lastSync: '今日 08:00', result: '更 4 · 败 1', status: '失败 1', statusType: 'warning' },
  { name: '售后知识库', dingtalk: '售后服务/知识中心', target: 'Dify·售后知识', docs: 41, lastSync: '—', result: '—', status: '停用', statusType: 'info' },
  { name: '研发视频资料', dingtalk: '研发中心/K7视频', target: 'Dify·K7视频', docs: 7, lastSync: '今日 02:00', result: '更 1 · 败 2', status: '失败 2', statusType: 'danger' },
]

// 缺口与征集
const gaps = [
  { question: '大客户的 VIP 折扣怎么算', count: '41 次', aiJudge: '知识缺口 → 建议征集', judgeType: 'primary', owner: '已确认 → 销售运营', status: '征集中 1/3', statusType: 'warning' },
  { question: 'JK-8669D 包缝参数对照', count: '32 次', aiJudge: '版本冲突 → 建议治理', judgeType: 'warning', owner: '待裁决', status: '待确认', statusType: 'primary' },
  { question: '出口 CE 认证流程', count: '27 次', aiJudge: '知识缺口 → 建议征集', judgeType: 'primary', owner: '已确认 → 体系办', status: '待启动', statusType: 'info' },
]
</script>

<template>
  <div class="page">
    <h2 class="pg-title">知识采集</h2>
    <p class="pg-sub">核心功能：<b>上传知识到 Dify 知识库</b>。先选择目标知识库（Dify 链接在「系统配置」中维护，右上角可快速跳转；不存在可一键新建），上传后由 AI 完成预检建议（命名校验、元数据推荐、重复检测、图注草稿），<b>人只做判断</b>。</p>
    <div class="chain">📥 采集（AI 预检 + 人确认） <span class="arr">▶</span> ⚙️ 加工（引擎自动） <span class="arr">▶</span> 🔗 应用（问答+反馈） <span class="arr">▶</span> 🛡️ 治理 <span class="arr">⟲</span></div>

    <el-tabs v-model="activeTab">
      <!-- 上传到 Dify 知识库（核心功能） -->
      <el-tab-pane label="上传到 Dify 知识库" name="upload">
        <el-row :gutter="16">
          <el-col :span="10">
            <el-card shadow="never">
              <template #header>
                <div class="card-header">
                  <span>Dify 知识库</span>
                  <el-button size="small" type="primary" plain @click="router.push('/settings')">去配置</el-button>
                </div>
              </template>
              <el-form label-width="100px">
                <el-form-item label="知识库列表">
                  <div class="field-row">
                    <el-select v-model="selectedDatasetId" placeholder="请选择目标知识库" style="flex: 1" :loading="loadingDatasets" :disabled="notConfigured">
                      <el-option v-for="d in datasets" :key="d.id" :value="d.id" :label="`${d.name}（${d.document_count} 篇文档）`" />
                    </el-select>
                    <el-button :loading="loadingDatasets" @click="loadDatasets">刷新</el-button>
                    <el-button type="success" @click="goCreateDataset">去新建</el-button>
                  </div>
                </el-form-item>
              </el-form>
              <el-alert v-if="notConfigured" type="info" :closable="false" style="margin-top: 8px"
                title="Dify 尚未配置">
                <template #default>
                  <div>请先在系统配置中设置 Dify 服务地址与 API Key，再选择知识库上传文档。</div>
                  <el-button size="small" type="primary" style="margin-top: 8px" @click="router.push('/settings')">去配置</el-button>
                </template>
              </el-alert>
              <el-alert v-else-if="datasetsError" type="error" :closable="false" style="margin-top: 8px"
                title="无法连接 Dify 知识库" :description="`${datasetsError}。请检查系统配置中的服务地址与 API Key 是否正确、Dify 服务是否可达。`" />
              <el-alert v-else-if="datasetsLoaded && !loadingDatasets && !datasets.length" type="warning" :closable="false" style="margin-top: 8px"
                title="Dify 中还没有知识库">
                <template #default>
                  <div>连接成功，但当前 API Key 下没有任何知识库。请先到 Dify 控制台新建知识库并配置解析策略后再上传文档。</div>
                  <el-button size="small" type="success" style="margin-top: 8px" @click="goCreateDataset">去新建</el-button>
                </template>
              </el-alert>
            </el-card>
          </el-col>

          <el-col :span="14">
            <el-card shadow="never" class="upload-card">
              <template #header>
                <div class="card-header">
                  <span>上传文档到 {{ selectedDatasetName || '（未选择知识库）' }}</span>
                  <el-tag size="small" type="info">上传后 Dify 自动分段与索引</el-tag>
                </div>
              </template>
              <el-upload v-model:file-list="uploadFiles" drag multiple :auto-upload="false" :disabled="!selectedDatasetId || uploading"
                :accept="ACCEPT_EXTS" :limit="MAX_FILES" :before-upload="beforeUpload" :on-exceed="onExceed">
                <div class="di">📄</div>
                <div class="dt">拖拽文件到此处，或 <em>点击选择</em></div>
                <div class="dd">支持 DOCX / XLS / MD / HTML / CSV / PDF / MDX / XLSX / TXT / VTT / PROPERTIES / HTM 等格式，每批最多 {{ MAX_FILES }} 个，单个不超过 {{ MAX_SIZE_MB }} MB</div>
              </el-upload>
              <div style="margin-top: 12px; display: flex; gap: 8px; align-items: center">
                <el-button type="primary" :loading="uploading" :disabled="!uploadFiles.length || !selectedDatasetId" @click="startUpload">
                  {{ uploading ? `上传中：${currentUploading}` : `开始上传（${uploadFiles.length} 个文件）` }}
                </el-button>
                <span class="small" v-if="!selectedDatasetId">请先在左侧选择或新建目标知识库</span>
              </div>

              <el-table v-if="uploadResults.length" :data="uploadResults" size="small" style="margin-top: 12px">
                <el-table-column prop="name" label="文件" min-width="180" />
                <el-table-column label="结果" width="90">
                  <template #default="{ row }">
                    <el-tag :type="row.ok ? 'success' : 'danger'" size="small">{{ row.ok ? '成功' : '失败' }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="message" label="说明" min-width="200" />
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- 上传前 AI 预检 -->
      <el-tab-pane label="上传前 AI 预检" name="precheck">
        <div class="hl blue">💡 <span>所有上传文档先过 AI 预检（判定类模型 temperature=0）。预检不拦截文件本身，只生成建议项，人确认后放行进入同步与加工。</span></div>
        <el-row :gutter="16">
          <el-col :span="14">
            <div class="drop" @click="simUpload">
              <div class="di">📄</div>
              <div class="dt">拖拽 / 点击上传文档</div>
              <div class="dd">支持 docx / pdf / pptx / xlsx / md / 音视频<br>上传即触发 AI 预检：命名规则 → 元数据 → 重复 → 图片</div>
            </div>

            <div v-if="showCheck" class="ai-check">
              <div class="ach">🤖 AI 预检报告 ·《高速绷缝机检验规程V3.docx》<el-tag size="small" type="info" style="margin-left: auto">用时 3.2s</el-tag></div>
              <div v-for="(item, idx) in checkItems" :key="idx" class="ckitem" :class="{ judged: item.judged }">
                <div class="ckh">{{ item.title }} <el-tag :type="item.badgeType as any" size="small">{{ item.badge }}</el-tag></div>
                <div class="ckb" v-html="item.content"></div>
                <div class="ckbtns" v-if="!item.judged">
                  <el-button size="small" type="primary" @click="judge(idx, '已采纳 AI 建议')">✓ 采纳</el-button>
                  <el-button size="small" @click="judge(idx, '已修改后采用')">✎ 修改</el-button>
                  <el-button size="small" @click="judge(idx, '已驳回')">✕ 驳回</el-button>
                </div>
                <el-tag v-else type="success" size="small">已判断</el-tag>
              </div>
              <div class="ck-footer">
                <span class="small" style="flex:1">{{ checkCount }}</span>
                <el-button type="primary" @click="release">确认放行，进入加工</el-button>
              </div>
            </div>
          </el-col>

          <el-col :span="10">
            <el-card shadow="never">
              <template #header>
                <div class="card-header">
                  <span>预检规则（AI 执行 · 规则维护在钉钉）</span>
                  <el-button size="small" @click="ElMessage.success('已刷新')">🔄</el-button>
                </div>
              </template>
              <ul class="dotlist">
                <li v-for="r in precheckRules" :key="r.rule">
                  <span>{{ r.rule }}</span>
                  <el-tag size="small" type="primary" effect="plain">{{ r.tag }}</el-tag>
                </li>
              </ul>
              <div class="small" style="margin-top: 8px">人只做判断：每项建议三选一（采纳/修改/驳回），AI 不替人拍板、不自动放行。</div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- 同步源状态 -->
      <el-tab-pane label="同步源状态" name="sync">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>同步源状态 <el-tag size="small" type="info">搬运工具：同步后台</el-tag></span>
              <div class="src">
                <span class="srcinfo">源：<b>同步后台 API</b></span>
                <el-button size="small" @click="ElMessage.success('已刷新')">🔄 刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="syncSources" style="width: 100%">
            <el-table-column prop="name" label="同步源" width="140" />
            <el-table-column prop="dingtalk" label="钉钉位置" min-width="160">
              <template #default="{ row }"><span class="small">{{ row.dingtalk }}</span></template>
            </el-table-column>
            <el-table-column prop="target" label="目标库" width="140" />
            <el-table-column prop="docs" label="文档" width="80" align="center" />
            <el-table-column prop="lastSync" label="上次同步" width="110">
              <template #default="{ row }"><span class="mono">{{ row.lastSync }}</span></template>
            </el-table-column>
            <el-table-column prop="result" label="本次结果" width="140">
              <template #default="{ row }"><span class="small">{{ row.result }}</span></template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-tag :type="row.statusType as any">{{ row.status }}</el-tag></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 缺口与征集 -->
      <el-tab-pane label="缺口与征集" name="gap">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>知识缺口看板 <el-tag size="small" type="info">聚合自「无结果」问答，AI 判定缺口类型</el-tag></span>
              <div class="src">
                <span class="srcinfo">源：<b>多维表《缺口与征集》</b></span>
                <el-button size="small" @click="ElMessage.success('已刷新')">🔄 刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="gaps" style="width: 100%">
            <el-table-column prop="question" label="缺口问题" min-width="220" />
            <el-table-column prop="count" label="近30天" width="100" align="center" />
            <el-table-column label="AI 判定" width="180">
              <template #default="{ row }"><el-tag :type="row.judgeType as any">{{ row.aiJudge }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="owner" label="人裁决" width="160" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }"><el-tag :type="row.statusType as any">{{ row.status }}</el-tag></template>
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
.chain { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; background: #eef3ff; border: 1px dashed #c7d7fe; border-radius: 10px; padding: 8px 14px; font-size: 12.5px; color: #1e40af; margin-bottom: 16px; }
.chain .arr { color: #93b4f5; }
.hl { border-radius: 8px; padding: 10px 14px; font-size: 12.5px; margin-bottom: 14px; display: flex; gap: 8px; line-height: 1.7; }
.hl.blue { background: #eef3ff; border: 1px solid #c7d7fe; color: #1e40af; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.field-row { display: flex; gap: 8px; width: 100%; }
.field-row .el-input, .field-row .el-select { flex: 1; }
.upload-card :deep(.el-upload-dragger) { padding: 26px 20px; }
.upload-card .di { font-size: 30px; margin-bottom: 6px; }
.upload-card .dt { font-size: 14px; font-weight: 600; color: #334155; }
.upload-card .dt em { color: #2b6bff; font-style: normal; }
.upload-card .dd { font-size: 12px; color: #6b7280; margin-top: 6px; line-height: 1.8; }
.src { display: flex; align-items: center; gap: 8px; }
.srcinfo { font-size: 11px; color: #9ca3af; }
.srcinfo b { color: #64748b; }
.small { font-size: 12.5px; color: #475569; line-height: 1.8; }
.mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; }

.drop { border: 2px dashed #c3d3f5; border-radius: 14px; background: #f8faff; padding: 34px 20px; text-align: center; cursor: pointer; transition: .2s; }
.drop:hover { border-color: #2b6bff; background: #eef3ff; }
.drop .di { font-size: 30px; margin-bottom: 8px; }
.drop .dt { font-size: 14px; font-weight: 600; }
.drop .dd { font-size: 12px; color: #6b7280; margin-top: 6px; line-height: 1.8; }

.ai-check { border: 1px solid #e5e8ee; border-radius: 12px; margin-top: 14px; overflow: hidden; }
.ach { background: linear-gradient(90deg, #eef3ff, #f5f0ff); padding: 11px 16px; display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #4c3d99; }
.ckitem { padding: 13px 16px; border-bottom: 1px solid #f1f3f7; }
.ckitem:last-child { border-bottom: none; }
.ckitem.judged { opacity: .7; }
.ckh { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.ckb { font-size: 12.5px; color: #475569; line-height: 1.8; background: #f8fafc; border-radius: 8px; padding: 9px 12px; margin-bottom: 8px; }
.ckbtns { display: flex; gap: 8px; }
.ck-footer { padding: 12px 16px; background: #f8fafc; display: flex; align-items: center; gap: 10px; }

.dotlist { list-style: none; padding: 0; }
.dotlist li { padding: 7px 0; border-bottom: 1px dashed #eef1f5; font-size: 13px; display: flex; justify-content: space-between; gap: 10px; align-items: center; }
.dotlist li:last-child { border: none; }
</style>
