<script setup lang="ts">
/**
 * 解析引擎（知识加工 · 二级页）· 页签外壳
 *
 * 两个页内页签：
 *  1.【自定义解析】→ components/ParserCustomTab.vue
 *     对接「统一文档解析引擎」独立服务（默认 127.0.0.1:8000）的测试台 + Key 管理。
 *  2.【MinerU WebUI】→ iframe 原样接入 http://127.0.0.1:7860/
 *     该页为 MinerU 官方 Gradio WebUI（`mineru-kit webui`，源码在 mineru venv 的
 *     kit/gradio/app.py，UI 由 Gradio 运行时从 Python 生成，本仓库无独立前端源码可并入），
 *     故按「无前端源码 → iframe」接入；其后端调用（MinerU V1 API，--api-url）保持不变。
 *
 * iframe 地址可配置并持久化，便于指向其他实例；提供重新加载 / 新窗口打开。
 */
import { computed, ref, watch } from 'vue'
import { Link, Refresh, TopRight } from '@element-plus/icons-vue'
import ParserCustomTab from './components/ParserCustomTab.vue'

const activeTab = ref<'custom' | 'webui'>('custom')

// ===== MinerU WebUI（iframe）=====
const WEBUI_URL_KEY = 'kge:parser_webui_url_v1'
const DEFAULT_WEBUI_URL = 'http://127.0.0.1:7860/'

const webuiUrl = ref(DEFAULT_WEBUI_URL)
const frameNonce = ref(0)

function loadWebuiUrl() {
  try {
    const saved = localStorage.getItem(WEBUI_URL_KEY)
    if (saved) webuiUrl.value = saved
  } catch {
    /* 忽略损坏缓存 */
  }
}
loadWebuiUrl()

watch(webuiUrl, (v) => {
  try {
    localStorage.setItem(WEBUI_URL_KEY, v)
  } catch {
    /* 存储失败不影响使用 */
  }
})

const webuiSrc = computed(() => webuiUrl.value.trim() || DEFAULT_WEBUI_URL)

function reloadWebui() {
  // 通过 key 强制重挂载 iframe 实现刷新（跨源无法直接 contentWindow.reload）
  frameNonce.value += 1
}

function openWebuiExternal() {
  window.open(webuiSrc.value, '_blank', 'noopener')
}
</script>

<template>
  <div class="engine-shell">
    <el-tabs v-model="activeTab" class="engine-tabs">
      <!-- 页签一：自定义解析 -->
      <el-tab-pane label="自定义解析" name="custom">
        <ParserCustomTab />
      </el-tab-pane>

      <!-- 页签二：MinerU 官方 WebUI（iframe 原样接入，后端调用不变） -->
      <el-tab-pane label="MinerU WebUI" name="webui" lazy>
        <div class="webui-pane">
          <div class="webui-toolbar">
            <el-input
              v-model="webuiUrl"
              placeholder="WebUI 地址"
              style="width: 320px"
              :prefix-icon="Link"
              clearable
            />
            <el-button plain :icon="Refresh" @click="reloadWebui">重新加载</el-button>
            <el-button plain :icon="TopRight" @click="openWebuiExternal">新窗口打开</el-button>
            <span class="webui-hint">
              MinerU 官方 Gradio WebUI；UI 由 Gradio 运行时生成，无独立前端源码，故 iframe 原样接入，其后端调用（MinerU V1 API）不变。
            </span>
          </div>
          <iframe
            :key="frameNonce"
            :src="webuiSrc"
            class="webui-frame"
            title="MinerU WebUI"
            frameborder="0"
          />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.engine-shell {
  min-height: 100%;
  background: #f5f7fa;
}
.engine-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 16px;
  background: #fff;
  border-bottom: 1px solid #e5e8ee;
}
.engine-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}
.engine-tabs :deep(.el-tabs__item) {
  font-size: 14px;
  font-weight: 600;
  height: 46px;
  line-height: 46px;
}
.engine-tabs :deep(.el-tabs__content) {
  padding: 0;
}

/* ===== MinerU WebUI 页签 ===== */
.webui-pane {
  padding: 12px 16px 16px;
}
.webui-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.webui-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  margin-left: auto;
  max-width: 560px;
}
.webui-frame {
  display: block;
  width: 100%;
  height: calc(100vh - 220px);
  min-height: 620px;
  border: 1px solid #d7e1ec;
  border-radius: 8px;
  background: #fff;
}
</style>
