<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageContainer from '@/components/common/PageContainer.vue'
import {
  getSettings, setSetting, testLLM, listLlmModels, testDify, testMineru, testDingtalk,
  type SettingsResponse, type SettingItem,
  type TestLLMResult, type TestDifyResult, type TestMinerUResult, type TestDingtalkResult,
} from '@/api/settings'
import { listDifyProfiles, createDifyProfile, updateDifyProfile, deleteDifyProfile, enableDifyProfile, type DifyProfile } from '@/api/settings'
import {
  listLlmProfiles, createLlmProfile, updateLlmProfile, deleteLlmProfile, refreshLlmProfileModels,
  type LlmProfile, type LlmModelEntry,
} from '@/api/settings'
import { listDifyDatasets, type DifyDataset } from '@/api/dify'

// ============ 接入配置（功能性） ============
const EMPTY: SettingItem = { label: '', value: '', is_set: false, is_secret: false }
const form = ref<SettingsResponse>({
  llm_base_url: { ...EMPTY },
  llm_api_key: { ...EMPTY, is_secret: true },
  llm_model: { ...EMPTY },
  mineru_api_key: { ...EMPTY, is_secret: true },
  dify_base_url: { ...EMPTY },
  dify_api_key: { ...EMPTY, is_secret: true },
  dify_dataset_ids: { ...EMPTY },
  dingtalk_app_key: { ...EMPTY },
  dingtalk_app_secret: { ...EMPTY, is_secret: true },
  dingtalk_operator_union_id: { ...EMPTY },
})
const saving = ref<string | null>(null)
const activeTab = ref('access')

// ============ LLM 供应商配置（多供应商 × 多模型列表管理） ============
const llmProviderPresets = [
  { key: 'deepseek', name: 'DeepSeek', base: 'https://api.deepseek.com/v1', doc: 'https://platform.deepseek.com/api_keys' },
  { key: 'zhipu', name: 'GLM（智谱）', base: 'https://open.bigmodel.cn/api/paas/v4', doc: 'https://open.bigmodel.cn/usercenter/apikeys' },
  { key: 'custom', name: '自定义（OpenAI 兼容）', base: '', doc: '' },
]

function providerLabel(key: string) {
  return llmProviderPresets.find((p) => p.key === key)?.name || key
}

const llmProfiles = ref<LlmProfile[]>([])
const llmLoading = ref(false)

async function loadLlmProfiles() {
  llmLoading.value = true
  try {
    llmProfiles.value = await listLlmProfiles()
  } finally {
    llmLoading.value = false
  }
}

const llmDlg = ref({
  visible: false,
  editingId: '',
  name: '',
  provider: 'deepseek',
  base_url: '',
  api_key: '',
  has_key: false,
  models: [] as LlmModelEntry[],
  fetching: false,
  testing: false,
  saving: false,
  testResult: null as TestLLMResult | null,
})

const llmDocLink = computed(() => llmProviderPresets.find((p) => p.key === llmDlg.value.provider)?.doc || '')

function openLlmCreate() {
  llmDlg.value = {
    visible: true, editingId: '', name: '', provider: 'deepseek',
    base_url: llmProviderPresets[0].base, api_key: '', has_key: false, models: [],
    fetching: false, testing: false, saving: false, testResult: null,
  }
}

function openLlmEdit(p: LlmProfile) {
  const preset = llmProviderPresets.find((x) => x.key === p.provider)
  llmDlg.value = {
    visible: true, editingId: p.id, name: p.name, provider: p.provider,
    base_url: p.base_url || preset?.base || '', api_key: '', has_key: p.has_key,
    models: p.models.map((m) => ({ ...m })),
    fetching: false, testing: false, saving: false, testResult: null,
  }
}

function onProviderChange(key: string) {
  const preset = llmProviderPresets.find((x) => x.key === key)
  if (preset && !llmDlg.value.editingId) {
    llmDlg.value.base_url = preset.base
    if (!llmDlg.value.name.trim()) llmDlg.value.name = preset.name
  }
}

// 拉取模型：编辑态且未填新 Key → 用已存 Key 调 refresh；否则用弹窗内 Key 实时拉取
async function fetchLlmModels() {
  const d = llmDlg.value
  if (!d.base_url.trim()) {
    ElMessage.warning('请先填写 API Base URL')
    return
  }
  d.fetching = true
  try {
    const newKey = d.api_key.trim()
    if (d.editingId && !newKey) {
      const res = await refreshLlmProfileModels(d.editingId)
      d.models = res.models || []
      await loadLlmProfiles()
    } else {
      const res = await listLlmModels({ base_url: d.base_url, api_key: newKey })
      const existing = new Map(d.models.map((m) => [m.name, m]))
      d.models = (res.models || []).map((name) => existing.get(name) || { name, enabled: false, is_default: false })
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '拉取模型失败')
  } finally {
    d.fetching = false
  }
}

async function testLlmDlg() {
  const d = llmDlg.value
  d.testResult = null
  d.testing = true
  try {
    d.testResult = await testLLM({
      base_url: d.base_url,
      api_key: d.api_key,
      model: d.models.find((m) => m.enabled)?.name || '',
    })
  } catch (e: any) {
    d.testResult = { ok: false, message: e?.message || '请求失败' }
  } finally {
    d.testing = false
  }
}

// 默认开关互斥（本配置内）；默认模型必须生效；跨配置互斥由后端保证
function onDefaultToggle(m: LlmModelEntry) {
  if (m.is_default) {
    for (const x of llmDlg.value.models) if (x !== m) x.is_default = false
    m.enabled = true
  }
}

async function saveLlmProfile() {
  const d = llmDlg.value
  if (!d.name.trim()) return ElMessage.warning('请填写配置名称')
  if (!d.base_url.trim()) return ElMessage.warning('请填写 API Base URL')
  if (!d.editingId && !d.api_key.trim()) return ElMessage.warning('请填写 API Key')
  if (!d.models.some((m) => m.enabled)) return ElMessage.warning('请至少勾选一个生效模型')
  d.saving = true
  try {
    const payload = {
      name: d.name.trim(),
      provider: d.provider,
      base_url: d.base_url.trim(),
      api_key: d.api_key.trim(),
      models: d.models,
    }
    if (d.editingId) await updateLlmProfile(d.editingId, payload)
    else await createLlmProfile(payload)
    ElMessage.success('模型配置已保存')
    d.visible = false
    await loadLlmProfiles()
  } finally {
    d.saving = false
  }
}

async function removeLlmProfile(p: LlmProfile) {
  await ElMessageBox.confirm(`确定删除模型配置「${p.name}」？该配置下的模型选项将同步移除。`, '删除确认', { type: 'warning' })
  await deleteLlmProfile(p.id)
  ElMessage.success('已删除')
  await loadLlmProfiles()
}

// Dify 数据集
const datasets = ref<DifyDataset[]>([])
const loadingDatasets = ref(false)
const datasetsError = ref('')

onMounted(async () => {
  form.value = await getSettings()
  await loadProfiles()
  await loadLlmProfiles()
  const active = profiles.value.find((p) => p.enabled)
  if (active) {
    await loadDatasets()
  }
})

async function save(k: string) {
  const item = form.value[k]
  if (!item) return
  if (item.is_secret && item.is_set && (!item.value || item.value.includes('****'))) {
    ElMessage.info('未填写新值，保留已配置的密钥')
    return
  }
  saving.value = k
  try {
    await setSetting({ key: k, value: item.value })
    form.value = await getSettings()
    ElMessage.success('已保存')
  } finally {
    saving.value = null
  }
}

async function loadDatasets() {
  loadingDatasets.value = true
  datasetsError.value = ''
  try {
    const res = await listDifyDatasets()
    datasets.value = res.items || []
    if (res.error) datasetsError.value = res.error
  } catch (e: any) {
    datasetsError.value = e?.message || '加载失败'
    datasets.value = []
  } finally {
    loadingDatasets.value = false
  }
}

function pickDatasetIds() {
  const ids = datasets.value.map((d) => d.id).join(',')
  if (editingProfile.value) editingProfile.value.dataset_ids = ids
  ElMessage.success(`已填入 ${datasets.value.length} 个数据集 ID`)
}

// ============ Dify 多配置（多条只能生效一条） ============
const profiles = ref<DifyProfile[]>([])
const profileDialogVisible = ref(false)
const savingProfile = ref(false)
const editingProfile = ref<{ id: string | null; name: string; base_url: string; api_key: string; dataset_ids: string }>({
  id: null, name: '', base_url: '', api_key: '', dataset_ids: '',
})

async function loadProfiles() {
  try {
    profiles.value = await listDifyProfiles()
  } catch {
    profiles.value = []
  }
}

function openProfileDialog(row?: Partial<DifyProfile> & { id?: string }) {
  if (row) {
    editingProfile.value = {
      id: row.id ?? null, name: row.name ?? '', base_url: row.base_url ?? '',
      api_key: '', dataset_ids: row.dataset_ids ?? '',
    }
  } else {
    editingProfile.value = { id: null, name: '', base_url: '', api_key: '', dataset_ids: '' }
  }
  profileDialogVisible.value = true
}

async function saveProfile() {
  if (!editingProfile.value.name.trim()) {
    ElMessage.warning('请填写配置名称')
    return
  }
  savingProfile.value = true
  try {
    const data = {
      name: editingProfile.value.name,
      base_url: editingProfile.value.base_url,
      api_key: editingProfile.value.api_key,
      dataset_ids: editingProfile.value.dataset_ids,
    }
    if (editingProfile.value.id) {
      await updateDifyProfile(editingProfile.value.id, data)
      ElMessage.success('配置已更新')
    } else {
      await createDifyProfile(data)
      ElMessage.success('配置已创建')
    }
    profileDialogVisible.value = false
    await loadProfiles()
  } finally {
    savingProfile.value = false
  }
}

async function removeProfile(id: string) {
  await ElMessageBox.confirm('确认删除该配置？', '提示', { type: 'warning' })
  await deleteDifyProfile(id)
  ElMessage.success('已删除')
  await loadProfiles()
}

// 配置弹窗内连通性测试（编辑态 Key 为掩码时由后端回退已存 Key）
const profileTest = ref({ testing: false, result: null as TestDifyResult | null })

async function runProfileTest() {
  profileTest.value.result = null
  profileTest.value.testing = true
  try {
    profileTest.value.result = await testDify({
      base_url: editingProfile.value.base_url,
      api_key: editingProfile.value.api_key,
      profile_id: editingProfile.value.id || '',
    })
  } catch (e: any) {
    profileTest.value.result = { ok: false, message: e?.message || '请求失败' }
  } finally {
    profileTest.value.testing = false
  }
}

async function enableProfile(id: string) {
  await enableDifyProfile(id)
  ElMessage.success('已切换生效配置')
  await loadProfiles()
  await loadDatasets()
}

// ============ 钉钉配置（弹窗配置 + 连通性测试） ============
const dingtalkConfigured = computed(() =>
  !!(form.value.dingtalk_app_key?.is_set && form.value.dingtalk_app_secret?.is_set && form.value.dingtalk_operator_union_id?.is_set))

const dtModal = ref({
  visible: false,
  app_key: '', app_secret: '', operator_union_id: '',
  testing: false, saving: false,
  testResult: null as TestDingtalkResult | null,
})

function openDingtalkModal() {
  dtModal.value = {
    visible: true,
    // Secret 不回显；其余回显已存值
    app_key: form.value.dingtalk_app_key?.value || '',
    app_secret: '',
    operator_union_id: form.value.dingtalk_operator_union_id?.value || '',
    testing: false, saving: false, testResult: null,
  }
}

async function runDingtalkTest() {
  dtModal.value.testResult = null
  dtModal.value.testing = true
  try {
    dtModal.value.testResult = await testDingtalk({
      app_key: dtModal.value.app_key,
      app_secret: dtModal.value.app_secret,
      operator_union_id: dtModal.value.operator_union_id,
    })
  } catch (e: any) {
    dtModal.value.testResult = { ok: false, message: e?.message || '请求失败' }
  } finally {
    dtModal.value.testing = false
  }
}

async function saveDingtalkModal() {
  // Dify 风格：保存前先验证连通性，失败则不落库
  await runDingtalkTest()
  if (!dtModal.value.testResult?.ok) return
  dtModal.value.saving = true
  try {
    const m = dtModal.value
    const items: Array<[string, string]> = [
      ['dingtalk_app_key', m.app_key.trim()],
      ['dingtalk_operator_union_id', m.operator_union_id.trim()],
    ]
    // Secret 已配置但弹窗留空 → 跳过，避免空值清掉已存 Secret
    if (!(form.value.dingtalk_app_secret?.is_set && !m.app_secret)) items.push(['dingtalk_app_secret', m.app_secret.trim()])
    for (const [k, v] of items) await setSetting({ key: k, value: v })
    form.value = await getSettings()
    ElMessage.success('钉钉配置已保存')
    dtModal.value.visible = false
  } finally {
    dtModal.value.saving = false
  }
}

const mineruTest = ref({ testing: false, result: null as TestMinerUResult | null })

async function runMineruTest() {
  mineruTest.value.result = null
  mineruTest.value.testing = true
  try {
    mineruTest.value.result = await testMineru({ api_key: (form.value.mineru_api_key?.value || '').includes('****') ? '' : form.value.mineru_api_key?.value })
  } catch (e: any) {
    mineruTest.value.result = { ok: false, message: e?.message || '请求失败' }
  } finally {
    mineruTest.value.testing = false
  }
}

// ============ 节点 → 模型绑定（原型展示） ============
const bindings = [
  { node: '智能问答（首页）', model: '千问-Max', temp: '0.3', structured: false, promptKey: '' },
  { node: '上传前命名校验', model: 'DeepSeek-V3', temp: '0', structured: true, promptKey: 'p1' },
  { node: '元数据推荐/打标', model: 'GLM-4', temp: '0', structured: true, promptKey: 'p2' },
  { node: '摘要/图注生成', model: '千问-Max', temp: '0.2', structured: false, promptKey: 'p3' },
  { node: '工单智能分诊', model: '千问-Max', temp: '0', structured: true, promptKey: 'p4' },
  { node: '巡检归档建议', model: 'DeepSeek-V3', temp: '0', structured: true, promptKey: 'p5' },
]

const prompts: Record<string, { title: string; sub: string; body: string }> = {
  p1: { title: '上传前命名校验 · 提示词全文', sub: '绑定模型：DeepSeek-V3 · temperature=0 · 结构化输出开启', body: '你是企业知识库的文档命名校验器。根据命名规范判断文件名是否合规，并给出改名建议。\n\n【命名规范】\n<机型|产品线>_<文档类型>_<主题>_<版本号>.<扩展名>\n示例：JK-8669D_检验规程_金加工过程_V3.docx\n\n【输入】\n文件名：{filename}\n文档前 500 字摘要：{doc_summary}\n\n【任务】\n1. 判断文件名是否符合规范\n2. 不合规时给出建议文件名\n3. 输出判断依据\n\n【输出 JSON】\n{ "compliant": true/false, "suggested_name": "", "machine_model_detected": "", "reason": "", "confidence": 0~1 }' },
  p2: { title: '元数据推荐与打标 · 提示词全文', sub: '绑定模型：GLM-4 · temperature=0 · 结构化输出开启', body: '你是知识库元数据标注助手。为文档推荐元数据与标签，供人工确认。\n\n【标签词表】\n机型：{机型词表}；流程域：{流程域词表}；知识类型：制度/规程/手册/FAQ/案例/标准；密级：公开/内部/秘密\n\n【规则】\n1. 只能从系统标签词表中选择标签\n2. 含商务条款/价格→内部及以上；含技术参数→至少内部\n3. 自定义标签须标注 suggested_custom=true\n\n【输出 JSON】\n{ "classification": {...}, "system_tags": [...], "custom_tags": [...], "confidence": 0~1 }' },
  p3: { title: '摘要与图注生成 · 提示词全文', sub: '绑定模型：千问-Max · temperature=0.2', body: '你是知识加工流水线的增强节点，负责：\n\n【任务A：文档/章节摘要】\n为文档生成 ≤100 字文档级摘要；为每个一级章节生成 ≤50 字章节级摘要。\n\n【任务B：图片描述】\n输入：图片 + 所在章节上下文。\n输出 ≤60 字描述：图的内容、量程/参数、在工序中的作用。\n\n【输出 JSON】\n{ "doc_summary": "", "section_summaries": [...], "image_captions": [...] }' },
  p4: { title: '工单智能分诊 · 提示词全文', sub: '绑定模型：千问-Max · temperature=0 · 置信度<0.7 转人工', body: '你是知识治理平台的反馈工单分诊助手。根据用户反馈判定根因并给出处置建议。\n\n【根因枚举】\nknowledge_gap=知识缺口 | version_conflict=版本冲突 | bad_chunking=分段劣化 | no_permission=权限 | model_error=模型错误 | content_error=源文档错误\n\n【处置枚举】\nsolicit=发起征集 | reprocess=回流重加工 | fix_doc=修正源文档 | answer_correction=答案纠偏\n\n【输出 JSON】\n{ "root_cause": "", "severity": "high|medium|low", "action": "", "suggested_owner_role": "", "evidence": "", "confidence": 0~1 }\n\n【约束】confidence < 0.7 时输出 root_cause="uncertain"' },
  p5: { title: '巡检归档建议 · 提示词全文', sub: '绑定模型：DeepSeek-V3 · temperature=0', body: '你是知识生命周期巡检助手。对"90天零引用"文档逐一给出处置建议。\n\n【判断规则】\n1. 制度/标准类：建议复审（不归档）\n2. 活动记录/草稿类：建议归档\n3. 同目录新版本存在：建议归档并声明被取代\n4. 无法判断时输出 review\n\n【输出 JSON】\n{ "docs": [{"doc_id":"","advice":"archive|keep|review","reason":""}] }' },
}

const usage = [
  { model: '千问-Max', calls: '4.2 万次', purpose: '问答 · 摘要 · 分诊', trend: '+12%（随问答量增长）', type: 'up' },
  { model: 'GLM-4（网关）', calls: '1.8 万次', purpose: '打标 · 元数据', trend: '0（自部署）', type: '' },
  { model: 'DeepSeek-V3', calls: '0.9 万次', purpose: '命名校验 · 巡检建议', trend: '稳定', type: '' },
]

const promptVisible = ref(false)
const currentPrompt = ref<{ title: string; sub: string; body: string } | null>(null)

function openPrompt(key: string) {
  currentPrompt.value = prompts[key]
  promptVisible.value = true
}
</script>

<template>
  <PageContainer title="系统配置">
    <p class="pg-sub">智能体的大脑与全链路 AI 节点的模型管理：问答模型可选可换，判定类节点（分诊/质检/命名校验/打标）绑定低温度模型并开启结构化输出。</p>

    <el-tabs v-model="activeTab">
      <!-- ============ 接入配置（真实表单） ============ -->
      <el-tab-pane label="接入配置" name="access">
        <el-form label-width="140px">
          <el-divider content-position="left">LLM 大模型</el-divider>
          <el-form-item label="模型管理">
            <div class="profile-box">
              <div class="profile-toolbar">
                <el-button type="primary" size="small" @click="openLlmCreate">+ 新增模型配置</el-button>
              </div>
              <el-table :data="llmProfiles" size="small" v-loading="llmLoading" style="margin-top: 8px" empty-text="暂无模型配置，点击「新增模型配置」">
                <el-table-column label="名称" min-width="150">
                  <template #default="{ row }">
                    <b>{{ row.name }}</b>
                    <el-tag size="small" effect="plain" style="margin-left: 6px">{{ providerLabel(row.provider) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="base_url" label="API 端点" min-width="170" show-overflow-tooltip />
                <el-table-column label="API Key" width="110">
                  <template #default="{ row }">
                    <span class="mono">{{ row.has_key ? row.api_key : '未配置' }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="生效模型" min-width="220">
                  <template #default="{ row }">
                    <template v-if="row.models?.length">
                      <el-tag
                        v-for="m in row.models.filter((x: LlmModelEntry) => x.enabled)"
                        :key="m.name"
                        size="small"
                        :type="m.is_default ? 'primary' : 'info'"
                        effect="light"
                        style="margin: 2px"
                      >
                        {{ m.name }}<span v-if="m.is_default"> · 默认</span>
                      </el-tag>
                      <span v-if="!row.models.some((x: LlmModelEntry) => x.enabled)" class="field-hint">无生效模型</span>
                    </template>
                    <span v-else class="field-hint">未拉取模型</span>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="110">
                  <template #default="{ row }">
                    <el-button type="primary" link size="small" @click="openLlmEdit(row as LlmProfile)">编辑</el-button>
                    <el-button type="danger" link size="small" @click="removeLlmProfile(row as LlmProfile)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div class="field-hint" style="margin-top: 6px">
                勾选「生效」的模型会出现在智能问答的模型选项中；「默认」模型为新会话默认使用，全局唯一。
              </div>
            </div>
          </el-form-item>

          <el-divider content-position="left">Dify 知识库（智能问答 Agent）</el-divider>
          <el-form-item label="配置列表">
            <div class="profile-box">
              <div class="profile-toolbar">
                <el-button size="small" type="primary" @click="openProfileDialog()">+ 新增配置</el-button>
                <el-button size="small" :loading="loadingDatasets" @click="loadDatasets">🔄 拉取数据集列表</el-button>
                <span v-if="datasetsError" class="err">{{ datasetsError }}</span>
              </div>
              <el-table v-if="profiles.length" :data="profiles" size="small" style="margin-top: 8px">
                <el-table-column label="生效" width="70">
                  <template #default="{ row }">
                    <el-radio :model-value="row.enabled" @change="enableProfile(row.id)">&nbsp;</el-radio>
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" min-width="120" />
                <el-table-column prop="base_url" label="服务地址" min-width="160" />
                <el-table-column label="API Key" min-width="140">
                  <template #default="{ row }">
                    <span v-if="row.api_key" class="mono">{{ row.api_key }}</span>
                    <span v-else class="muted">未设置</span>
                  </template>
                </el-table-column>
                <el-table-column prop="dataset_ids" label="数据集 ID" min-width="160" />
                <el-table-column label="操作" width="120">
                  <template #default="{ row }">
                    <el-button size="small" link type="primary" @click="openProfileDialog(row)">编辑</el-button>
                    <el-button size="small" link type="danger" @click="removeProfile(row.id)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div v-else class="empty">尚无配置，请点击「新增配置」添加 Dify 实例。</div>
              <div class="field-hint" style="margin-top: 6px">启用某条配置后，该配置的服务地址、API Key、数据集 ID 会同步为系统生效值。只能生效一条。</div>

              <!-- 数据集列表（启用配置的） -->
              <template v-if="datasets.length">
                <div class="ds-section-title">数据集列表（当前生效配置）</div>
                <el-table :data="datasets" size="small" style="margin-top: 4px">
                  <el-table-column prop="name" label="名称" min-width="160" />
                  <el-table-column prop="document_count" label="文档数" width="90" />
                  <el-table-column prop="word_count" label="字数" width="120" />
                  <el-table-column prop="id" label="ID" min-width="200">
                    <template #default="{ row }"><span class="mono">{{ row.id }}</span></template>
                  </el-table-column>
                </el-table>
                <el-button size="small" type="primary" plain style="margin-top: 6px" @click="pickDatasetIds">填入全部 ID 到编辑框</el-button>
              </template>
            </div>
          </el-form-item>

          <el-divider content-position="left">文档解析</el-divider>
          <el-form-item label="MinerU API Key">
            <div class="field-row">
              <el-input v-model="form.mineru_api_key.value" show-password placeholder="未设置" />
              <el-button type="primary" :loading="saving === 'mineru_api_key'" @click="save('mineru_api_key')">保存</el-button>
            </div>
            <div class="field-row" style="margin-top: 8px">
              <el-button :loading="mineruTest.testing" @click="runMineruTest">测试连通性</el-button>
            </div>
            <el-alert
              v-if="mineruTest.result?.ok"
              type="success"
              :closable="false"
              show-icon
              style="margin-top: 8px"
              :title="`连接成功 · ${mineruTest.result.latency_ms}ms · ${mineruTest.result.message}`"
            />
            <el-alert
              v-else-if="mineruTest.result && !mineruTest.result.ok"
              type="error"
              :closable="false"
              show-icon
              style="margin-top: 8px"
              :title="mineruTest.result.message || '连接失败'"
            />
            <div class="field-hint">配置 Key 后支持 PDF/Word/Excel/HTML 云解析；留空则仅 txt/md/csv。</div>
          </el-form-item>

          <el-divider content-position="left">钉钉（企业知识库数据源）</el-divider>
          <!-- 配置结果展示：具体凭证在弹窗中配置，Secret 脱敏 -->
          <el-form-item label="配置状态">
            <div class="dt-result" :class="{ ok: dingtalkConfigured }">
              <div class="dt-row">
                <span class="dt-label">状态</span>
                <el-tag :type="dingtalkConfigured ? 'success' : 'info'" size="small" effect="light">
                  {{ dingtalkConfigured ? '已配置' : '未配置' }}
                </el-tag>
              </div>
              <div class="dt-row">
                <span class="dt-label">AppKey</span>
                <span class="mono">{{ form.dingtalk_app_key?.is_set ? form.dingtalk_app_key.value : '未配置' }}</span>
              </div>
              <div class="dt-row">
                <span class="dt-label">AppSecret</span>
                <span class="mono">{{ form.dingtalk_app_secret?.is_set ? '••••••••（已配置，不显示）' : '未配置' }}</span>
              </div>
              <div class="dt-row">
                <span class="dt-label">操作人 UnionId</span>
                <span class="mono">{{ form.dingtalk_operator_union_id?.is_set ? form.dingtalk_operator_union_id.value : '未配置' }}</span>
              </div>
              <div class="dt-row dt-foot">
                <span class="field-hint">运营看板的"企业知识"指标来源于此用户可见的钉钉知识库；需授予应用「知识库读权限」。</span>
                <el-button type="primary" size="small" @click="openDingtalkModal">{{ dingtalkConfigured ? '修改配置' : '配置' }}</el-button>
              </div>
            </div>
          </el-form-item>

          <el-alert type="info" :closable="false" title="向量模型 BGE-M3 与重排模型 BGE-reranker 本地部署，无需配置。" style="margin-top: 12px;" />
        </el-form>
      </el-tab-pane>

      <!-- ============ 节点 → 模型绑定（原型展示） ============ -->
      <el-tab-pane label="节点 → 模型绑定" name="binding">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>节点 → 模型绑定 <el-tag size="small" type="primary">判定类 temperature=0</el-tag></span>
            </div>
          </template>
          <el-table :data="bindings" style="width: 100%">
            <el-table-column prop="node" label="链路节点" min-width="150" />
            <el-table-column prop="model" label="绑定模型" width="110" />
            <el-table-column prop="temp" label="temp" width="60">
              <template #default="{ row }"><span class="mono">{{ row.temp }}</span></template>
            </el-table-column>
            <el-table-column label="结构化输出" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.structured" type="success" size="small">开</el-tag>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="提示词" width="80">
              <template #default="{ row }">
                <el-button v-if="row.promptKey" size="small" link type="primary" @click="openPrompt(row.promptKey)">查看</el-button>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============ 用量与成本（原型展示） ============ -->
      <el-tab-pane label="用量与成本" name="usage">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>用量与成本（本月）</span>
              <el-button size="small" @click="ElMessage.success('已刷新')">🔄 刷新</el-button>
            </div>
          </template>
          <el-table :data="usage" style="width: 100%">
            <el-table-column prop="model" label="模型" width="140" />
            <el-table-column prop="calls" label="调用量" width="120" />
            <el-table-column prop="purpose" label="主要用途" min-width="200">
              <template #default="{ row }"><span class="small">{{ row.purpose }}</span></template>
            </el-table-column>
            <el-table-column label="成本趋势" min-width="200">
              <template #default="{ row }"><span class="small" :class="row.type">{{ row.trend }}</span></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 提示词弹窗 -->
    <el-dialog v-model="promptVisible" :title="currentPrompt?.title" width="720px">
      <div class="sub">{{ currentPrompt?.sub }}</div>
      <pre class="promptbox">{{ currentPrompt?.body }}</pre>
      <template #footer>
        <el-button @click="promptVisible = false">关闭</el-button>
        <el-button type="primary" @click="ElMessage.success('提示词已保存（原型演示）'); promptVisible = false">保存</el-button>
      </template>
    </el-dialog>

    <!-- LLM 模型配置弹窗：供应商 → Key → 拉取模型 → 复选框勾选生效/默认 -->
    <el-dialog v-model="llmDlg.visible" :title="llmDlg.editingId ? '编辑模型配置' : '新增模型配置'" width="640px" destroy-on-close>
      <el-form label-position="top" @submit.prevent>
        <el-form-item required label="模型供应商">
          <el-select v-model="llmDlg.provider" style="width: 100%" :disabled="!!llmDlg.editingId" @change="onProviderChange">
            <el-option v-for="p in llmProviderPresets" :key="p.key" :label="p.name" :value="p.key" />
          </el-select>
        </el-form-item>
        <el-form-item required label="配置名称">
          <el-input v-model="llmDlg.name" placeholder="如：DeepSeek 生产环境" />
        </el-form-item>
        <el-form-item required label="API Base URL">
          <el-input v-model="llmDlg.base_url" placeholder="https://api.deepseek.com/v1" />
        </el-form-item>
        <el-form-item :required="!llmDlg.editingId" label="API Key">
          <el-input v-model="llmDlg.api_key" show-password :placeholder="llmDlg.has_key ? '••••••••' : '在此输入您的 API Key'" />
          <div v-if="llmDlg.editingId" class="field-hint">留空表示不修改已保存的 Key</div>
        </el-form-item>
        <div class="dlg-actions">
          <el-button size="small" type="primary" plain :loading="llmDlg.fetching" @click="fetchLlmModels">拉取模型列表</el-button>
          <a v-if="llmDocLink" :href="llmDocLink" target="_blank" class="doc-link">获取 API Key ↗</a>
        </div>
        <el-alert
          v-if="llmDlg.testResult?.ok"
          type="success" :closable="false" show-icon style="margin-top: 8px"
          :title="`连接成功 · ${llmDlg.testResult.latency_ms}ms · 模型回复：${(llmDlg.testResult.reply || '').slice(0, 50)}`"
        />
        <el-alert
          v-else-if="llmDlg.testResult && !llmDlg.testResult.ok"
          type="error" :closable="false" show-icon style="margin-top: 8px"
          :title="llmDlg.testResult.message || '连接失败'"
        />
        <el-form-item v-if="llmDlg.models.length" label="可用模型（复选框=生效出现在问答选项；开关=设为新会话默认）" style="margin-top: 12px">
          <div class="model-pick-list">
            <div v-for="m in llmDlg.models" :key="m.name" class="mpl-row">
              <el-checkbox
                v-model="m.enabled"
                @change="(v: any) => { if (!v) m.is_default = false }"
              >{{ m.name }}</el-checkbox>
              <el-switch
                v-model="m.is_default"
                :disabled="!m.enabled"
                active-text="默认"
                inline-prompt
                @change="() => onDefaultToggle(m)"
              />
            </div>
          </div>
        </el-form-item>
        <div v-else class="field-hint" style="margin-top: 8px">填写 API Base URL 与 Key 后，点击「拉取模型列表」加载该供应商的推理模型。</div>
      </el-form>
      <template #footer>
        <el-button :loading="llmDlg.testing" @click="testLlmDlg">测试连通性</el-button>
        <el-button @click="llmDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="llmDlg.saving" @click="saveLlmProfile">保存</el-button>
      </template>
    </el-dialog>

    <!-- Dify 配置编辑弹窗 -->
    <el-dialog v-model="profileDialogVisible" :title="editingProfile.id ? '编辑配置' : '新增配置'" width="520px">
      <el-form label-width="120px" @submit.prevent>
        <el-form-item label="配置名称">
          <el-input v-model="editingProfile.name" placeholder="如：生产环境 / 测试环境" />
        </el-form-item>
        <el-form-item label="API 端点">
          <el-input v-model="editingProfile.base_url" placeholder="http://127.0.0.1:8088/v1" />
          <div class="field-hint">Dify 知识库 Service API 端点，需含端口与 /v1，例如 http://127.0.0.1:8088/v1 或 https://dify.example.com/v1</div>
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="editingProfile.api_key" show-password :placeholder="editingProfile.id ? '••••••••' : 'Dataset API Key，如 dataset-R6qPqf7CfPC0Dbn6uT3LxIKw'" />
        </el-form-item>
        <el-form-item label="数据集 ID">
          <el-input v-model="editingProfile.dataset_ids" placeholder="数据集 ID，逗号分隔" />
          <div class="field-hint">可先启用此配置后在上方「拉取数据集列表」并「填入全部 ID」</div>
        </el-form-item>
        <el-alert
          v-if="profileTest.result?.ok"
          type="success"
          :closable="false"
          show-icon
          :title="`连接成功 · ${profileTest.result.latency_ms}ms · ${profileTest.result.message}`"
        />
        <el-alert
          v-else-if="profileTest.result && !profileTest.result.ok"
          type="error"
          :closable="false"
          show-icon
          :title="profileTest.result.message || '连接失败'"
        />
      </el-form>
      <template #footer>
        <el-button :loading="profileTest.testing" @click="runProfileTest">测试连通性</el-button>
        <el-button @click="profileDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingProfile" @click="saveProfile">保存</el-button>
      </template>
    </el-dialog>

    <!-- 钉钉配置弹窗（AppKey / AppSecret / UnionId + 连通性测试） -->
    <el-dialog v-model="dtModal.visible" title="配置钉钉（企业知识库数据源）" width="520px" destroy-on-close>
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="AppKey">
          <el-input v-model="dtModal.app_key" placeholder="钉钉开放平台应用 AppKey" />
        </el-form-item>
        <el-form-item label="AppSecret">
          <el-input
            v-model="dtModal.app_secret"
            show-password
            :placeholder="form.dingtalk_app_secret?.is_set ? '••••••••' : '钉钉开放平台应用 AppSecret'"
          />
        </el-form-item>
        <el-form-item label="操作人 UnionId">
          <el-input v-model="dtModal.operator_union_id" placeholder="具备知识库读权限的用户 UnionId" />
        </el-form-item>
        <el-alert
          v-if="dtModal.testResult?.ok"
          type="success"
          :closable="false"
          show-icon
        >
          <template #title>
            连接成功 · {{ dtModal.testResult.latency_ms }}ms · {{ dtModal.testResult.message }}
          </template>
        </el-alert>
        <el-alert
          v-else-if="dtModal.testResult && !dtModal.testResult.ok"
          type="error"
          :closable="false"
          show-icon
          :title="dtModal.testResult.message || '连接失败'"
        />
      </el-form>
      <template #footer>
        <el-button :loading="dtModal.testing" @click="runDingtalkTest">测试连通性</el-button>
        <el-button type="primary" :loading="dtModal.saving" @click="saveDingtalkModal">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<style scoped>
.pg-sub { color: #6b7280; font-size: 13px; margin-bottom: 16px; line-height: 1.8; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.field-row { display: flex; gap: 8px; width: 100%; }
.field-row .el-input { flex: 1; }
.field-hint { font-size: 12px; color: #909399; margin-top: 4px; }
.dataset-box { width: 100%; }
.dlg-actions { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.model-pick-list { width: 100%; border: 1px solid #e4e7ed; border-radius: 8px; padding: 6px 12px; max-height: 240px; overflow-y: auto; }
.mpl-row { display: flex; align-items: center; justify-content: space-between; padding: 4px 0; border-bottom: 1px dashed #ebeef5; }
.mpl-row:last-child { border-bottom: none; }
.doc-link { color: #409eff; font-size: 13px; text-decoration: none; }
.doc-link:hover { text-decoration: underline; }
.dt-result { width: 100%; border: 1px solid #e4e7ed; border-radius: 10px; padding: 12px 16px; background: #fafbfc; }
.dt-result.ok { border-color: #b3e19d; background: #f7fbf5; }
.dt-row { display: flex; align-items: center; gap: 12px; padding: 4px 0; font-size: 13px; }
.dt-label { width: 120px; color: #909399; flex-shrink: 0; }
.dt-foot { justify-content: space-between; margin-top: 6px; padding-top: 8px; border-top: 1px dashed #e4e7ed; }
.dataset-box { width: 100%; }
.dataset-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.empty { font-size: 12.5px; color: #909399; margin-top: 8px; }
.profile-box { width: 100%; }
.profile-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ds-section-title { font-size: 13px; font-weight: 600; color: #303133; margin-top: 12px; }
.err { font-size: 12px; color: #f56c6c; }
.small { font-size: 12.5px; color: #475569; line-height: 1.8; }
.small.up { color: #16a34a; }
.muted { color: #9ca3af; font-size: 12px; }
.mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #334155; }
.sub { color: #6b7280; font-size: 12.5px; margin-bottom: 12px; }
.promptbox { background: #0f172a; color: #dbeafe; border-radius: 10px; padding: 14px 16px; font-family: ui-monospace, Menlo, monospace; font-size: 12px; line-height: 1.8; white-space: pre-wrap; max-height: 340px; overflow-y: auto; margin: 0; }
</style>
