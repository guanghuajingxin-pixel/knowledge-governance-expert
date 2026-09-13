import { it, expect } from 'vitest'
import { updateStep, settleSteps, evidenceLabel, type StepItem } from '../chat-progress'

it('并行工具开始和结束按调用 ID 更新，不提前完成另一个工具', () => {
  const steps: StepItem[] = []
  updateStep(steps, { type: 'step', step_id: 'a', status: 'running', title: '读取甲' })
  updateStep(steps, { type: 'step', step_id: 'b', status: 'running', title: '读取乙' })
  updateStep(steps, { type: 'step', step_id: 'b', status: 'completed', title: '读取乙', detail: '已读取' })
  expect(steps).toHaveLength(2)
  expect(steps[0].done).toBe(false)
  expect(steps[1].status).toBe('completed')
  settleSteps(steps, 'failed')
  expect(steps[0].status).toBe('failed')
  expect(steps[1].status).toBe('completed')
  const restored = JSON.parse(JSON.stringify(steps))
  expect(restored).toEqual(steps)
})
it('取消和暂停不会将未完成工具显示成成功', () => {
  const steps: StepItem[] = [{ title: '读取', detail: '', done: false }]
  settleSteps(steps, 'cancelled')
  expect(steps[0].status).toBe('cancelled')
  updateStep(steps, { type: 'step', step_id: 'choice', status: 'running' })
  settleSteps(steps, 'paused')
  expect(steps[1].status).toBe('paused')
})
it('有引用和回答完成都不能被标成已通过事实核验', () => {
  expect(evidenceLabel('answered', 1)).toBe('附有参考来源')
  expect(evidenceLabel('answered', 0)).toBe('回答已生成')
  expect(evidenceLabel('insufficient', 0)).toBe('参考依据不足')
})
