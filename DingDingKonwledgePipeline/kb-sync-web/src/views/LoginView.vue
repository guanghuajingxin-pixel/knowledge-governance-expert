<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { errMsg } from '@/api/http'

const router = useRouter()
const auth = useAuthStore()
const username = ref('admin')
const password = ref('admin123')
const loading = ref(false)

async function doLogin() {
  if (!username.value || !password.value) { ElMessage.error('请输入账号和密码'); return }
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    ElMessage.success(`欢迎回来，${username.value === 'admin' ? '知识管理员' : username.value}`)
    router.push('/dashboard')
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo">知</div>
      <h1>知识同步管理后台</h1>
      <div class="sub">钉钉知识库 → Dify 定时增量同步</div>
      <div class="label">账号</div>
      <el-input v-model="username" placeholder="请输入账号" @keyup.enter="doLogin" />
      <div class="label">密码</div>
      <el-input v-model="password" type="password" show-password placeholder="请输入密码" @keyup.enter="doLogin" />
      <el-button type="primary" class="login-btn" :loading="loading" @click="doLogin">登 录</el-button>
      <div class="login-hint">默认账号 admin / admin123 · 生产环境请修改密码</div>
    </div>
  </div>
</template>
