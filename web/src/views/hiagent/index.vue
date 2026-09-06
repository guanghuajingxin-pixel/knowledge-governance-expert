<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Loading } from '@element-plus/icons-vue'

// HiAgent（火山引擎）智能体 WebSDK 配置
const HIAGENT_SDK_URL =
  'https://hia.volcenginepaas.com/resources/product/llm/public/sdk/embedFull.js'
const HIAGENT_APP_KEY = 'dabr1u3i47rnq2qe21qg'
const HIAGENT_BASE_URL = 'https://hia.volcenginepaas.com'

const hostRef = ref<HTMLElement | null>(null)
const loading = ref(true)
const errorMsg = ref('')
let observer: MutationObserver | null = null

onMounted(() => {
  const host = hostRef.value
  if (!host) return

  // SDK 初始化后会向宿主节点插入 iframe（成功）或错误提示 div（失败），据此关闭 loading
  observer = new MutationObserver(() => {
    if (host.querySelector('iframe')) {
      loading.value = false
      observer?.disconnect()
      return
    }
    const errEl = host.querySelector('div')
    if (errEl) {
      errorMsg.value = errEl.textContent || 'HiAgent 加载失败，请稍后重试'
      loading.value = false
      observer?.disconnect()
    }
  })
  observer.observe(host, { childList: true })

  // 动态加载 SDK 脚本
  const sdkScript = document.createElement('script')
  sdkScript.src = HIAGENT_SDK_URL
  sdkScript.async = true
  sdkScript.onload = () => {
    // SDK 以「初始化内联脚本的父节点」作为挂载容器，
    // 因此必须把 init 脚本注入到当前宿主 div 内，iframe 才会渲染到本页面
    const initScript = document.createElement('script')
    initScript.textContent = `new HiagentWebSDK.WebClient({appKey:${JSON.stringify(
      HIAGENT_APP_KEY,
    )},baseUrl:${JSON.stringify(HIAGENT_BASE_URL)},hideSidebar:false,variables:{}});`
    host.appendChild(initScript)
  }
  sdkScript.onerror = () => {
    loading.value = false
    errorMsg.value = 'HiAgent SDK 脚本加载失败，请检查网络连接后刷新重试'
    observer?.disconnect()
  }
  host.appendChild(sdkScript)
})

onUnmounted(() => {
  observer?.disconnect()
  observer = null
  // 离开页面时清理 SDK 注入的 iframe / 脚本，避免节点残留
  if (hostRef.value) hostRef.value.innerHTML = ''
})

function reload() {
  window.location.reload()
}
</script>

<template>
  <div class="hiagent-page">
    <!-- 加载中提示 -->
    <div v-if="loading" class="hiagent-mask">
      <el-icon class="is-loading" :size="28" color="#2b6bff"><Loading /></el-icon>
      <span class="mask-text">正在加载 HiAgent 智能问答…</span>
    </div>
    <!-- 加载失败提示（域名白名单/网络/智能体配置异常） -->
    <div v-else-if="errorMsg" class="hiagent-mask">
      <el-result icon="warning" title="HiAgent 智能问答加载失败" :sub-title="errorMsg">
        <template #extra>
          <el-button type="primary" @click="reload">刷新重试</el-button>
        </template>
      </el-result>
    </div>
    <!-- SDK 挂载宿主：HiAgent iframe 会被注入到此节点 -->
    <div ref="hostRef" class="hiagent-host" />
  </div>
</template>

<style scoped>
.hiagent-page {
  position: relative;
  height: 100%;
  min-height: 600px;
  background: #fff;
}
.hiagent-host {
  width: 100%;
  height: 100%;
}
.hiagent-mask {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: #fff;
}
.mask-text {
  font-size: 14px;
  color: #6b7280;
}
</style>
