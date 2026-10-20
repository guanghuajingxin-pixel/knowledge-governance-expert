<script setup lang="ts">
import { ElTooltip } from 'element-plus'
import portalMark from '@/assets/portal-mark.svg'

// 门户统一占用主机默认端口（本地 dev :80 / 生产 Nginx 80，容器源站 3200）。
// KGE 本体固定 8080（本地与生产同口径），因此入口 URL = 当前主机去掉端口（即 80），
// 本地 http://localhost:8080 → 门户 http://localhost/，生产 http://10.10.166.2:8080 → http://10.10.166.2/。
// 独立域名部署时用 VITE_PORTAL_URL 覆盖（构建期注入）。
const defaultPortalUrl = new URL(window.location.origin)
defaultPortalUrl.port = ''
const portalUrl = import.meta.env.VITE_PORTAL_URL?.trim() || defaultPortalUrl.href

// KGE 以 iframe 形式内嵌在门户内时（门户「知识治理专家」应用页），用户本就在门户里，
// 再展示「跳回门户」入口只会造成「门户里再开门户」的冗余跳转，此时隐藏该按钮。
const embeddedInPortal = window.self !== window.top
</script>

<template>
  <ElTooltip v-if="!embeddedInPortal" content="打开杰克科技 AIGC 门户（新标签页）" placement="bottom">
    <a
      class="portal-entry"
      :href="portalUrl"
      target="_blank"
      rel="noopener noreferrer"
      aria-label="打开杰克科技 AIGC 门户（新标签页）"
    >
      <img :src="portalMark" class="portal-mark" alt="" width="28" height="28" />
      <span class="portal-label">AIGC 门户</span>
    </a>
  </ElTooltip>
</template>

<style scoped lang="scss">
.portal-entry {
  display: inline-flex;
  align-items: center;
  align-self: center;
  flex-shrink: 0;
  gap: 8px;
  height: 32px;
  padding: 0 8px 0 4px;
  border-radius: 8px;
  color: var(--el-color-primary);
  text-decoration: none;
  white-space: nowrap;
  transition: background-color 0.15s ease;

  &:hover {
    background: var(--el-color-primary-light-9);
  }

  &:focus-visible {
    outline: 2px solid var(--el-color-primary);
    outline-offset: 2px;
  }
}

.portal-mark {
  display: block;
  flex-shrink: 0;
}

.portal-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.4px;
}

@media (max-width: 640px) {
  .portal-entry { padding: 0 4px; }
  .portal-label { display: none; }
}
</style>
