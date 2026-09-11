<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, type UploadUserFile, type UploadFile } from 'element-plus'
import { UploadFilled, Refresh, FolderOpened } from '@element-plus/icons-vue'
import { listDifyDatasets, uploadDifyDocument, type DifyDataset } from '@/api/dify'
import { getSettings } from '@/api/settings'

const datasets = ref<DifyDataset[]>([])
const targetId = ref('')
const loading = ref(false)
const error = ref('')
const files = ref<UploadUserFile[]>([])
const uploading = ref(false)
const currentFile = ref('')
const results = ref<{ name: string; ok: boolean; message: string }[]>([])
const extensions = ['doc', 'docx', 'ppt', 'pptx', 'xls', 'md', 'html', 'csv', 'markdown', 'pdf', 'mdx', 'xlsx', 'txt', 'vtt', 'properties', 'htm']
const accept = extensions.map((extension) => `.${extension}`).join(',')
const completed = ref(0)
const batchSize = ref(0)
const percent = computed(() => batchSize.value ? Math.round(completed.value / batchSize.value * 100) : 0)
const target = computed(() => datasets.value.find((item) => item.id === targetId.value))
const validation = ref('')

function validateFile(file: UploadFile) {
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  const message = !extensions.includes(extension) ? `「${file.name}」格式不支持，请参考右侧格式说明。`
    : !file.size ? `「${file.name}」为空文件，无法上传。`
      : file.size > 15 * 1024 * 1024 ? `「${file.name}」超过 15 MB，请压缩或拆分。` : ''
  validation.value = message
  if (message) {
    files.value = files.value.filter((item) => item.uid !== file.uid)
    ElMessage.warning(message)
  } else if (extension === 'doc' || extension === 'ppt') {
    validation.value = '旧版 DOC / PPT 需要 Dify 配置 Unstructured 解析器；若不支持，请另存为 DOCX / PPTX 后上传。'
  }
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const response = await listDifyDatasets()
    error.value = response.error || ''
    datasets.value = response.error ? [] : response.items || []
    if (!datasets.value.some((item) => item.id === targetId.value)) targetId.value = ''
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
  const selected = files.value.map((item) => item.raw).filter((item): item is NonNullable<typeof item> => !!item)
  if (!selected.length) { ElMessage.warning('请选择文档'); return }
  const datasetId = targetId.value
  const datasetName = datasets.value.find((item) => item.id === datasetId)?.name || datasetId
  results.value = []
  completed.value = 0
  batchSize.value = selected.length
  uploading.value = true
  const succeeded = new Set<number>()
  try {
    for (const file of selected) {
      if (file.size > 15 * 1024 * 1024 || !extensions.includes(file.name.split('.').pop()?.toLowerCase() || '')) {
        results.value.push({ name: file.name, ok: false, message: '文件格式不支持或超过 15 MB，请移除后重新选择' })
        completed.value++
        continue
      }
      currentFile.value = file.name
      try {
        await uploadDifyDocument(datasetId, file)
        succeeded.add(file.uid)
        results.value.push({ name: file.name, ok: true, message: `已上传至「${datasetName}」，Dify 正在分段与索引` })
      } catch (e: any) {
        results.value.push({ name: file.name, ok: false, message: e?.code === 'ECONNABORTED' ? '请求超时，请先到 Dify 确认文档是否已创建，再决定是否重试。' : e?.response?.data?.detail || e?.message || '上传失败，请检查网络后重试' })
      } finally {
        completed.value++
      }
    }
    files.value = files.value.filter((item) => !succeeded.has(item.uid!))
  } finally {
    currentFile.value = ''
    uploading.value = false
  }
  const count = results.value.filter((item) => item.ok).length
  if (count === selected.length) ElMessage.success(`已上传 ${count} 个文档，等待 Dify 分段索引`)
  else ElMessage.warning(`已上传 ${count} 个，失败 ${selected.length - count} 个，请查看具体原因`)
  await refresh()
}

onMounted(refresh)
</script>

<template>
  <div class="manual-upload">
    <div class="page-heading"><div><h3>上传本地文档</h3><p>将文档添加到指定知识库，沿用该知识库的索引与分段配置。</p></div><el-button link type="primary" @click="$router.push('/settings')">系统配置</el-button></div>
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
    <div class="section-title"><span class="step">2</span>添加文档<span class="file-count">{{ files.length }} / 5 个</span></div>
    <el-upload v-model:file-list="files" class="upload" drag multiple :auto-upload="false" :disabled="uploading || !targetId || loading" :accept="accept" :limit="5" :on-change="validateFile" :on-exceed="() => ElMessage.warning('每批最多上传 5 个文件，请分批上传')">
      <el-icon class="upload-icon"><UploadFilled /></el-icon>
      <div class="drop-title">拖拽文档到此处，或 <em>点击选择</em></div>
      <div class="drop-hint">{{ targetId ? '支持多个文件，每个文件不超过 15 MB' : '请先选择上方的目标知识库' }}</div>
    </el-upload>
    <el-alert v-if="validation" :title="validation" type="warning" show-icon :closable="false" class="validation" />
    <div v-if="uploading" class="progress"><div class="hint">正在处理 {{ completed + 1 > batchSize ? batchSize : completed + 1 }} / {{ batchSize }}：{{ currentFile }}</div><el-progress :percentage="percent" /></div>
    <div class="upload-footer">
      <span class="hint">上传成功后，Dify 将异步解析与索引</span>
      <el-button type="primary" :loading="uploading" :disabled="!targetId || !files.length || loading" @click="upload">{{ uploading ? '上传中' : '开始上传' }}</el-button>
    </div>
    </el-card>
    <el-card shadow="never" class="guide-card">
      <template #header><span class="section-title">上传说明</span></template>
      <div class="limit-tags"><el-tag effect="plain">单个 ≤ 15 MB</el-tag><el-tag type="info" effect="plain">每批 ≤ 5 个</el-tag></div>
      <h4>常见文档格式</h4>
      <dl><dt>文档</dt><dd>PDF、DOCX、TXT</dd><dt>表格</dt><dd>XLS、XLSX、CSV</dd><dt>演示</dt><dd>PPTX（按页提取文本）</dd><dt>其他</dt><dd>MD、MARKDOWN、MDX、HTML、HTM、VTT、PROPERTIES</dd></dl>
      <h4>解析与限制</h4>
      <p>PPTX 自动转换为 Markdown 上传，保留页序与文字，不包含图片、动画和版式。</p>
      <p>旧版 DOC、PPT 依赖 Dify 的 Unstructured 解析器；建议另存为 DOCX、PPTX。请勿直接修改扩展名。</p>
      <p>扫描件、纯图片文档需先 OCR；加密文件需解除密码。Dify 或网关的大小限制可能低于 15 MB。</p>
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
.page-heading { display:flex; justify-content:space-between; align-items:center; margin:8px 0 20px; }
.page-heading h3 { font-size:18px; margin:0 0 8px; color:var(--el-text-color-primary); }
.page-heading p { margin:0; font-size:13px; color:var(--el-text-color-secondary); }
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
