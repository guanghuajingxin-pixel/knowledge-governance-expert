<script setup lang="ts">
/**
 * 策略编排：策略列表 + 编排弹窗（条件 → 识别 → 动作 → 执行节点 → 兜底）。
 * 多策略命中同一实体类型时引擎自动取最严格动作；此页只负责声明策略。
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Edit, Delete } from '@element-plus/icons-vue'
import {
  listMaskingPolicies,
  createMaskingPolicy,
  updateMaskingPolicy,
  deleteMaskingPolicy,
  type MaskingPolicy,
  type MaskingPolicyPayload,
  type EntityType,
  type MaskAction,
  type MaskScene,
  type ScopeType,
  type FailureStrategy,
} from '@/api/masking'
import { listKnowledgeLibraries } from '@/api/knowledge-library'
import { listKnowledgeBases } from '@/api/knowledge-base'
import {
  ENTITY_TYPES, ENTITY_LABEL, ACTIONS, ACTION_LABEL, ACTION_EXAMPLE,
  ROLE_OPTIONS, SCENE_OPTIONS, FAILURE_OPTIONS,
} from './constants'

const emit = defineEmits<{ changed: [] }>()

// ===== 列表 =====
const policies = ref<MaskingPolicy[]>([])
const loading = ref(false)

const libraries = ref<{ id: number; name: string }[]>([])
const kbs = ref<{ id: string; name: string }[]>([])
const libraryName = computed(() => Object.fromEntries(libraries.value.map((l) => [String(l.id), l.name])))
const kbName = computed(() => Object.fromEntries(kbs.value.map((k) => [k.id, k.name])))

function scopeText(p: MaskingPolicy): string {
  if (p.scope_type === 'global') return '全局'
  if (p.scope_type === 'library') return `镜像：${libraryName.value[p.scope_id] || p.scope_id}`
  return `本地库：${kbName.value[p.scope_id] || p.scope_id}`
}

function rolesText(p: MaskingPolicy): string {
  return p.user_roles?.length ? p.user_roles.map((r) => roleLabel(r)).join('、') : '全部角色'
}
function roleLabel(r: string): string {
  return ROLE_OPTIONS.find((o) => o.value === r)?.label || r
}
function scenesText(p: MaskingPolicy): string {
  return p.scenes?.length ? p.scenes.map((s) => (s === 'search' ? '检索' : '问答')).join('、') : '全部场景'
}
function nodesText(p: MaskingPolicy): string {
  const parts: string[] = []
  if (p.pre_llm_enabled) parts.push('送LLM前')
  if (p.post_output_enabled) parts.push('输出后')
  return parts.join(' + ') || '未启用'
}
function actionCount(p: MaskingPolicy): number {
  return Object.keys(p.actions || {}).length + (p.dict_types?.length ? 1 : 0) +
    (p.regex_rules?.length || 0) + (p.context_rules?.length || 0)
}

async function loadPolicies() {
  loading.value = true
  try {
    policies.value = await listMaskingPolicies()
  } catch (e: any) {
    ElMessage.error('加载策略失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  loadPolicies()
  try {
    const [libs, kbPage] = await Promise.all([
      listKnowledgeLibraries(),
      listKnowledgeBases({ page: 1, size: 100 }),
    ])
    libraries.value = libs.map((l) => ({ id: l.id, name: l.name }))
    kbs.value = (kbPage.items || []).map((k) => ({ id: k.id, name: k.name }))
  } catch {
    // 下拉降级为手输 scope_id
  }
})

// ===== 启停 =====
function fullPayload(p: MaskingPolicy): MaskingPolicyPayload {
  return {
    name: p.name, description: p.description || '', scope_type: p.scope_type,
    scope_id: p.scope_id || '', priority: p.priority, user_roles: p.user_roles || [],
    scenes: p.scenes || [], regex_rules: p.regex_rules || [], dict_types: p.dict_types || [],
    context_rules: p.context_rules || [], actions: p.actions || {},
    pre_llm_enabled: p.pre_llm_enabled, post_output_enabled: p.post_output_enabled,
    failure_strategy: p.failure_strategy, enabled: p.enabled,
  }
}

async function handleToggle(row: MaskingPolicy) {
  try {
    await updateMaskingPolicy(row.id, { ...fullPayload(row), enabled: !row.enabled })
    row.enabled = !row.enabled
    emit('changed')
  } catch (e: any) {
    ElMessage.error('状态更新失败：' + (e?.message || e))
  }
}

// ===== 删除 =====
async function handleDelete(row: MaskingPolicy) {
  try {
    await ElMessageBox.confirm(
      `确认删除策略「${row.name}」？删除后该策略立即失效。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteMaskingPolicy(row.id)
    ElMessage.success('已删除')
    loadPolicies()
    emit('changed')
  } catch {
    // 用户取消
  }
}

// ===== 编排弹窗 =====
const dialogVisible = ref(false)
const isEdit = ref(false)
const saving = ref(false)
const currentId = ref<number | null>(null)

type RegexRow = { pattern: string; label: string; entity_type: string }
type ContextRow = { keyword: string; entity_type: string }

const form = reactive({
  name: '',
  description: '',
  enabled: true,
  priority: 100,
  scope_type: 'global',
  scope_id: '',
  user_roles: [] as string[],
  scenes: [] as string[],
  dict_types: [] as string[],
  regex_rules: [] as RegexRow[],
  context_rules: [] as ContextRow[],
  actions: {} as Record<string, MaskAction | ''>,
  pre_llm_enabled: true,
  post_output_enabled: true,
  failure_strategy: 'non_sensitive',
})

function openAdd() {
  isEdit.value = false
  currentId.value = null
  Object.assign(form, {
    name: '', description: '', enabled: true, priority: 100,
    scope_type: 'global', scope_id: '', user_roles: [], scenes: [],
    dict_types: [], regex_rules: [], context_rules: [],
    actions: {}, pre_llm_enabled: true, post_output_enabled: true,
    failure_strategy: 'non_sensitive',
  })
  dialogVisible.value = true
}

function openEdit(row: MaskingPolicy) {
  isEdit.value = true
  currentId.value = row.id
  Object.assign(form, {
    name: row.name, description: row.description || '', enabled: row.enabled,
    priority: row.priority, scope_type: row.scope_type, scope_id: row.scope_id || '',
    user_roles: [...(row.user_roles || [])], scenes: [...(row.scenes || [])],
    dict_types: [...(row.dict_types || [])],
    regex_rules: (row.regex_rules || []).map((r) => ({
      pattern: r.pattern || '', label: r.label || '', entity_type: r.entity_type || 'custom',
    })),
    context_rules: (row.context_rules || []).map((r) => ({
      keyword: r.keyword || '', entity_type: r.entity_type || 'custom',
    })),
    actions: { ...(row.actions || {}) } as Record<string, MaskAction | ''>,
    pre_llm_enabled: row.pre_llm_enabled, post_output_enabled: row.post_output_enabled,
    failure_strategy: row.failure_strategy,
  })
  dialogVisible.value = true
}

function addRegexRule() {
  form.regex_rules.push({ pattern: '', label: '', entity_type: 'custom' })
}
function removeRegexRule(i: number) {
  form.regex_rules.splice(i, 1)
}
function addContextRule() {
  form.context_rules.push({ keyword: '', entity_type: 'custom' })
}
function removeContextRule(i: number) {
  form.context_rules.splice(i, 1)
}

function validateRegex(pattern: string): boolean {
  if (!pattern.trim()) return true
  try {
    new RegExp(pattern)
    return true
  } catch {
    return false
  }
}

async function handleSave() {
  if (!form.name.trim()) return ElMessage.warning('请输入策略名称')
  if (form.scope_type !== 'global' && !form.scope_id) return ElMessage.warning('请选择作用域对象')
  const cleanedRegex = form.regex_rules.filter((r) => r.pattern.trim())
  for (const r of cleanedRegex) {
    if (!validateRegex(r.pattern)) return ElMessage.warning(`非法正则表达式：${r.pattern}`)
  }
  const cleanedContext = form.context_rules.filter((r) => r.keyword.trim())
  const actionEntries = Object.entries(form.actions).filter(([, v]) => v) as [EntityType, MaskAction][]
  if (!actionEntries.length && !form.dict_types.length && !cleanedRegex.length && !cleanedContext.length) {
    return ElMessage.warning('请至少配置一项识别方式（词典/正则/上下文）或脱敏动作')
  }
  if (!form.pre_llm_enabled && !form.post_output_enabled) {
    return ElMessage.warning('执行节点至少启用一个（建议保留送LLM前脱敏作为底线）')
  }
  saving.value = true
  const payload: MaskingPolicyPayload = {
    name: form.name.trim(),
    description: form.description,
    enabled: form.enabled,
    priority: form.priority,
    scope_type: form.scope_type as ScopeType,
    scope_id: form.scope_type === 'global' ? '' : form.scope_id,
    user_roles: form.user_roles,
    scenes: form.scenes as MaskScene[],
    dict_types: form.dict_types as EntityType[],
    regex_rules: cleanedRegex.map((r) => ({
      pattern: r.pattern, label: r.label, entity_type: (r.entity_type || 'custom') as EntityType,
    })),
    context_rules: cleanedContext.map((r) => ({
      keyword: r.keyword, entity_type: r.entity_type as EntityType,
    })),
    actions: Object.fromEntries(actionEntries) as Partial<Record<EntityType, MaskAction>>,
    pre_llm_enabled: form.pre_llm_enabled,
    post_output_enabled: form.post_output_enabled,
    failure_strategy: form.failure_strategy as FailureStrategy,
  }
  try {
    if (isEdit.value && currentId.value) {
      await updateMaskingPolicy(currentId.value, payload)
      ElMessage.success('策略已保存')
    } else {
      await createMaskingPolicy(payload)
      ElMessage.success('策略已创建')
    }
    dialogVisible.value = false
    loadPolicies()
    emit('changed')
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="pt-wrap">
    <div class="tab-intro">
      一条策略回答五个问题：对哪类用户（条件）、识别什么敏感实体（识别）、变成什么返回形态（动作）、
      在链路哪个节点生效（执行节点）、识别异常时如何兜底（失败策略）。多策略命中同一实体类型时自动取最严格动作。
    </div>
    <div class="tab-toolbar">
      <el-button :icon="Refresh" :loading="loading" @click="loadPolicies">刷新</el-button>
      <el-button type="primary" :icon="Plus" @click="openAdd">新建策略</el-button>
    </div>

    <el-table :data="policies" v-loading="loading" stripe style="width: 100%"
      empty-text="暂无脱敏策略，点击「新建策略」创建">
      <el-table-column label="策略名称" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <div class="name-cell">
            <span class="p-name">{{ row.name }}</span>
            <span v-if="row.description" class="p-desc">{{ row.description }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="作用域" width="170" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag size="small" :type="row.scope_type === 'global' ? 'primary' : 'info'" effect="plain">
            {{ scopeText(row as MaskingPolicy) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="priority" label="优先级" width="80" align="center" />
      <el-table-column label="适用角色" width="110" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="muted">{{ rolesText(row as MaskingPolicy) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="适用场景" width="100" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="muted">{{ scenesText(row as MaskingPolicy) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="执行节点" width="130">
        <template #default="{ row }">
          <span class="muted">{{ nodesText(row as MaskingPolicy) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="识别方式" width="90" align="center">
        <template #default="{ row }">
          <span class="muted">{{ actionCount(row as MaskingPolicy) }} 项</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <div class="switch-line">
            <el-switch :model-value="row.enabled" @change="handleToggle(row as MaskingPolicy)" />
            <span class="switch-text" :class="{ off: !row.enabled }">{{ row.enabled ? '生效中' : '已停用' }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <div class="action-btns">
            <el-button link type="primary" :icon="Edit" size="small" @click="openEdit(row as MaskingPolicy)">编辑</el-button>
            <el-button link type="danger" :icon="Delete" size="small" @click="handleDelete(row as MaskingPolicy)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑策略' : '新建策略'" width="720px"
      :close-on-click-modal="false" top="4vh" class="policy-dialog">
      <el-form :model="form" label-width="92px" class="policy-form">
        <div class="section-title">基本信息</div>
        <div class="form-row">
          <el-form-item label="策略名称" required class="grow">
            <el-input v-model="form.name" maxlength="100" placeholder="如：薪酬信息脱敏" />
          </el-form-item>
          <el-form-item label="优先级">
            <el-input-number v-model="form.priority" :min="1" :max="9999" controls-position="right" style="width: 120px" />
          </el-form-item>
        </div>
        <el-form-item label="描述">
          <el-input v-model="form.description" maxlength="200" placeholder="可选，说明该策略的治理目标" />
        </el-form-item>
        <el-form-item label="作用域">
          <el-radio-group v-model="form.scope_type">
            <el-radio-button value="global">全局</el-radio-button>
            <el-radio-button value="library">知识库镜像</el-radio-button>
            <el-radio-button value="kb">本地知识库</el-radio-button>
          </el-radio-group>
          <el-select v-if="form.scope_type === 'library'" v-model="form.scope_id" filterable
            placeholder="选择知识库镜像" class="scope-select">
            <el-option v-for="l in libraries" :key="l.id" :label="l.name" :value="String(l.id)" />
          </el-select>
          <el-select v-if="form.scope_type === 'kb'" v-model="form.scope_id" filterable
            placeholder="选择本地知识库" class="scope-select">
            <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
          </el-select>
        </el-form-item>

        <div class="section-title">触发条件</div>
        <el-form-item label="适用角色">
          <el-checkbox-group v-model="form.user_roles" class="inline-check">
            <el-checkbox v-for="r in ROLE_OPTIONS" :key="r.value" :value="r.value">{{ r.label }}</el-checkbox>
          </el-checkbox-group>
          <div class="form-hint">不勾选 = 对全部角色生效</div>
        </el-form-item>
        <el-form-item label="适用场景">
          <el-checkbox-group v-model="form.scenes" class="inline-check">
            <el-checkbox v-for="s in SCENE_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</el-checkbox>
          </el-checkbox-group>
          <div class="form-hint">不勾选 = 对统一检索与 RAG 问答均生效</div>
        </el-form-item>

        <div class="section-title">敏感实体识别</div>
        <el-form-item label="敏感词典">
          <el-checkbox-group v-model="form.dict_types" class="inline-check">
            <el-checkbox v-for="t in ENTITY_TYPES" :key="t" :value="t">{{ ENTITY_LABEL[t] }}</el-checkbox>
          </el-checkbox-group>
          <div class="form-hint">命中「敏感词典」页签中对应类型的登记词条</div>
        </el-form-item>
        <el-form-item label="自定义正则">
          <div class="rule-list">
            <div v-for="(r, i) in form.regex_rules" :key="i" class="rule-row">
              <el-input v-model="r.pattern" placeholder="正则表达式，如 (?&lt;!\\d)\\d{15}(?!\\d)" class="rule-pattern" />
              <el-input v-model="r.label" placeholder="规则名称" maxlength="50" class="rule-label" />
              <el-select v-model="r.entity_type" class="rule-type">
                <el-option v-for="t in ENTITY_TYPES" :key="t" :label="ENTITY_LABEL[t]" :value="t" />
              </el-select>
              <el-button link type="danger" @click="removeRegexRule(i)">删除</el-button>
            </div>
            <el-button link type="primary" :icon="Plus" @click="addRegexRule">添加正则规则</el-button>
          </div>
        </el-form-item>
        <el-form-item label="上下文规则">
          <div class="rule-list">
            <div v-for="(r, i) in form.context_rules" :key="i" class="rule-row">
              <el-input v-model="r.keyword" placeholder="关键词，如：薪酬" maxlength="50" class="rule-label" />
              <span class="rule-sep">邻近的</span>
              <el-select v-model="r.entity_type" class="rule-type">
                <el-option v-for="t in ENTITY_TYPES" :key="t" :label="ENTITY_LABEL[t]" :value="t" />
              </el-select>
              <span class="rule-sep">识别为敏感</span>
              <el-button link type="danger" @click="removeContextRule(i)">删除</el-button>
            </div>
            <el-button link type="primary" :icon="Plus" @click="addContextRule">添加上下文规则</el-button>
          </div>
        </el-form-item>

        <div class="section-title">脱敏动作</div>
        <el-form-item label="动作配置">
          <div class="action-grid">
            <div v-for="t in ENTITY_TYPES" :key="t" class="action-row">
              <el-tag :type="t === 'custom' ? 'info' : 'warning'" size="small" effect="light" class="action-type">
                {{ ENTITY_LABEL[t] }}
              </el-tag>
              <el-select v-model="form.actions[t]" clearable placeholder="不脱敏" class="action-select">
                <el-option v-for="a in ACTIONS" :key="a" :value="a" :label="ACTION_LABEL[a]">
                  <span>{{ ACTION_LABEL[a] }}</span>
                  <span class="opt-example">{{ ACTION_EXAMPLE[a] }}</span>
                </el-option>
              </el-select>
            </div>
          </div>
          <div class="form-hint">识别出的实体按所选动作处理；选「不脱敏」表示该类型不做处理（清空即关闭）</div>
        </el-form-item>

        <div class="section-title">执行节点与兜底</div>
        <el-form-item label="执行节点">
          <div class="switch-line">
            <el-switch v-model="form.pre_llm_enabled" />
            <span class="switch-text" :class="{ off: !form.pre_llm_enabled }">送LLM前脱敏（底线，推荐开启）</span>
          </div>
          <div class="switch-line node-gap">
            <el-switch v-model="form.post_output_enabled" />
            <span class="switch-text" :class="{ off: !form.post_output_enabled }">输出后二次过滤</span>
          </div>
        </el-form-item>
        <el-form-item label="失败策略">
          <el-radio-group v-model="form.failure_strategy">
            <el-radio-button v-for="f in FAILURE_OPTIONS" :key="f.value" :value="f.value">{{ f.label }}</el-radio-button>
          </el-radio-group>
          <div class="form-hint">{{ FAILURE_OPTIONS.find((f) => f.value === form.failure_strategy)?.tip }}</div>
        </el-form-item>
        <el-form-item label="启用状态">
          <div class="switch-line">
            <el-switch v-model="form.enabled" />
            <span class="switch-text" :class="{ off: !form.enabled }">{{ form.enabled ? '生效中' : '已停用' }}</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">{{ isEdit ? '保存修改' : '创建策略' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.pt-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tab-intro {
  font-size: 13px;
  color: #909399;
  line-height: 1.6;
}

.tab-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.tab-toolbar .el-button + .el-button {
  margin-left: 0;
}

.name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.p-name {
  font-weight: 600;
  color: #303133;
}

.p-desc {
  font-size: 12px;
  color: #999;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.muted {
  color: #909399;
  font-size: 13px;
}

.switch-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.node-gap {
  margin-top: 8px;
}

.switch-text {
  font-size: 12px;
  color: var(--el-color-success);
}

.switch-text.off {
  color: var(--el-color-info);
}

.action-btns {
  display: flex;
  gap: 4px;
}

/* 弹窗表单 */
.form-row {
  display: flex;
  gap: 16px;
}

.form-row .grow {
  flex: 1;
  min-width: 0;
}

.scope-select {
  margin-left: 12px;
  width: 220px;
}

.inline-check {
  display: inline-flex;
  flex-wrap: wrap;
  column-gap: 4px;
}

.form-hint {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
  width: 100%;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin: 8px 0 12px;
  padding-left: 8px;
  border-left: 3px solid var(--el-color-primary);
}

.rule-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rule-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rule-pattern {
  flex: 2;
  min-width: 0;
}

.rule-label {
  flex: 1;
  min-width: 0;
}

.rule-type {
  width: 110px;
  flex-shrink: 0;
}

.rule-sep {
  font-size: 12px;
  color: #999;
  flex-shrink: 0;
}

.action-grid {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.action-type {
  width: 72px;
  justify-content: center;
  flex-shrink: 0;
}

.action-select {
  width: 220px;
}

.opt-example {
  float: right;
  font-size: 12px;
  color: #999;
}

.policy-form {
  padding: 0 8px;
}
</style>
