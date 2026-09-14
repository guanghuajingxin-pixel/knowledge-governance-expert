<script setup lang="ts">
/**
 * 检索返回脱敏策略控制台。
 * 管理对象是「检索返回策略」而非数据本身：条件 → 识别 → 动作 → 执行节点 → 兜底 → 审计。
 * 顶部为全局策略（总开关 / 执行节点 / 失败策略 / 用户提示语），
 * 五个页签：策略编排 / 敏感词典 / 豁免管理 / 脱敏审计 / 预览沙箱。
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'
import {
  getMaskingGlobal,
  putMaskingGlobal,
  type MaskingGlobal,
} from '@/api/masking'
import { FAILURE_OPTIONS } from './constants'
import PolicyTab from './PolicyTab.vue'
import DictTab from './DictTab.vue'
import ExemptionTab from './ExemptionTab.vue'
import AuditTab from './AuditTab.vue'
import SandboxTab from './SandboxTab.vue'

const activeTab = ref('policy')

// ===== 全局策略 =====
const globalCfg = reactive<MaskingGlobal>({
  enabled: true,
  pre_llm: true,
  post_output: true,
  failure_strategy: 'non_sensitive',
  hint: '部分内容因权限隐藏',
})
const globalLoaded = ref(false)
const globalDialog = ref(false)
const savingGlobal = ref(false)
const draft = reactive<MaskingGlobal>({ ...globalCfg })

async function loadGlobal() {
  try {
    Object.assign(globalCfg, await getMaskingGlobal())
    globalLoaded.value = true
  } catch (e: any) {
    ElMessage.error('加载全局策略失败：' + (e?.message || e))
  }
}

onMounted(loadGlobal)

function openGlobalDialog() {
  Object.assign(draft, globalCfg)
  globalDialog.value = true
}

async function saveGlobal() {
  savingGlobal.value = true
  try {
    Object.assign(globalCfg, await putMaskingGlobal({ ...draft }))
    globalDialog.value = false
    ElMessage.success('全局策略已保存')
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    savingGlobal.value = false
  }
}

function onPoliciesChanged() {
  // 策略变更影响沙箱/审计的即时正确性；全局条不受影响，此处预留联动
}
</script>

<template>
  <div class="mk-page">
    <!-- 顶部：全局策略条 -->
    <div class="mk-global" v-loading="!globalLoaded">
      <div class="global-status">
        <span class="global-title">检索返回脱敏策略控制台</span>
        <el-tag :type="globalCfg.enabled ? 'success' : 'info'" size="small" effect="light">
          {{ globalCfg.enabled ? '脱敏总开关：开启' : '脱敏总开关：关闭' }}
        </el-tag>
        <el-tag v-if="globalCfg.enabled && globalCfg.pre_llm" type="primary" size="small" effect="plain">送LLM前</el-tag>
        <el-tag v-if="globalCfg.enabled && globalCfg.post_output" type="primary" size="small" effect="plain">输出后过滤</el-tag>
        <span class="global-hint">兜底：{{ FAILURE_OPTIONS.find((f) => f.value === globalCfg.failure_strategy)?.label || globalCfg.failure_strategy }}</span>
        <span v-if="globalCfg.hint" class="global-hint muted">提示语「{{ globalCfg.hint }}」</span>
      </div>
      <el-button :icon="Setting" @click="openGlobalDialog">全局策略</el-button>
    </div>

    <!-- 五大功能页签 -->
    <div class="mk-body">
      <el-tabs v-model="activeTab" class="mk-tabs">
        <el-tab-pane label="策略编排" name="policy" lazy>
          <PolicyTab @changed="onPoliciesChanged" />
        </el-tab-pane>
        <el-tab-pane label="敏感词典" name="dict" lazy>
          <DictTab />
        </el-tab-pane>
        <el-tab-pane label="豁免管理" name="exemption" lazy>
          <ExemptionTab />
        </el-tab-pane>
        <el-tab-pane label="脱敏审计" name="audit" lazy>
          <AuditTab />
        </el-tab-pane>
        <el-tab-pane label="预览沙箱" name="sandbox" lazy>
          <SandboxTab />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 全局策略弹窗 -->
    <el-dialog v-model="globalDialog" title="全局策略" width="560px" :close-on-click-modal="false">
      <el-form label-width="110px" class="global-form">
        <el-form-item label="脱敏总开关">
          <div class="switch-line">
            <el-switch v-model="draft.enabled" />
            <span class="switch-text" :class="{ off: !draft.enabled }">{{ draft.enabled ? '开启' : '关闭（全部接口零开销直通）' }}</span>
          </div>
        </el-form-item>
        <el-form-item label="送LLM前脱敏">
          <div class="switch-line">
            <el-switch v-model="draft.pre_llm" />
            <span class="switch-text" :class="{ off: !draft.pre_llm }">底线节点：LLM 不接触明文（推荐开启）</span>
          </div>
        </el-form-item>
        <el-form-item label="输出后二次过滤">
          <div class="switch-line">
            <el-switch v-model="draft.post_output" />
            <span class="switch-text" :class="{ off: !draft.post_output }">对检索结果与问答输出做二次扫描</span>
          </div>
        </el-form-item>
        <el-form-item label="失败策略">
          <el-radio-group v-model="draft.failure_strategy">
            <el-radio-button v-for="f in FAILURE_OPTIONS" :key="f.value" :value="f.value">{{ f.label }}</el-radio-button>
          </el-radio-group>
          <div class="form-hint">{{ FAILURE_OPTIONS.find((f) => f.value === draft.failure_strategy)?.tip }}</div>
        </el-form-item>
        <el-form-item label="用户提示语">
          <el-input v-model="draft.hint" maxlength="100" placeholder="如：部分内容因权限隐藏" show-word-limit />
          <div class="form-hint">内容被脱敏时向用户展示的说明，避免静默修改导致误解</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="globalDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingGlobal" @click="saveGlobal">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mk-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 16px 20px 20px;
  gap: 12px;
}

/* 全局策略条 */
.mk-global {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-radius: 8px;
  padding: 12px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  flex-shrink: 0;
}

.global-status {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.global-title {
  font-size: 15px;
  font-weight: 700;
  color: #303133;
  margin-right: 4px;
}

.global-hint {
  font-size: 13px;
  color: #606266;
}

.global-hint.muted {
  color: #909399;
}

/* 页签区 */
.mk-body {
  flex: 1;
  min-height: 0;
  background: #fff;
  border-radius: 8px;
  padding: 4px 16px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
}

.mk-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.mk-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.mk-tabs :deep(.el-tab-pane) {
  height: 100%;
}

/* 全局弹窗 */
.global-form {
  padding: 0 8px;
}

.switch-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.switch-text {
  font-size: 12px;
  color: var(--el-color-success);
}

.switch-text.off {
  color: var(--el-color-info);
}

.form-hint {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
  width: 100%;
}
</style>
