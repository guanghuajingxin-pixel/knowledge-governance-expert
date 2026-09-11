<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getAgentConfig, updateAgentConfig,
  getPersona, savePersona, getSkill, saveSkill,
  getAgentTools, listSkills, saveSkillDoc as putSkillDoc, deleteSkillDoc, importSkillDoc,
  type AgentConfig, type AgentTool, type SkillDoc,
} from '@/api/agent'
import { listEnabledLlmModels } from '@/api/settings'

const loading = ref(false)
const saving = ref(false)
const activeTab = ref('basic')
const activeCollapse = ref(['model', 'knowledge', 'tools', 'greeting', 'planning', 'subagent', 'memory', 'deep', 'hyper'])

const form = reactive<AgentConfig>({
  agent_name: '杰克百晓生',
  models: [],
  retrieval_mode: 'smart',
  greeting_enabled: true,
  greeting: '',
  suggested_questions: [],
  follow_up_enabled: true,
  tools_enabled: {},
  planning_enabled: true,
  subagent_enabled: false,
  long_memory_enabled: true,
  deep_think_default: false,
  temperature: 0,
  top_p: 0.9,
  max_tokens: 4096,
  top_k: 8,
  max_retrieval_rounds: 2,
})

// 工具目录（名称/描述来自后端 /agent/tools，开关状态保存于 form.tools_enabled）
const toolCatalog = ref<AgentTool[]>([])

// 仅可选择系统已接入（生效）的模型；is_default 为系统配置里的默认模型
const modelOptions = ref<Array<{ model: string; profile_id: string; profile_name: string; is_default: boolean }>>([])

async function load() {
  loading.value = true
  try {
    const [cfg, toolsRes] = await Promise.all([getAgentConfig(), getAgentTools().catch(() => null)])
    Object.assign(form, cfg)
    toolCatalog.value = toolsRes?.tools || []
    // 目录补齐 form.tools_enabled 中缺失的 key（默认启用）
    toolCatalog.value.forEach((t) => {
      if (form.tools_enabled[t.key] === undefined) form.tools_enabled[t.key] = t.enabled
    })
  } catch {
    ElMessage.error('加载智能体配置失败')
  } finally {
    loading.value = false
  }
  // 拉取系统已接入（生效）的模型作为候选，仅可选择、不允许手输模型名
  try {
    const res = await listEnabledLlmModels()
    const seen = new Map<string, { model: string; profile_id: string; profile_name: string; is_default: boolean }>()
    for (const m of res.models || []) {
      const prev = seen.get(m.model)
      // 同名模型跨配置去重，优先保留带默认标记的条目
      if (!prev || (!prev.is_default && m.is_default)) {
        seen.set(m.model, { model: m.model, profile_id: m.profile_id, profile_name: m.profile_name, is_default: !!m.is_default })
      }
    }
    modelOptions.value = [...seen.values()]
    // 未配置过模型时，默认选中系统配置里的默认模型
    if (!form.models.length && modelOptions.value.length) {
      const def = modelOptions.value.find((m) => m.is_default) || modelOptions.value[0]
      form.models = [def.model]
    }
  } catch {
    /* 未配置 LLM 时忽略 */
  }
}

async function save() {
  if (form.models.length > 10) {
    ElMessage.error('模型最多选择 10 个')
    return
  }
  saving.value = true
  try {
    await updateAgentConfig({ ...form })
    ElMessage.success('智能体配置已保存')
  } catch {
    ElMessage.error('保存失败，请稍后重试')
  } finally {
    saving.value = false
  }
}

// ============ 人格（SOUL）与技能（SKILL）提示词编辑 ============
const promptLoading = ref(false)
const personaSaving = ref(false)
const skillSaving = ref(false)
const personaLoaded = ref(false)
const skillLoaded = ref(false)

const persona = reactive({ content: '', saved: '', custom: false, default: '' })
const skill = reactive({ content: '', saved: '', custom: false, default: '' })

async function loadPrompts() {
  promptLoading.value = true
  try {
    const [p, s] = await Promise.all([getPersona(), getSkill()])
    persona.content = p.content; persona.saved = p.content; persona.custom = p.custom; persona.default = p.default
    skill.content = s.content; skill.saved = s.content; skill.custom = s.custom; skill.default = s.default
    personaLoaded.value = true
    skillLoaded.value = true
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '人格/技能配置加载失败（请确认 DeerFlow 服务已启动）')
  } finally {
    promptLoading.value = false
  }
}

// 切到「人格与技能 / 技能库」Tab 时懒加载
function onTabChange(name: string | number) {
  if (name === 'prompt' && !personaLoaded.value) loadPrompts()
  if (name === 'skills' && !skillsLoaded.value) {
    skillsLoaded.value = true
    loadSkills()
  }
}

async function savePersonaDoc() {
  if (!persona.content.trim()) {
    ElMessage.warning('人格内容不能为空')
    return
  }
  personaSaving.value = true
  try {
    const res = await savePersona({ content: persona.content })
    persona.saved = persona.content
    persona.custom = res.custom
    ElMessage.success('人格已保存至兼容服务')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    personaSaving.value = false
  }
}

async function resetPersonaDoc() {
  try {
    await ElMessageBox.confirm('确定恢复为默认人格模板？当前自定义内容将被清除。', '恢复默认', { type: 'warning' })
    personaSaving.value = true
    const res = await savePersona({ reset: true })
    persona.content = persona.default
    persona.saved = persona.default
    persona.custom = res.custom
    ElMessage.success('已恢复默认人格')
  } catch {
    /* 用户取消 */
  } finally {
    personaSaving.value = false
  }
}

async function saveSkillDoc() {
  if (!skill.content.trim()) {
    ElMessage.warning('技能内容不能为空')
    return
  }
  skillSaving.value = true
  try {
    const res = await saveSkill({ content: skill.content })
    skill.saved = skill.content
    skill.custom = res.custom
    ElMessage.success('技能已保存至兼容服务')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    skillSaving.value = false
  }
}

async function resetSkillDoc() {
  try {
    await ElMessageBox.confirm('确定恢复为默认技能模板？当前自定义内容将被清除。', '恢复默认', { type: 'warning' })
    skillSaving.value = true
    const res = await saveSkill({ reset: true })
    skill.content = skill.default
    skill.saved = skill.default
    skill.custom = res.custom
    ElMessage.success('已恢复默认技能')
  } catch {
    /* 用户取消 */
  } finally {
    skillSaving.value = false
  }
}

onMounted(load)

// ============ 技能库管理（ClawHub/Agent Skills 通用结构） ============
const skills = ref<SkillDoc[]>([])
const skillsLoading = ref(false)
const skillsLoaded = ref(false)
const skillDialogVisible = ref(false)
const skillDialogTitle = ref('新建技能')
const skillFormSaving = ref(false)
const skillForm = reactive({ slug: '', name: '', description: '', content: '', enabled: true })
const importInput = ref<HTMLInputElement | null>(null)
const importing = ref(false)

const SKILL_MD_TEMPLATE = `---
name: my-skill
description: 一句话说明这个技能在什么场景下使用（智能体会据此判断是否调用）
---

# 技能说明

## 适用场景
- 什么情况下应该使用本技能

## 执行步骤
1. 第一步做什么
2. 第二步做什么

## 注意事项
- 约束与规范
`

async function loadSkills() {
  skillsLoading.value = true
  try {
    const res = await listSkills()
    skills.value = (res.skills || []).filter((s) => !s.builtin)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '技能库加载失败（请确认 DeerFlow 服务已启动）')
  } finally {
    skillsLoading.value = false
  }
}

function openCreateSkill() {
  skillDialogTitle.value = '新建技能'
  Object.assign(skillForm, {
    slug: '', name: '', description: '',
    content: SKILL_MD_TEMPLATE, enabled: true,
  })
  skillDialogVisible.value = true
}

function openEditSkill(s: SkillDoc) {
  skillDialogTitle.value = `编辑技能 · ${s.name}`
  Object.assign(skillForm, {
    slug: s.slug,
    name: s.name,
    description: s.description,
    content: s.content,
    enabled: s.enabled,
  })
  skillDialogVisible.value = true
}

async function saveSkillForm() {
  if (!skillForm.name.trim()) {
    ElMessage.warning('技能名称不能为空')
    return
  }
  if (!skillForm.content.trim()) {
    ElMessage.warning('SKILL.md 内容不能为空')
    return
  }
  skillFormSaving.value = true
  try {
    await putSkillDoc({
      name: skillForm.name.trim(),
      slug: skillForm.slug,
      description: skillForm.description.trim(),
      content: skillForm.content,
      enabled: skillForm.enabled,
    })
    ElMessage.success('技能已保存至兼容服务')
    skillDialogVisible.value = false
    await loadSkills()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    skillFormSaving.value = false
  }
}

async function toggleSkill(s: SkillDoc, enabled: boolean) {
  try {
    await putSkillDoc({ name: s.name, description: s.description, content: s.content, enabled })
    s.enabled = enabled
    ElMessage.success(enabled ? '技能已启用' : '技能已停用（内容保留）')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function removeSkill(s: SkillDoc) {
  try {
    await ElMessageBox.confirm(`确认删除技能「${s.name}」？删除后不可恢复。`, '删除技能', { type: 'warning' })
    await deleteSkillDoc(s.slug)
    ElMessage.success('技能已删除')
    await loadSkills()
  } catch {
    /* 取消 */
  }
}

function triggerImport() {
  importInput.value?.click()
}

async function onImportFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importing.value = true
  try {
    const res = await importSkillDoc(file, true)
    if (res.ok === false) {
      ElMessage.error('导入失败')
    } else {
      ElMessage.success(`技能「${res.name || file.name}」导入成功`)
      await loadSkills()
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '导入失败（需为含 SKILL.md 的 zip 包或 .md 文件）')
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <div class="agent-config-page" v-loading="loading">
    <div class="page-head">
      <div>
        <h2 class="page-title">智能体配置</h2>
        <p class="page-sub">配置企业知识检索、钉钉补查与会话上下文；回答须通过原文依据核验。</p>
      </div>
      <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
    </div>

    <el-tabs v-model="activeTab" class="cfg-tabs" @tab-change="onTabChange">
      <!-- ============ 基础设置 ============ -->
      <el-tab-pane label="基础设置" name="basic">
        <el-collapse v-model="activeCollapse" class="cfg-collapse">
          <!-- 模型 -->
          <el-collapse-item name="model">
            <template #title>
              <span class="card-title"><span class="card-ico ico-model">🧊</span> 模型
                <span class="card-hint">仅可选择系统已接入的模型（最多 10 个）；问答页模型下拉仅展示此列表</span>
              </span>
            </template>
            <el-select
              v-model="form.models"
              multiple
              filterable
              :reserve-keyword="false"
              placeholder="选择系统已接入的模型，最多 10 个"
              class="full-width"
            >
              <el-option
                v-for="m in modelOptions"
                :key="`${m.profile_id}-${m.model}`"
                :label="m.profile_name ? `${m.model}（${m.profile_name}）` : m.model"
                :value="m.model"
              >
                <span>{{ m.model }}</span>
                <span v-if="m.is_default" style="float: right; color: #409eff; font-size: 12px">默认</span>
              </el-option>
            </el-select>
          </el-collapse-item>

          <!-- 知识库 -->
          <el-collapse-item name="knowledge">
            <template #title>
              <span class="card-title"><span class="card-ico ico-kb">📚</span> 知识库
                <el-radio-group v-model="form.retrieval_mode" size="small" class="mode-radio" @click.stop>
                  <el-radio-button value="force">强制调用</el-radio-button>
                  <el-radio-button value="smart">智能调用</el-radio-button>
                </el-radio-group>
              </span>
            </template>
            <div class="mode-desc">
              <p><b>强制调用</b>：每个问题（含问候寒暄）都检索知识库后再回答，答案严格来自知识库。</p>
              <p><b>智能调用</b>：闲聊问候直接应答，业务问题先检索知识库；原文不能覆盖问题时补查，仍不足则尝试钉钉 DWS。</p>
            </div>
          </el-collapse-item>

          <!-- 工具 -->
          <el-collapse-item name="tools">
            <template #title>
              <span class="card-title"><span class="card-ico ico-tool">🧰</span> 工具
                <span class="card-hint">智能问答可调用的工具，停用后智能体不再使用该能力</span>
              </span>
            </template>
            <div class="tool-list">
              <div v-for="t in toolCatalog" :key="t.key" class="tool-item">
                <div class="tool-info">
                  <span class="tool-name">{{ t.name }}</span>
                  <span class="tool-desc">{{ t.desc }}</span>
                </div>
                <el-switch v-model="form.tools_enabled[t.key]" :disabled="t.key === 'present_files'" :aria-label="t.name" />
              </div>
            </div>
          </el-collapse-item>

          <!-- 对话开场白 -->
          <el-collapse-item name="greeting">
            <template #title>
              <span class="card-title"><span class="card-ico ico-greet">💬</span> 对话开场白
                <el-switch v-model="form.greeting_enabled" class="title-switch" @click.stop />
              </span>
            </template>
            <el-input
              v-model="form.greeting"
              type="textarea"
              :rows="3"
              placeholder="进入问答页时展示的欢迎语"
              class="full-width"
            />
            <div class="sub-label">推荐问题（回车添加，最多 6 个）</div>
            <el-select
              v-model="form.suggested_questions"
              multiple
              filterable
              allow-create
              default-first-option
              :reserve-keyword="false"
              placeholder="输入推荐问题后回车"
              class="full-width"
            />
          </el-collapse-item>

          <!-- 下一步问题建议 -->
          <el-collapse-item name="followup">
            <template #title>
              <span class="card-title"><span class="card-ico ico-follow">👍</span> 下一步问题建议
                <el-switch v-model="form.follow_up_enabled" class="title-switch" @click.stop />
              </span>
            </template>
            <div class="mode-desc">
              <p>完整回答通过核验后，提供查看原文依据的追问入口，点击即可提问。</p>
            </div>
          </el-collapse-item>
        </el-collapse>
      </el-tab-pane>

      <!-- ============ 高级设置 ============ -->
      <el-tab-pane label="高级设置" name="advanced">
        <el-collapse v-model="activeCollapse" class="cfg-collapse">
          <!-- 任务规划 -->
          <el-collapse-item name="planning">
            <template #title>
              <span class="card-title"><span class="card-ico ico-plan">📋</span> 补查规划
                <el-switch v-model="form.planning_enabled" class="title-switch" @click.stop />
              </span>
            </template>
            <div class="mode-desc">
              <p>问题始终会拆分为最多 3 个检索查询。开启此项且检索轮数为 2 时，利用标签、摘要和文档关系补查缺失要点；关闭后仍保留钉钉兜底和答案核验。</p>
            </div>
          </el-collapse-item>

          <!-- 子智能体协作 -->
          <el-collapse-item name="subagent">
            <template #title>
              <span class="card-title"><span class="card-ico ico-plan">🧩</span> 子智能体协作（兼容配置）
                <el-switch v-model="form.subagent_enabled" disabled class="title-switch" @click.stop />
              </span>
            </template>
            <div class="mode-desc">
              <p>此设置仅供旧版 DeerFlow 服务使用。当前问答执行固定的检索、补查与核验流程，不受此开关影响。</p>
            </div>
          </el-collapse-item>

          <!-- 长期记忆 -->
          <el-collapse-item name="memory">
            <template #title>
              <span class="card-title"><span class="card-ico ico-mem">🧠</span> 会话上下文
                <el-switch v-model="form.long_memory_enabled" class="title-switch" @click.stop />
              </span>
            </template>
            <div class="mode-desc">
              <p>使用当前会话最近 8 条消息理解「它/那个/上一条」等指代，事实仍需重新检索原文。关闭后每轮独立，不共享其他会话的记忆。</p>
            </div>
          </el-collapse-item>

          <!-- 默认深度思考 -->
          <el-collapse-item name="deep">
            <template #title>
              <span class="card-title"><span class="card-ico ico-deep">⚡</span> 默认深度思考
                <el-switch v-model="form.deep_think_default" class="title-switch" @click.stop />
              </span>
            </template>
            <div class="mode-desc">
              <p>新会话默认扩大检索范围，召回条数至少为 12；事实生成温度保持为 0，回答中的事实仍须逐项核验。</p>
            </div>
          </el-collapse-item>

          <!-- 超参维护 -->
          <el-collapse-item name="hyper">
            <template #title>
              <span class="card-title"><span class="card-ico ico-hyper">&lt;/&gt;</span> 超参维护</span>
            </template>
            <div class="hyper-grid">
              <div class="hyper-item">
                <div class="hyper-label">事实生成温度 <b>0（固定）</b></div>
                <el-slider :model-value="0" :min="0" :max="2" :step="0.1" disabled />
              </div>
              <div class="hyper-item">
                <div class="hyper-label">Top-P <b>{{ form.top_p.toFixed(2) }}</b></div>
                <el-slider v-model="form.top_p" :min="0.1" :max="1" :step="0.05" />
              </div>
              <div class="hyper-item">
                <div class="hyper-label">召回条数 Top-K <b>{{ form.top_k }}</b></div>
                <el-slider v-model="form.top_k" :min="1" :max="20" :step="1" />
              </div>
              <div class="hyper-item">
                <div class="hyper-label">企业知识检索轮数 <b>{{ form.max_retrieval_rounds }}</b></div>
                <el-slider v-model="form.max_retrieval_rounds" :min="1" :max="2" :step="1" />
              </div>
              <div class="hyper-item hyper-item--input">
                <div class="hyper-label">单次生成 / 核验 Tokens 上限</div>
                <el-input-number v-model="form.max_tokens" :min="3000" :max="8192" :step="256" />
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </el-tab-pane>

      <!-- ============ 人格与技能（DeerFlow SOUL / SKILL 提示词） ============ -->
      <el-tab-pane label="人格与技能（兼容）" name="prompt">
        <el-alert title="以下设置仅作用于旧版 DeerFlow 服务。当前企业问答的检索与核验规则由程序维护。" type="info" :closable="false" show-icon />
        <div v-loading="promptLoading">
          <!-- 人格 SOUL.md -->
          <div class="prompt-card">
            <div class="prompt-head">
              <div>
                <span class="card-title"><span class="card-ico ico-soul">🎭</span> 智能体人格 · SOUL.md</span>
                <el-tag :type="persona.custom ? 'warning' : 'info'" size="small" class="prompt-tag">
                  {{ persona.custom ? '自定义' : '默认模板' }}
                </el-tag>
              </div>
              <div class="prompt-actions">
                <el-button size="small" :disabled="personaSaving" @click="resetPersonaDoc">恢复默认</el-button>
                <el-button size="small" type="primary" :loading="personaSaving" :disabled="persona.content === persona.saved" @click="savePersonaDoc">保存</el-button>
              </div>
            </div>
            <p class="prompt-desc">
              定义智能体的身份、职责与行为准则（DeerFlow 系统提示词）。例如：双源检索策略、
              答案风格、引用规范。修改后<strong>在旧版服务的新对话中生效</strong>，进行中的会话不受影响；自定义内容持久化，服务重启不丢失。
            </p>
            <el-input
              v-model="persona.content"
              type="textarea"
              :rows="16"
              spellcheck="false"
              class="prompt-editor"
            />
          </div>

          <!-- 技能 SKILL.md -->
          <div class="prompt-card">
            <div class="prompt-head">
              <div>
                <span class="card-title"><span class="card-ico ico-skill">🧰</span> 问答技能 · SKILL.md</span>
                <el-tag :type="skill.custom ? 'warning' : 'info'" size="small" class="prompt-tag">
                  {{ skill.custom ? '自定义' : '默认模板' }}
                </el-tag>
              </div>
              <div class="prompt-actions">
                <el-button size="small" :disabled="skillSaving" @click="resetSkillDoc">恢复默认</el-button>
                <el-button size="small" type="primary" :loading="skillSaving" :disabled="skill.content === skill.saved" @click="saveSkillDoc">保存</el-button>
              </div>
            </div>
            <p class="prompt-desc">
              定义「企业知识库问答」技能的工作流指令（DeerFlow Skill）：意图判断、检索策略、
              作答规范、引用来源等。<strong>头部 frontmatter（name/description/version）需保留</strong>；
              修改后在旧版服务的新对话中生效，自定义内容持久化。
            </p>
            <el-input
              v-model="skill.content"
              type="textarea"
              :rows="16"
              spellcheck="false"
              class="prompt-editor"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- ============ 技能库（ClawHub 通用 SKILL.md 结构） ============ -->
      <el-tab-pane label="技能库（兼容）" name="skills">
        <div class="skill-page" v-loading="skillsLoading">
          <div class="skill-toolbar">
            <div class="skill-toolbar-hint">
              兼容 ClawHub 通用技能结构：每个技能为一个目录 + <code>SKILL.md</code>（含 name/description frontmatter）。
              仅供旧版 DeerFlow 服务按需调用，当前企业问答不加载这些自定义技能。
            </div>
            <div class="skill-toolbar-ops">
              <input
                ref="importInput"
                type="file"
                accept=".zip,.md,.markdown"
                style="display: none"
                @change="onImportFile"
              />
              <el-button :loading="importing" @click="triggerImport">导入技能（.zip / SKILL.md）</el-button>
              <el-button type="primary" @click="openCreateSkill">新建技能</el-button>
            </div>
          </div>

          <div v-if="!skills.length && !skillsLoading" class="skill-empty">
            暂无自定义技能。可点击「导入技能」上传 ClawHub 技能 zip 包或 SKILL.md 文件，
            或点击「新建技能」直接编写 Markdown。
          </div>

          <div v-for="s in skills" :key="s.slug" class="skill-card">
            <div class="skill-card-main">
              <div class="skill-card-title">
                <span class="skill-name">{{ s.name }}</span>
                <el-tag :type="s.enabled ? 'success' : 'info'" size="small">
                  {{ s.enabled ? '已启用' : '已停用' }}
                </el-tag>
              </div>
              <div class="skill-desc">{{ s.description || '（无描述）' }}</div>
            </div>
            <div class="skill-card-ops">
              <el-switch
                :model-value="s.enabled"
                @change="(v: any) => toggleSkill(s, !!v)"
              />
              <el-button size="small" @click="openEditSkill(s)">编辑 MD</el-button>
              <el-button size="small" type="danger" plain @click="removeSkill(s)">删除</el-button>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 技能新建/编辑弹窗 -->
    <el-dialog
      v-model="skillDialogVisible"
      :title="skillDialogTitle"
      width="760px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="技能名称（frontmatter name，建议英文小写+中划线）">
          <el-input v-model="skillForm.name" placeholder="例如：expense-report-guide" />
        </el-form-item>
        <el-form-item label="技能描述（frontmatter description：智能体据此判断何时使用）">
          <el-input v-model="skillForm.description" placeholder="一句话说明该技能的适用场景" />
        </el-form-item>
        <el-form-item label="SKILL.md 内容（Markdown，可含 frontmatter；缺省由系统补齐）">
          <el-input
            v-model="skillForm.content"
            type="textarea"
            :rows="16"
            spellcheck="false"
            class="prompt-editor"
          />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="skillForm.enabled" />
          <span class="mode-desc" style="margin-left: 10px">停用后内容保留，智能体不加载该技能</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="skillDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="skillFormSaving" @click="saveSkillForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.agent-config-page {
  padding: 20px 24px;
  max-width: 960px;
  margin: 0 auto;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.page-title {
  font-size: 20px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0 0 6px;
}
.page-sub {
  font-size: 13px;
  color: #909399;
  margin: 0;
}
.cfg-tabs :deep(.el-tabs__item) {
  font-size: 15px;
  font-weight: 600;
}
.cfg-collapse {
  border: none;
}
.cfg-collapse :deep(.el-collapse-item) {
  background: #f7f8fa;
  border: 1px solid #eef0f4;
  border-radius: 12px;
  margin-bottom: 14px;
  padding: 4px 18px;
}
.cfg-collapse :deep(.el-collapse-item__header) {
  background: transparent;
  border: none;
  height: 56px;
  font-size: 15px;
}
.cfg-collapse :deep(.el-collapse-item__wrap) {
  border: none;
  background: transparent;
}
.cfg-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 18px;
}
.card-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: #1a1a2e;
}
.card-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  font-size: 15px;
  font-style: normal;
}
.ico-model { background: #e8f0ff; }
.ico-kb { background: #e8f8ee; }
.ico-greet { background: #e8f0ff; }
.ico-follow { background: #fff4e0; }
.ico-plan { background: #eef0ff; }
.ico-mem { background: #f0e8ff; }
.ico-deep { background: #ffe8e8; }
.ico-hyper { background: #e8f6ff; font-weight: 700; font-size: 13px; color: #2b6bff; }
.card-hint {
  font-size: 12px;
  font-weight: 400;
  color: #909399;
  margin-left: 4px;
}
.title-switch {
  margin-left: 12px;
}
.mode-radio {
  margin-left: 14px;
}
.mode-desc {
  color: #606266;
  font-size: 13px;
  line-height: 1.9;
}
.mode-desc p {
  margin: 4px 0;
}
.full-width {
  width: 100%;
}
.sub-label {
  margin: 14px 0 8px;
  font-size: 13px;
  color: #606266;
  font-weight: 600;
}
.hyper-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px 32px;
}
.hyper-item {
  min-width: 0;
}
.hyper-item--input {
  align-self: end;
}
.hyper-label {
  font-size: 13px;
  color: #303133;
  margin-bottom: 8px;
}
.hyper-label b {
  color: #2b6bff;
  margin-left: 6px;
}

/* 人格与技能提示词编辑 */
.prompt-card {
  background: #f7f8fa;
  border: 1px solid #eef0f4;
  border-radius: 12px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.prompt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.prompt-tag {
  margin-left: 8px;
}
.prompt-actions {
  display: flex;
  gap: 8px;
}
.prompt-desc {
  font-size: 12.5px;
  color: #909399;
  line-height: 1.8;
  margin: 10px 0 12px;
}
.prompt-editor :deep(textarea) {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace !important;
  font-size: 12.5px !important;
  line-height: 1.75 !important;
}
.ico-soul { background: #f3e8ff; }
.ico-skill { background: #e0f7f0; }
.ico-tool { background: #eef0ff; }

/* ===== 工具组 ===== */
.tool-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tool-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #eef0f4;
}
.tool-item:hover {
  border-color: #d6ddf5;
}
.tool-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.tool-name {
  font-size: 13.5px;
  font-weight: 600;
  color: #303133;
}
.tool-desc {
  font-size: 12.5px;
  color: #909399;
  line-height: 1.5;
}

/* ===== 技能库 ===== */
.skill-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.skill-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.skill-toolbar-hint {
  flex: 1 1 320px;
  font-size: 12.5px;
  color: #909399;
  line-height: 1.7;
}
.skill-toolbar-hint code {
  background: #f0f2f8;
  padding: 1px 5px;
  border-radius: 4px;
  color: #2b6bff;
}
.skill-toolbar-ops {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.skill-empty {
  padding: 36px 20px;
  text-align: center;
  font-size: 13px;
  color: #909399;
  background: #f7f8fa;
  border: 1px dashed #dcdfe6;
  border-radius: 12px;
  line-height: 1.9;
}
.skill-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  background: #f7f8fa;
  border: 1px solid #eef0f4;
  border-radius: 12px;
}
.skill-card-main {
  min-width: 0;
  flex: 1 1 auto;
}
.skill-card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}
.skill-name {
  font-size: 14px;
  font-weight: 700;
  color: #1a1a2e;
}
.skill-desc {
  font-size: 12.5px;
  color: #909399;
  line-height: 1.6;
}
.skill-card-ops {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
</style>
