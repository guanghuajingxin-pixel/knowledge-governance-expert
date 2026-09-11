<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSettings, updateSettings } from '@/api/settings'
import { errMsg } from '@/api/http'
import type { Settings } from '@/types'

const form = reactive<Settings>({
  dingtalk_webhook: '',
  alert_failure_threshold: 1,
  default_delete_policy: 'keep',
  export_format: 'markdown',
  max_depth: 10,
  dify_wait_indexing: false,
  dingtalk_operator_id: '',
})
const loginEnabled = ref(true)
const intranetOnly = ref(true)
const saving = ref(false)

async function load() {
  try { Object.assign(form, await getSettings()) } catch (e) { ElMessage.error(errMsg(e)) }
}
async function save() {
  saving.value = true
  try {
    await updateSettings({ ...form })
    ElMessage.success('设置已保存')
  } catch (e) { ElMessage.error(errMsg(e)) } finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <div>
    <div class="page-head"><div><h2>设置</h2><div class="desc">全局参数与安全配置</div></div></div>
    <div class="grid-2">
      <div class="card">
        <div class="sect-title">安全</div>
        <div class="setting-row">
          <div><div>后台登录</div><div class="hint">启用后访问管理后台需要账号密码</div></div>
          <el-switch v-model="loginEnabled" @change="() => ElMessage.success('后台登录设置已更新')" />
        </div>
        <div class="setting-row">
          <div><div>仅限内网访问</div><div class="hint">关闭登录时限制来源 IP 为内网</div></div>
          <el-switch v-model="intranetOnly" @change="() => ElMessage.success('内网限制已更新')" />
        </div>
      </div>
      <div class="card">
        <div class="sect-title">告警与全局默认</div>
        <el-form label-position="top">
          <el-form-item label="钉钉告警 Webhook"><el-input v-model="form.dingtalk_webhook" placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." /></el-form-item>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
            <el-form-item label="失败告警阈值">
              <el-select v-model="form.alert_failure_threshold" style="width:100%">
                <el-option label="≥ 1 个失败即告警" :value="1" /><el-option label="≥ 3 个失败" :value="3" /><el-option label="≥ 10 个失败" :value="10" />
              </el-select>
            </el-form-item>
            <el-form-item label="默认删除策略">
              <el-select v-model="form.default_delete_policy" style="width:100%">
                <el-option label="同步删除（源删除则删 Dify 文档）" value="sync" /><el-option label="保留（仅清理状态）" value="keep" />
              </el-select>
            </el-form-item>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
            <el-form-item label="在线文档导出格式">
              <el-select v-model="form.export_format" style="width:100%">
                <el-option label="markdown" value="markdown" /><el-option label="docx" value="docx" /><el-option label="pdf" value="pdf" />
              </el-select>
            </el-form-item>
            <el-form-item label="目录遍历最大深度"><el-input-number v-model="form.max_depth" :min="1" :max="20" style="width:100%" /></el-form-item>
          </div>
          <el-form-item label="钉钉操作员 unionId"><el-input v-model="form.dingtalk_operator_id" /></el-form-item>
          <el-form-item label="上传后等待 Dify 索引完成"><el-switch v-model="form.dify_wait_indexing" /></el-form-item>
        </el-form>
        <el-button type="primary" :loading="saving" @click="save">保存设置</el-button>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <div class="sect-title">系统信息</div>
      <div class="kvs">
        <div class="kv"><div class="k">服务版本</div><div class="v">v0.1.0</div></div>
        <div class="kv"><div class="k">部署形态</div><div class="v">单服务一体化（Web + API + 同步引擎）</div></div>
        <div class="kv"><div class="k">状态库</div><div class="v">SQLite</div></div>
        <div class="kv"><div class="k">健康检查</div><div class="v">正常</div></div>
      </div>
    </div>
  </div>
</template>
