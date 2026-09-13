<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { useUserStore } from '@/stores/user'
import { useRouter } from 'vue-router'
import { Expand, Fold, ArrowDown } from '@element-plus/icons-vue'
import Breadcrumb from './Breadcrumb.vue'
import { getOverviewMetrics } from '@/api/metrics'

const appStore = useAppStore()
const userStore = useUserStore()
const router = useRouter()

// 顶栏运营指标：value 为 null 时表示尚未取到数，展示占位符而非假数字
const metrics = ref<[string, number | null][]>([
  ['今日新增', null],
  ['今日加工', null],
  ['累计采纳', null],
  ['累计反馈', null],
])

onMounted(async () => {
  try {
    const data = await getOverviewMetrics()
    metrics.value = [
      ['今日新增', data.today_new],
      ['今日加工', data.today_processed],
      ['累计采纳', data.total_adopted],
      ['累计反馈', data.total_feedback],
    ]
  } catch {
    // 取数失败保持占位符，避免展示误导性的数字
  }
})

function handleCommand(command: string) {
  if (command === 'logout') {
    userStore.logout()
    router.push('/login')
  }
}
</script>

<template>
  <div class="header">
    <div class="header-left">
      <el-icon class="collapse-btn" size="20" @click="appStore.toggleSidebar()">
        <Fold v-if="!appStore.sidebarCollapsed" />
        <Expand v-else />
      </el-icon>
      <Breadcrumb />
    </div>

    <div class="header-center">
      <!-- 关键指标 -->
      <div class="metrics">
        <span v-for="[label, value] in metrics" :key="label" class="metric-item">
          {{ label }} <b>{{ value ?? '--' }}</b>
        </span>
      </div>
    </div>

    <div class="header-right">
      <el-dropdown @command="handleCommand">
        <span class="user-info">
          <el-avatar :size="32" icon="UserFilled" />
          <span class="username">{{ userStore.userInfo?.username || '用户' }}</span>
          <el-icon><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<style scoped>
.header {
  height: 56px;
  background: #fff;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 20px;
  border-bottom: 1px solid #e6e6e6;
  gap: 16px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}
.collapse-btn {
  cursor: pointer;
}
.header-center {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
}
.metrics {
  display: flex;
  align-items: center;
  gap: 10px;
}
.metric-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #6b7280;
  background: #f5f7fa;
  border: 1px solid #e5e8ee;
  border-radius: 999px;
  padding: 4px 14px;
  white-space: nowrap;
}
.metric-item b {
  color: #2b6bff;
  font-size: 16px;
  font-weight: 700;
}

.header-right {
  flex-shrink: 0;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.username {
  font-size: 14px;
}
@media (max-width: 1200px) {
  .metrics { display: none; }
}
</style>
