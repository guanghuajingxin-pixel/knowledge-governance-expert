import request from './request'

/** 杰克百晓生智能体配置（与后端 services/kb-api/app/services/agent/config.py 对应） */
export interface AgentConfig {
  agent_name: string
  models: string[]               // 参与调度的模型（最多 10）
  retrieval_mode: 'smart' | 'force'  // 智能调用 / 强制调用
  greeting_enabled: boolean
  greeting: string
  suggested_questions: string[]
  follow_up_enabled: boolean     // 下一步问题建议
  tools_enabled: Record<string, boolean>  // 工具开关（key=工具名）
  planning_enabled: boolean      // 任务规划
  subagent_enabled: boolean      // 子智能体协作（DeerFlow Lead → Sub-Agent 并行调研）
  long_memory_enabled: boolean   // 长期记忆
  deep_think_default: boolean    // 默认深度思考
  temperature: number
  top_p: number
  max_tokens: number
  top_k: number
  max_retrieval_rounds: number
}

/** 智能问答可用工具 */
export interface AgentTool {
  key: string
  name: string
  desc: string
  enabled: boolean
}

/** 技能（ClawHub/Agent Skills 通用结构：<技能名>/SKILL.md） */
export interface SkillDoc {
  name: string
  slug: string
  description: string
  content: string
  enabled: boolean
  builtin: boolean
}

export const getAgentTools = () =>
  request.get<unknown, { tools: AgentTool[] }>('/agent/tools')

export const listSkills = () =>
  request.get<unknown, { skills: SkillDoc[] }>('/agent/skills')

export const saveSkillDoc = (data: { name: string; slug?: string; description?: string; content: string; enabled: boolean }) =>
  request.put<unknown, { ok: boolean; slug?: string; name?: string }>('/agent/skills', data)

export const deleteSkillDoc = (slug: string) =>
  request.delete<unknown, { ok: boolean }>(`/agent/skills/${slug}`)

/** 导入技能：.zip 包（内含 SKILL.md）或单个 .md 文件 */
export const importSkillDoc = (file: File, enabled = true) => {
  const fd = new FormData()
  fd.append('file', file)
  return request.post<unknown, { ok: boolean; slug?: string; name?: string }>(
    `/agent/skills/import?enabled=${enabled}`,
    fd,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
}

export interface GreetingInfo {
  agent_name: string
  greeting_enabled: boolean
  greeting: string
  suggested_questions: string[]
  models: string[]
  follow_up_enabled: boolean
  planning_enabled: boolean
  long_memory_enabled: boolean
  deep_think_default: boolean
}

export const getAgentConfig = () => request.get<unknown, AgentConfig>('/agent/config')

export const updateAgentConfig = (data: Partial<AgentConfig>) =>
  request.put<unknown, AgentConfig>('/agent/config', data)

export const getGreeting = () => request.get<unknown, GreetingInfo>('/agent/greeting')

/** 智能体人格（SOUL.md）/ 问答技能（SKILL.md）提示词配置 */
export interface PromptDoc {
  content: string        // 当前生效内容
  custom: boolean        // 是否为用户自定义（false=默认模板）
  default: string        // 默认模板内容（用于"恢复默认"）
  skill_name?: string
}

export const getPersona = () => request.get<unknown, PromptDoc>('/agent/persona')

export const savePersona = (data: { content?: string; reset?: boolean }) =>
  request.put<unknown, { ok: boolean; custom: boolean }>('/agent/persona', data)

export const getSkill = () => request.get<unknown, PromptDoc>('/agent/skill')

export const saveSkill = (data: { content?: string; reset?: boolean }) =>
  request.put<unknown, { ok: boolean; custom: boolean }>('/agent/skill', data)
