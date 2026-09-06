<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import PageContainer from '@/components/common/PageContainer.vue'
import { getSettings, setSetting, testLLM, type SettingsResponse, type SettingItem, type TestLLMResult } from '@/api/settings'
import { listDifyDatasets, type DifyDataset } from '@/api/dify'

// 预填占位项，保证模板中 v-model="form.xxx.value" 在 onMounted 加载前即为可赋值目标
const EMPTY: SettingItem = { label: '', value: '', is_set: false, is_secret: false }
const form = ref<SettingsResponse>({
  llm_base_url: { ...EMPTY },
  llm_api_key: { ...EMPTY, is_secret: true },
  llm_model: { ...EMPTY },
  mineru_api_key: { ...EMPTY, is_secret: true },
  dify_base_url: { ...EMPTY },
  dify_api_key: { ...EMPTY, is_secret: true },
  dify_dataset_ids: { ...EMPTY },
})
const saving = ref<string | null>(null)

// Dify 数据集
const datasets = ref<DifyDataset[]>([])
const loadingDatasets = ref(false)
const datasetsError = ref('')

// ---- 模型供应商（Dify 风格卡片，弹窗内配置 + 连通性测试） ----
interface Provider { key: string; label: string; short: string; color: string; url: string; model: string; desc: string }
const providers: Provider[] = [
  { key: 'glm', label: 'GLM (智谱)', short: 'GLM', color: '#3859ff', url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash', desc: 'glm-4-flash 免费额度可用' },
  { key: 'deepseek', label: 'DeepSeek', short: 'DS', color: '#4d6bfe', url: 'https://api.deepseek.com/v1', model: 'deepseek-chat', desc: 'OpenAI 兼容接口' },
  { key: 'custom', label: '自定义模型', short: '···', color: '#64748b', url: '', model: '', desc: '任意 OpenAI API 兼容服务' },
]
const currentProvider = computed(() => providers.find((p) => p.key === modal.value.providerKey) || providers[0])

// 当前使用中的供应商：以已保存的服务地址匹配预设
const activeProviderKey = computed(() => {
  const cur = (form.value.llm_base_url?.value || '').replace(/\/+$/, '')
  if (!cur) return ''
  const hit = providers.find((p) => p.url && p.url.replace(/\/+$/, '') === cur)
  return hit ? hit.key : 'custom'
})
const llmConfigured = computed(() => !!form.value.llm_api_key?.is_set)

const modal = ref({
  visible: false, providerKey: 'glm',
  base_url: '', api_key: '', model: '',
  testing: false, saving: false,
  testResult: null as TestLLMResult | null,
})

function openModal(p: Provider) {
  const isActive = activeProviderKey.value === p.key
  modal.value = {
    visible: true, providerKey: p.key,
    // 使用中的供应商回显已存值，其余用预设填充；Key 永不回显
    base_url: isActive ? form.value.llm_base_url?.value || p.url : p.url,
    api_key: '',
    model: isActive ? form.value.llm_model?.value || p.model : p.model,
    testing: false, saving: false, testResult: null,
  }
}

async function runTest() {
  modal.value.testResult = null
  modal.value.testing = true
  try {
    modal.value.testResult = await testLLM({
      base_url: modal.value.base_url, api_key: modal.value.api_key, model: modal.value.model,
    })
  } catch (e: any) {
    modal.value.testResult = { ok: false, message: e?.message || '请求失败' }
  } finally {
    modal.value.testing = false
  }
}

async function saveModal() {
  // Dify 风格：保存前先验证连通性，失败则不落库
  await runTest()
  if (!modal.value.testResult?.ok) return
  modal.value.saving = true
  try {
    const m = modal.value
    const items: Array<[string, string]> = [
      ['llm_base_url', m.base_url.trim()],
      ['llm_model', m.model.trim()],
    ]
    // 密钥已配置但弹窗留空 → 跳过，避免空值清掉已存 Key
    if (!(form.value.llm_api_key?.is_set && !m.api_key)) items.push(['llm_api_key', m.api_key.trim()])
    for (const [k, v] of items) await setSetting({ key: k, value: v })
    form.value = await getSettings()
    ElMessage.success('模型配置已保存')
    modal.value.visible = false
  } finally {
    modal.value.saving = false
  }
}

onMounted(async () => {
  // request.ts 响应拦截器已解包 response.data，getSettings() 直接返回设置字典
  form.value = await getSettings()
  // 仅当 Dify 已配置时尝试加载数据集列表
  if (form.value.dify_base_url?.is_set || form.value.dify_api_key?.is_set) {
    await loadDatasets()
  }
})

async function save(k: string) {
  const item = form.value[k]
  if (!item) return
  // 密钥字段已设置但前端拿到的是空串（后端不回显），提交空值会清空已配置的 key，需跳过
  if (item.is_secret && item.is_set && !item.value) {
    ElMessage.info('未填写新值，保留已配置的密钥')
    return
  }
  saving.value = k
  try {
    await setSetting({ key: k, value: item.value })
    // 刷新以更新 is_set 状态（保存密钥后后端仍不回显 value）
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
  if (form.value.dify_dataset_ids) form.value.dify_dataset_ids.value = ids
  ElMessage.success(`已填入 ${datasets.value.length} 个数据集 ID，可点击保存生效`)
}
</script>

<template>
  <PageContainer title="模型配置">
    <el-form label-width="140px">
      <el-divider content-position="left">模型接入</el-divider>
      <div class="provider-grid">
        <div
          v-for="p in providers"
          :key="p.key"
          class="provider-card"
          :class="{ active: activeProviderKey === p.key }"
          @click="openModal(p)"
        >
          <div class="provider-head">
            <div class="provider-avatar" :style="{ background: p.color }">{{ p.short }}</div>
            <div class="provider-info">
              <div class="provider-name">
                {{ p.label }}
                <el-tag v-if="activeProviderKey === p.key" type="success" size="small" effect="light">使用中</el-tag>
              </div>
              <div class="provider-url mono">{{ p.url || p.desc }}</div>
            </div>
          </div>
          <div class="provider-foot">
            <span v-if="activeProviderKey === p.key" class="provider-model">
              {{ form.llm_model?.value || '未配置模型名' }} · {{ llmConfigured ? 'Key 已配置' : 'Key 未配置' }}
            </span>
            <el-button size="small" text type="primary" @click.stop="openModal(p)">配置</el-button>
          </div>
        </div>
      </div>
      <div class="field-hint" style="margin: 4px 0 0;">点击卡片配置模型地址、API Key 与模型名，支持连通性测试；保存时自动验证。</div>

      <el-divider content-position="left">Dify 知识库（智能问答 Agent）</el-divider>
      <el-form-item label="API 端点">
        <div class="field-row">
          <el-input v-model="form.dify_base_url.value" placeholder="http://127.0.0.1:8088/v1" />
          <el-button type="primary" :loading="saving === 'dify_base_url'" @click="save('dify_base_url')">保存</el-button>
        </div>
        <div class="field-hint">Dify 知识库 Service API 端点，需含端口与 /v1，例如 http://127.0.0.1:8088/v1 或 https://dify.example.com/v1</div>
      </el-form-item>
      <el-form-item label="API Key">
        <div class="field-row">
          <el-input v-model="form.dify_api_key.value" show-password placeholder="dataset-..." />
          <el-button type="primary" :loading="saving === 'dify_api_key'" @click="save('dify_api_key')">保存</el-button>
        </div>
        <div class="field-hint">Dataset API Key（Dify 知识库 → API 密钥 中创建），例如 dataset-R6qPqf7CfPC0Dbn6uT3LxIKw</div>
      </el-form-item>
      <el-form-item label="默认数据集 ID">
        <div class="field-row">
          <el-input v-model="form.dify_dataset_ids.value" placeholder="数据集 ID，逗号分隔；可点击下方『拉取列表』自动填入" />
          <el-button type="primary" :loading="saving === 'dify_dataset_ids'" @click="save('dify_dataset_ids')">保存</el-button>
        </div>
        <div class="field-hint">未在问答页选择数据集时使用的默认检索范围</div>
      </el-form-item>
      <el-form-item label="数据集列表">
        <div class="dataset-box">
          <div class="dataset-toolbar">
            <el-button size="small" :loading="loadingDatasets" @click="loadDatasets">🔄 拉取列表</el-button>
            <el-button size="small" type="success" :disabled="!datasets.length" @click="pickDatasetIds">填入全部 ID</el-button>
            <span v-if="datasetsError" class="err">{{ datasetsError }}</span>
          </div>
          <el-table v-if="datasets.length" :data="datasets" size="small" style="margin-top: 8px">
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column prop="document_count" label="文档数" width="90" />
            <el-table-column prop="word_count" label="字数" width="120" />
            <el-table-column prop="id" label="ID" min-width="200">
              <template #default="{ row }"><span class="mono">{{ row.id }}</span></template>
            </el-table-column>
          </el-table>
          <div v-else-if="!loadingDatasets && !datasetsError" class="empty">尚未加载。请先填写并保存 API 端点与 API Key，再点击『拉取列表』。</div>
        </div>
      </el-form-item>

      <el-divider content-position="left">文档解析</el-divider>
      <el-form-item label="MinerU API Key">
        <div class="field-row">
          <el-input v-model="form.mineru_api_key.value" show-password placeholder="未设置" />
          <el-button type="primary" :loading="saving === 'mineru_api_key'" @click="save('mineru_api_key')">保存</el-button>
        </div>
        <div class="field-hint">配置 Key 后支持 PDF/Word/Excel/HTML 云解析；留空则仅 txt/md/csv。</div>
      </el-form-item>
      <el-alert type="info" :closable="false" title="向量模型 BGE-M3 与重排模型 BGE-reranker 本地部署，无需配置。" style="margin-top: 12px;" />
    </el-form>

    <!-- 模型配置弹窗（Dify 风格：地址 / Key / 模型名 + 连通性测试） -->
    <el-dialog v-model="modal.visible" :title="`配置模型 — ${currentProvider.label}`" width="520px" destroy-on-close>
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="服务地址">
          <el-input v-model="modal.base_url" placeholder="https://...（OpenAI 兼容地址，含 /v1）" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="modal.api_key"
            show-password
            :placeholder="form.llm_api_key?.is_set ? '已配置，留空保持不变' : 'sk-...'"
          />
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="modal.model" placeholder="如 glm-4-flash / deepseek-chat" />
        </el-form-item>
        <el-alert
          v-if="modal.testResult?.ok"
          type="success"
          :closable="false"
          show-icon
        >
          <template #title>
            连接成功 · {{ modal.testResult.latency_ms }}ms · 模型「{{ modal.testResult.model }}」回复：{{ modal.testResult.reply || '（空）' }}
          </template>
        </el-alert>
        <el-alert
          v-else-if="modal.testResult && !modal.testResult.ok"
          type="error"
          :closable="false"
          show-icon
          :title="modal.testResult.message || '连接失败'"
        />
      </el-form>
      <template #footer>
        <el-button :loading="modal.testing" @click="runTest">测试连通性</el-button>
        <el-button type="primary" :loading="modal.saving" @click="saveModal">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<style scoped>
.provider-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; width: 100%; }
.provider-card { border: 1px solid #dcdfe6; border-radius: 10px; padding: 14px 16px; cursor: pointer; transition: border-color .2s, box-shadow .2s; background: #fff; }
.provider-card:hover { border-color: #409eff; box-shadow: 0 2px 8px rgba(64, 158, 255, .12); }
.provider-card.active { border-color: #409eff; box-shadow: 0 0 0 1px #409eff inset; }
.provider-head { display: flex; gap: 12px; align-items: center; }
.provider-avatar { width: 40px; height: 40px; border-radius: 10px; color: #fff; font-size: 13px; font-weight: 600; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.provider-info { flex: 1; min-width: 0; }
.provider-name { font-size: 14.5px; font-weight: 600; color: #1f2329; display: flex; align-items: center; gap: 6px; }
.provider-url { font-size: 12px; color: #909399; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.provider-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; }
.provider-model { font-size: 12px; color: #606266; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.field-row { display: flex; gap: 8px; width: 100%; }
.field-row .el-input { flex: 1; }
.field-hint { font-size: 12px; color: #909399; margin-top: 4px; }
.dataset-box { width: 100%; }
.dataset-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.empty { font-size: 12.5px; color: #909399; margin-top: 8px; }
.err { font-size: 12px; color: #f56c6c; }
.mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #334155; }
</style>

