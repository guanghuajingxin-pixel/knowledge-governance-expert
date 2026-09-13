import type { StreamEvent } from '@/api/chat'

export type StepStatus = 'running' | 'completed' | 'failed' | 'cancelled' | 'paused'
export interface StepItem {
  id?: string
  title: string
  detail: string
  done: boolean
  status?: StepStatus
}
export function updateStep(steps: StepItem[], event: StreamEvent) {
  const id = event.step_id
  const existing = id ? steps.find((step) => step.id === id) : undefined
  const status = event.status || 'running'
  const value = { id, title: event.title || event.node || '', detail: event.detail || '',
    status, done: status !== 'running' }
  if (existing) Object.assign(existing, value)
  else steps.push(value)
}
export function settleSteps(steps: StepItem[] | undefined, status: StepStatus) {
  for (const step of steps || []) {
    if (step.status === 'running' || (!step.status && !step.done)) {
      step.status = status
      step.done = status !== 'running'
      step.detail = status === 'failed' ? '未收到完成结果' : status === 'cancelled' ? '已取消' : '等待继续'
    }
  }
}
export function evidenceLabel(status: string | undefined, references: number): string {
  if (status === 'insufficient') return '参考依据不足'
  if (status === 'partial') return '部分有依据 · 尚有缺口'
  if (status === 'clarification') return '需要补充信息'
  // answered 仅表示生成完成，历史 prompt 自检也不能展示“已通过证据核验”。
  return references ? '附有参考来源' : '回答已生成'
}
