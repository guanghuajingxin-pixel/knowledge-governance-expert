<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getAgentConfig } from '@/api/agent'

// 钉钉 DEAP 智能问答智能体（发布后的 H5 链接）
// 嵌入地址来自「智能体配置 → DEAP智能问答」external_agents.deap；未配置时回退到内置链接
// 注意：DEAP H5 需要**钉钉登录态**（未登录会 302 到钉钉 OAuth，页面内引导用户在钉钉客户端/已登录浏览器中打开）
const FALLBACK_URL =
  'https://deap-agent.dingtalk.com/h5/index.html?publish_h5=1&code=f4408df0-5230-4f7f-bbe7-1207d4e2a048'

const iframeUrl = ref(FALLBACK_URL)

onMounted(async () => {
  try {
    const cfg = await getAgentConfig()
    const url = cfg.external_agents?.deap?.url
    if (url) iframeUrl.value = url
  } catch {
    /* 配置拉取失败时保留默认链接 */
  }
})

// 新窗口打开（钉钉登录态在新页签中完成，避免 iframe 内 OAuth 被拦截）
function openInNewTab() {
  window.open(iframeUrl.value, '_blank', 'noopener')
}
</script>

<template>
  <div class="deap-page">
    <div class="deap-toolbar">
      <span class="deap-title">钉钉 DEAP 智能问答</span>
      <span class="deap-hint">需钉钉登录态；若下方未显示，请点击右侧按钮在钉钉中打开</span>
      <el-button size="small" type="primary" plain @click="openInNewTab">在钉钉中打开 ↗</el-button>
    </div>
    <!-- 直接 iframe 嵌入 DEAP H5：已登录钉钉的浏览器内可直接对话（allow=microphone 支持语音输入） -->
    <iframe
      :src="iframeUrl"
      class="deap-iframe"
      title="钉钉 DEAP 智能问答"
      allow="microphone"
      referrerpolicy="no-referrer-when-downgrade"
    />
  </div>
</template>

<style scoped>
.deap-page {
  height: 100%;
  min-height: 700px;
  display: flex;
  flex-direction: column;
  background: #fff;
}
.deap-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  border-bottom: 1px solid #ebeef5;
  background: #fafbfd;
}
.deap-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.deap-hint {
  flex: 1;
  font-size: 12px;
  color: #9ca3af;
}
.deap-iframe {
  flex: 1;
  width: 100%;
  border: none;
}
</style>
