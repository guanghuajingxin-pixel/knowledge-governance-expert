<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, type UploadUserFile, type UploadFile } from 'element-plus'
import { UploadFilled, Refresh, FolderOpened } from '@element-plus/icons-vue'
import { listDifyDatasets, listSupportedExtensions, uploadDifyDocument, type DifyDataset } from '@/api/dify'
import { getSettings } from '@/api/settings'

import PipelineInputs from '@/components/collection/PipelineInputs.vue'

const datasets = ref<DifyDataset[]>([])
const targetId = ref('')
const loading = ref(false)
const error = ref('')
const files = ref<UploadUserFile[]>([])
const uploading = ref(false)
const activeFiles = ref<string[]>([])
const results = ref<{ name: string; ok: boolean; message: string }[]>([])
// Dify 内置 ETL 白名单兜底；挂载时从后端拉真实白名单（随 ETL_TYPE 切换）
const extensions = ref<string[]>(['txt', 'markdown', 'md', 'mdx', 'pdf', 'html', 'htm', 'xlsx', 'xls', 'docx', 'csv', 'vtt', 'properties'])
const etlType = ref('dify')
const accept = computed(() => extensions.value.map((extension) => `.${extension}`).join(','))
const completed = ref(0)
const batchSize = ref(0)
const percent = computed(() => batchSize.value ? Math.round(completed.value / batchSize.value * 100) : 0)
const target = computed(() => datasets.value.find((item) => item.id === targetId.value))
const validation = ref('')
// 单批最多 100 个文件，同时在跑的请求最多 5 个。
// 流水线数据集（rag_pipeline）走 pipeline/run 阻塞模式，单个文档 30s~数分钟；
// 并发 5 是「打爆 Dify/MinerU」与「用户等待时间」之间的折中。
const MAX_BATCH = 100
const CONCURRENCY = 5

const pipelineForm = ref<InstanceType<typeof PipelineInputs>>()
const pipelineInputs = ref<Record<string, any>>({})
const maxUploadBytes = ref(15 * 1024 * 1024)
watch(targetId, () => { pipelineInputs.value = {}; loadSupportedExtensions() })

function validateFile(file: UploadFile) {
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  const message = !extensions.value.includes(extension) ? `「${file.name}」格式不支持（当前 Dify ETL=${etlType.value}），请参考右侧格式说明。`
    : !file.size ? `「${file.name}」为空文件，无法上传。`
      : file.size > maxUploadBytes.value ? `「${file.name}」超过 ${maxUploadBytes.value / 1024 / 1024} MB，请核对上传上限。` : ''
  validation.value = message
  if (message) {
    files.value = files.value.filter((item) => item.uid !== file.uid)
    ElMessage.warning(message)
  } else if (extension === 'doc' || extension === 'ppt') {
    validation.value = '旧版 DOC / PPT 需要 Dify 配置 Unstructured 解析器；若不支持，请另存为 DOCX / PPTX 后上传。'
  }
}

// Dify 知识库列表持久缓存 1 小时：listDifyDatasets 走 Dify API（1~3s），
// 命中秒开下拉并后台校准；上传前 extensions/大小限制仍实时拉取（watch targetId）
const DS_STORE_KEY = 'kge:dify_datasets_v1'
const DS_STORE_TTL = 3_600_000

async function refresh() {
  // ① 持久缓存命中：先出列表，后台静默校准
  try {
    const raw = localStorage.getItem(DS_STORE_KEY)
    if (raw) {
      const c = JSON.parse(raw) as { ts: number; items: typeof datasets.value }
      if (Date.now() - c.ts <= DS_STORE_TTL && c.items?.length) {
        datasets.value = c.items
        listDifyDatasets().then((response) => {
          const items = response.error ? [] : response.items || []
          if (items.length) {
            datasets.value = items
            localStorage.setItem(DS_STORE_KEY, JSON.stringify({ ts: Date.now(), items }))
          }
        }).catch(() => { /* 后台校准失败保留缓存 */ })
        return
      }
    }
  } catch { /* 缓存读取失败走网络 */ }
  // ② 未命中：正常拉取并回写缓存
  loading.value = true
  error.value = ''
  try {
    const response = await listDifyDatasets()
    error.value = response.error || ''
    datasets.value = response.error ? [] : response.items || []
    if (!datasets.value.some((item) => item.id === targetId.value)) targetId.value = ''
    if (datasets.value.length) {
      try { localStorage.setItem(DS_STORE_KEY, JSON.stringify({ ts: Date.now(), items: datasets.value })) } catch { /* 忽略 */ }
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载知识库失败'
    datasets.value = []
    targetId.value = ''
  } finally { loading.value = false }
}

async function openDify() {
  try {
    const settings = await getSettings()
    const baseUrl = (settings.dify_base_url?.value || '').trim().replace(/\/v1\/?$/, '')
    if (!baseUrl) { ElMessage.warning('请先在系统配置中设置 Dify 服务地址'); return }
    window.open(`${baseUrl}/datasets`, '_blank', 'noopener,noreferrer')
  } catch { /* API 拦截器提示错误 */ }
}

async function upload() {
  if (uploading.value) return
  if (!targetId.value) { ElMessage.warning('请选择目标知识库'); return }
  if (pipelineForm.value && !pipelineForm.value.validate()) return
  const selected = files.value.map((item) => item.raw).filter((item): item is NonNullable<typeof item> => !!item)
  if (!selected.length) { ElMessage.warning('请选择文档'); return }
  const datasetId = targetId.value
  const datasetName = datasets.value.find((item) => item.id === datasetId)?.name || datasetId
  results.value = []
  completed.value = 0
  batchSize.value = selected.length
  uploading.value = true
  activeFiles.value = []
  const succeeded = new Set<number>()
  // 共享游标：多个 worker 抢占式取下一个待上传文件，天然实现「上限 CONCURRENCY 并发」。
  let cursor = 0
  async function worker() {
    while (cursor < selected.length) {
      const index = cursor++
      const file = selected[index]
      if (file.size > maxUploadBytes.value || !extensions.value.includes(file.name.split('.').pop()?.toLowerCase() || '')) {
        results.value.push({ name: file.name, ok: false, message: `文件格式不支持或超过 ${maxUploadBytes.value / 1024 / 1024} MB` })
        completed.value++
        continue
      }
      activeFiles.value.push(file.name)
      try {
        await uploadDifyDocument(datasetId, file, pipelineInputs.value)
        succeeded.add(file.uid)
        results.value.push({ name: file.name, ok: true, message: `已上传至「${datasetName}」，Dify 正在分段与索引` })
      } catch (e: any) {
        results.value.push({ name: file.name, ok: false, message: e?.code === 'ECONNABORTED' ? '请求超时，请先到 Dify 确认文档是否已创建，再决定是否重试。' : e?.response?.data?.detail || e?.message || '上传失败，请检查网络后重试' })
      } finally {
        completed.value++
        activeFiles.value = activeFiles.value.filter((name) => name !== file.name)
      }
    }
  }
  try {
    const workerCount = Math.min(CONCURRENCY, selected.length)
    await Promise.all(Array.from({ length: workerCount }, () => worker()))
    files.value = files.value.filter((item) => !succeeded.has(item.uid!))
  } finally {
    activeFiles.value = []
    uploading.value = false
  }
  const count = results.value.filter((item) => item.ok).length
  if (count === selected.length) ElMessage.success(`已上传 ${count} 个文档，等待 Dify 分段索引`)
  else ElMessage.warning(`已上传 ${count} 个，失败 ${selected.length - count} 个，请查看具体原因`)
  await refresh()
}

async function loadSupportedExtensions() {
  try {
    const datasetId = targetId.value
    const r = await listSupportedExtensions(datasetId)
    if (datasetId !== targetId.value) return
    maxUploadBytes.value = r.max_upload_bytes
    etlType.value = r.etl_type || 'dify'
    if (r.extensions?.length) extensions.value = r.extensions
  } catch {
    /* 拉取失败保持内置 ETL 默认白名单 */
  }
}

onMounted(() => { refresh(); loadSupportedExtensions() })
</script>

<template>
  <div class="kge-page kge-page--scroll">
    <div class="upload-grid">
    <el-card shadow="never" class="main-card">
    <template #header><span class="section-title"><span class="step">1</span>选择目标知识库</span></template>
    <el-form label-position="top">
      <el-form-item label="Dify 目标知识库">
        <div class="actions">
          <el-select v-model="targetId" filterable placeholder="搜索并选择 Dify 知识库" :loading="loading" :disabled="uploading || loading" class="dataset-select">
            <el-option v-for="item in datasets" :key="item.id" :value="item.id" :label="`${item.name}（${item.document_count} 篇）`" />
          </el-select>
          <el-button :icon="Refresh" :loading="loading" :disabled="uploading" @click="refresh">刷新</el-button>
        </div>
      </el-form-item>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-empty v-else-if="!loading && !datasets.length" description="暂无可用知识库" :image-size="64"><el-button type="primary" plain @click="openDify">去 Dify 新建知识库</el-button></el-empty>
    <div v-if="target" class="target-summary"><el-icon><FolderOpened /></el-icon><span>{{ target.name }}</span><el-tag type="info" size="small">已有 {{ target.document_count }} 篇文档</el-tag></div>
    <el-divider />
    <PipelineInputs ref="pipelineForm" :dataset-id="targetId" v-model="pipelineInputs" :disabled="uploading" />
    <div class="section-title"><span class="step">2</span>添加文档<span class="file-count">{{ files.length }} / {{ MAX_BATCH }} 个</span></div>
    <el-upload v-model:file-list="files" class="upload" drag multiple :auto-upload="false" :disabled="uploading || !targetId || loading" :accept="accept" :limit="MAX_BATCH" :on-change="validateFile" :on-exceed="() => ElMessage.warning(`每批最多上传 ${MAX_BATCH} 个文件，请分批上传`)">
      <el-icon class="upload-icon"><UploadFilled /></el-icon>
      <div class="drop-title">拖拽文档到此处，或 <em>点击选择</em></div>
      <div class="drop-hint">{{ targetId ? `支持多个文件（每批 ≤ ${MAX_BATCH} 个，单个 ≤ ${maxUploadBytes / 1024 / 1024} MB），并发 ${CONCURRENCY} 上传` : '请先选择上方的目标知识库' }}</div>
    </el-upload>
    <el-alert v-if="validation" :title="validation" type="warning" show-icon :closable="false" class="validation" />
    <div v-if="uploading" class="progress">
      <div class="hint">
        已完成 {{ completed }} / {{ batchSize }}
        <span v-if="activeFiles.length">
          ，正在处理 {{ activeFiles.length }} 个：{{ activeFiles.slice(0, 3).join('、') }}<span v-if="activeFiles.length > 3">…</span>
        </span>
      </div>
      <el-progress :percentage="percent" />
    </div>
    <div class="upload-footer">
      <span class="hint">上传成功后，Dify 将异步解析与索引</span>
      <el-button type="primary" :loading="uploading" :disabled="!targetId || !files.length || loading" @click="upload">{{ uploading ? '上传中' : '开始上传' }}</el-button>
    </div>
    </el-card>
    <el-card shadow="never" class="guide-card">
      <template #header><span class="section-title">上传说明</span></template>
      <div class="limit-tags"><el-tag effect="plain">单个 ≤ {{ maxUploadBytes / 1024 / 1024 }} MB</el-tag><el-tag type="info" effect="plain">每批 ≤ {{ MAX_BATCH }} 个</el-tag></div>
      <h4>当前支持的文档格式</h4>
      <p>Dify ETL 类型：<b>{{ etlType }}</b>{{ etlType.toLowerCase() === 'unstructured' ? '（Unstructured 服务解析）' : '（Dify 内置解析）' }}</p>
      <p>{{ extensions.map((e) => e.toUpperCase()).join('、') }}</p>
      <p v-if="etlType.toLowerCase() !== 'unstructured'">PPTX / PPT / DOC / EML 等格式需 Dify 配置 ETL_TYPE=Unstructured 后才支持；当前会被 Dify 拒收。</p>
      <h4>解析与限制</h4>
      <p>PPTX 自动转换为 Markdown 上传，保留页序与文字，不包含图片、动画和版式。</p>
      <p>旧版 DOC、PPT 依赖 Dify 的 Unstructured 解析器；建议另存为 DOCX、PPTX。请勿直接修改扩展名。</p>
      <p>原文件交由目标知识库解析；扫描件需要流水线配置 OCR。上传上限须与 Dify 服务及网关保持一致。</p>
      <p>目标为「知识流水线」类型的 Dify 知识库时，走 pipeline/run 阻塞模式（含解析+分段+索引），单个文档可能需要数十秒到几分钟，进度看似缓慢属正常，请勿中途刷新页面。</p>
      <p>“已上传”表示文档已创建，索引结果请到 Dify 查看。超时后先检查目标知识库，避免重复上传。</p>
      <el-button link type="primary" @click="openDify">打开 Dify 知识库</el-button>
    </el-card>
    </div>
    <el-card v-if="results.length" shadow="never" class="results-card"><template #header><span class="section-title">上传结果</span><span class="hint">成功 {{ results.filter(item => item.ok).length }} · 失败 {{ results.filter(item => !item.ok).length }}，失败文件保留在待上传列表</span></template>
    <el-table v-if="results.length" :data="results" class="results">
      <el-table-column prop="name" label="文档" min-width="200" />
      <el-table-column label="结果" width="90"><template #default="{ row }"><el-tag :type="row.ok ? 'success' : 'danger'">{{ row.ok ? '已上传' : '失败' }}</el-tag></template></el-table-column>
      <el-table-column prop="message" label="说明" min-width="280" />
    </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.upload { margin: 16px 0; }
.hint { color: var(--el-text-color-secondary); font-size: 12px; }
.results { margin-top: 16px; }
.upload-grid { display:grid; grid-template-columns:minmax(0, 1fr) 300px; gap:20px; align-items:start; }
.section-title { display:flex; align-items:center; gap:10px; font-size:14px; font-weight:600; }
.step { display:inline-flex; align-items:center; justify-content:center; width:24px; height:24px; border-radius:50%; background:var(--el-color-primary-light-9); color:var(--el-color-primary); }
.actions { width:100%; flex-wrap:nowrap; }
.dataset-select { flex:1; min-width:0; }
.target-summary { display:flex; gap:8px; align-items:center; padding:12px; background:var(--el-fill-color-light); font-size:13px; }
.file-count { margin-left:auto; font-size:12px; font-weight:400; color:var(--el-text-color-secondary); }
.upload :deep(.el-upload-dragger) { padding:32px 16px; background:var(--el-fill-color-lighter); }
.upload-icon { font-size:44px; color:var(--el-color-primary); margin-bottom:12px; }
.drop-title { font-size:14px; color:var(--el-text-color-primary); }
.drop-title em { font-style:normal; color:var(--el-color-primary); }
.drop-hint { margin-top:10px; font-size:12px; color:var(--el-text-color-secondary); }
.upload-footer { border-top:1px solid var(--el-border-color-lighter); padding-top:16px; display:flex; gap:12px; justify-content:space-between; align-items:center; }
.limit-tags { display:flex; gap:8px; }
.guide-card h4 { font-size:13px; margin:22px 0 12px; }
.guide-card p, .guide-card dl { font-size:12px; line-height:1.8; color:var(--el-text-color-regular); }
.guide-card dl { display:grid; grid-template-columns:36px 1fr; gap:8px 12px; }
.guide-card dd { margin:0; overflow-wrap:anywhere; }
.guide-card dt { color:var(--el-text-color-secondary); }
.validation, .progress { margin-bottom:16px; }
.results-card { margin-top:20px; }
.results-card :deep(.el-card__header) { display:flex; gap:16px; justify-content:space-between; flex-wrap:wrap; }
@media (max-width:1000px) { .upload-grid { grid-template-columns:1fr; } }
</style>
