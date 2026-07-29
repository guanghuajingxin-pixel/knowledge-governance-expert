<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import PageContainer from '@/components/common/PageContainer.vue'
import { getSettings, setSetting, type SettingsResponse, type SettingItem } from '@/api/settings'

// 预填占位项，保证模板中 v-model="form.xxx.value" 在 onMounted 加载前即为可赋值目标
const EMPTY: SettingItem = { label: '', value: '', is_set: false, is_secret: false }
const form = ref<SettingsResponse>({
  llm_base_url: { ...EMPTY },
  llm_api_key: { ...EMPTY, is_secret: true },
  llm_model: { ...EMPTY },
  mineru_api_key: { ...EMPTY, is_secret: true },
})
const saving = ref<string | null>(null)

const providers = [
  { label: 'GLM (智谱)', url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  { label: 'DeepSeek', url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
]

onMounted(async () => {
  // request.ts 响应拦截器已解包 response.data，getSettings() 直接返回设置字典
  form.value = await getSettings()
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

function pick(p: { label: string; url: string; model: string }) {
  if (form.value.llm_base_url) form.value.llm_base_url.value = p.url
  if (form.value.llm_model) form.value.llm_model.value = p.model
}
</script>

<template>
  <PageContainer title="模型配置">
    <el-form label-width="140px">
      <el-divider content-position="left">LLM 大模型</el-divider>
      <el-form-item label="快速选择">
        <el-button v-for="p in providers" :key="p.label" @click="pick(p)">{{ p.label }}</el-button>
      </el-form-item>
      <el-form-item label="LLM 服务地址">
        <div class="field-row">
          <el-input v-model="form.llm_base_url.value" placeholder="https://..." />
          <el-button type="primary" :loading="saving === 'llm_base_url'" @click="save('llm_base_url')">保存</el-button>
        </div>
      </el-form-item>
      <el-form-item label="LLM API Key">
        <div class="field-row">
          <el-input v-model="form.llm_api_key.value" show-password placeholder="未设置" />
          <el-button type="primary" :loading="saving === 'llm_api_key'" @click="save('llm_api_key')">保存</el-button>
        </div>
      </el-form-item>
      <el-form-item label="模型名">
        <div class="field-row">
          <el-input v-model="form.llm_model.value" placeholder="glm-4-flash" />
          <el-button type="primary" :loading="saving === 'llm_model'" @click="save('llm_model')">保存</el-button>
        </div>
      </el-form-item>
      <el-divider content-position="left">文档解析</el-divider>
      <el-form-item label="MinerU API Key">
        <div class="field-row">
          <el-input v-model="form.mineru_api_key.value" show-password placeholder="未设置" />
          <el-button type="primary" :loading="saving === 'mineru_api_key'" @click="save('mineru_api_key')">保存</el-button>
        </div>
      </el-form-item>
      <el-alert type="info" :closable="false" title="向量模型 BGE-M3 与重排模型 BGE-reranker 本地部署，无需配置。" style="margin-top: 12px;" />
    </el-form>
  </PageContainer>
</template>

<style scoped>
.field-row { display: flex; gap: 8px; width: 100%; }
.field-row .el-input { flex: 1; }
</style>
