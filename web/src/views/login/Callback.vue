<script setup lang="ts">
// 钉钉扫码授权回调：?code=&state= → state 防伪校验 → 登录（未登录）或绑定（已登录）
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { bindDingtalkBinding, dingtalkLogin } from '@/api/auth'
import { loginDestination, safeRedirect, takeDingtalkOAuthState } from '@/utils/dingtalk-auth'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const loading = ref(true)
const tip = ref('正在处理钉钉授权…')

function fail(message: string) {
  ElMessage.error(message)
  router.replace('/login')
}

onMounted(async () => {
  const code = typeof route.query.code === 'string' ? route.query.code : ''
  const state = typeof route.query.state === 'string' ? route.query.state : ''
  if (!code) {
    fail('钉钉授权失败：未获取到授权码')
    return
  }
  // state 与发起授权时留存的值比对（单次消费），防 CSRF
  const saved = takeDingtalkOAuthState()
  if (!saved || saved !== state) {
    fail('授权状态校验失败，请重新发起登录')
    return
  }

  try {
    if (userStore.token) {
      // 已登录（个人账户页「绑定钉钉」发起）：把钉钉身份附加到当前账号后回账户页
      tip.value = '正在绑定钉钉账号…'
      const res = await bindDingtalkBinding(code)
      userStore.setToken(res.access_token)
      userStore.setUserInfo(res.user)
      ElMessage.success('钉钉绑定成功')
      router.replace('/settings/account')
      return
    }
    // 未登录：扫码登录（首次自动建档，may 返回 must_set_password）
    tip.value = '正在登录…'
    const res = await dingtalkLogin({ auth_code: code, channel: 'qr' })
    userStore.applyLogin(res)
    const redirect = safeRedirect(route.query.redirect, '/chat')
    router.replace(loginDestination(res, redirect))
  } catch (e) {
    const err = e as { response?: { data?: { detail?: string } } }
    fail(err?.response?.data?.detail || '钉钉登录失败，请重试')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading" class="callback-page" element-loading-text="">
    <div class="callback-tip">{{ tip }}</div>
  </div>
</template>

<style scoped>
.callback-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.callback-tip {
  color: #fff;
  font-size: 14px;
  text-align: center;
  margin-top: 64px;
}
</style>
