<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock, Reading } from '@element-plus/icons-vue'
import type { LoginResponse } from '@/types/user'
import { authConfig, authError, sso } from '@/auth/session'
import { safeRedirect } from '@/utils/dingtalk-auth'
import { ElAlert, ElButton } from 'element-plus'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

onMounted(async () => {
  if (authConfig.value?.provider !== 'keycloak') return
  // keycloak 模式（含本地调试）：一律走统一登录（本地经 scripts/start-dev.sh keycloak
  // 建立 166.2 身份中心隧道）；Direct opens and portal "open in new window" links must
  // start the same Keycloak flow automatically; check-sso alone only checks for a session
  // and otherwise leaves users on a login page that requires another click.
  await handleSsoLogin()
})

/** 登录成功统一落地：token/userInfo 入 store 后回原目标 */
function postLogin(res: LoginResponse) {
  userStore.applyLogin(res)
  router.push(safeRedirect(route.query.redirect, '/chat'))
}

async function handleLogin() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      const res = await userStore.login(form)
      ElMessage.success('登录成功')
      postLogin(res)
    } catch (e) {
      // 登录接口 401 由 request.ts 放行至此；展示后端 detail 或默认提示
      const err = e as { response?: { data?: { detail?: string } } }
      ElMessage.error(err?.response?.data?.detail || '用户名或密码错误')
    } finally {
      loading.value = false
    }
  })
}

function reloadPage() { window.location.reload() }
async function handleSsoLogin() {
  try { await sso.login(safeRedirect(route.query.redirect, '/chat')) }
  catch (error) { authError.value = error instanceof Error ? error.message : '统一登录失败，请重试。' }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <el-icon size="40" color="var(--el-color-primary)"><Reading /></el-icon>
        <h2>知识治理专家</h2>
      </div>
      <el-alert v-if="authError" :title="authError" type="error" :closable="false" show-icon />
      <div v-if="authConfig?.provider === 'keycloak'" class="sso-pane">
        <p class="sso-desc">使用杰克科技统一账号，与 AIGC 门户共享登录身份和权限。</p>
        <el-button type="primary" style="width: 100%" @click="handleSsoLogin">使用企业统一账号登录</el-button>
      </div>
      <el-button v-if="!authConfig" style="width: 100%; margin-top: 16px" @click="reloadPage">重试连接</el-button>
      <el-form
        v-if="authConfig?.provider === 'local'"
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        @keyup.enter="handleLogin"
      >
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="密码" :prefix-icon="Lock" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" style="width: 100%" @click="handleLogin">
            登录
          </el-button>
        </el-form-item>
        <div class="login-tip">本地开发登录通道；生产环境请使用统一账号登录。</div>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.login-card {
  width: 400px;
  padding: 40px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}
.login-header {
  text-align: center;
  margin-bottom: 16px;
}
.login-header h2 {
  margin: 12px 0 0;
  color: #303133;
}
.login-tip {
  text-align: center;
  color: #909399;
  font-size: 12px;
  margin-top: 8px;
}
.sso-pane {
  padding: 8px 0 4px;
}
.sso-desc {
  margin: 0 0 20px;
  color: #606266;
  font-size: 13px;
  line-height: 1.7;
  text-align: center;
}
</style>
