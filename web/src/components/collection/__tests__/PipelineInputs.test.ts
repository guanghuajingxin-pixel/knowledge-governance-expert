import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi, beforeEach } from 'vitest'
import PipelineInputs from '../PipelineInputs.vue'
import { listPipelineVariables, importPipelineSchema } from '@/api/sync'

vi.mock('@/api/sync', () => ({ listPipelineVariables: vi.fn(), importPipelineSchema: vi.fn() }))
const request = vi.mocked(listPipelineVariables)
const schema = {
  configured: true, schema_source: 'published', runtime_mode: 'rag_pipeline', variables: [
    { variable: 'parent_mode', label: '父分段模式', type: 'select', options: ['paragraph', 'full_doc'], required: true, default_value: 'paragraph' },
    { variable: 'clean_1', label: '清洗', type: 'checkbox', required: true, default_value: true },
    { variable: 'length', label: '长度', type: 'number', required: true, default_value: 1024 },
  ],
} as any
const create = (modelValue = {}) => mount(PipelineInputs, { props: { datasetId: 'pipeline', modelValue } })
beforeEach(() => { vi.clearAllMocks(); request.mockResolvedValue(schema) })

it('保留明确的关闭和零值，只填补缺省参数', async () => {
  const wrapper = create({ clean_1: false, length: 0 })
  await flushPromises()
  expect(wrapper.emitted('update:modelValue')?.[0][0]).toEqual({ parent_mode: 'paragraph', clean_1: false, length: 0 })
  await wrapper.setProps({ modelValue: { parent_mode: 'paragraph', clean_1: false, length: 0 } })
  expect((wrapper.vm as any).validate()).toBe(true)
  expect(wrapper.text()).toContain('已关闭')
  expect(wrapper.text()).not.toContain('已开启')
  wrapper.unmount()
})

it('切换普通库后隐藏参数，忽略旧库延迟返回的表单', async () => {
  let resolveOld!: (value: any) => void
  request.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
  const wrapper = create()
  request.mockResolvedValueOnce({ configured: true, runtime_mode: 'general', variables: [] } as any)
  await wrapper.setProps({ datasetId: 'general' })
  await flushPromises()
  resolveOld(schema)
  await flushPromises()
  expect(wrapper.find('.pipeline-inputs').exists()).toBe(false)
  expect((wrapper.vm as any).validate()).toBe(true)
  wrapper.unmount()
})

it('阻止必填文本全空白的上传', async () => {
  request.mockResolvedValueOnce({ ...schema, variables: [{ variable: 'token', label: '项目编号', type: 'text-input', required: true }] })
  const wrapper = create({ token: '   ' })
  await flushPromises()
  expect((wrapper.vm as any).validate()).toBe(false)
  wrapper.unmount()
})

it('无定义时允许 JSON 参数，并阻止数组或无效 JSON', async () => {
  request.mockResolvedValueOnce({ configured: false, runtime_mode: 'rag_pipeline', variables: [] } as any)
  const wrapper = create()
  await flushPromises()
  const input = wrapper.get('textarea')
  await input.setValue('[]')
  expect((wrapper.vm as any).validate()).toBe(false)
  await input.setValue('{"clean_1":false}')
  expect(wrapper.emitted('update:modelValue')?.slice(-1)[0]?.[0]).toEqual({ clean_1: false })
  expect((wrapper.vm as any).validate()).toBe(true)
  wrapper.unmount()
})

it('导入配置使用当前目标库并展示可编辑表单', async () => {
  request.mockResolvedValueOnce({ configured: false, runtime_mode: 'rag_pipeline', variables: [] } as any)
  vi.mocked(importPipelineSchema).mockResolvedValueOnce({ ...schema, schema_source: 'imported' })
  const wrapper = create()
  await flushPromises()
  const file = new File(['kind: rag_pipeline'], 'test.pipeline')
  const input = wrapper.get('input[type=file]')
  Object.defineProperty(input.element, 'files', { value: [file] })
  await input.trigger('change')
  await flushPromises()
  expect(importPipelineSchema).toHaveBeenCalledWith('pipeline', file)
  expect(wrapper.text()).toContain('导入的配置文件')
  expect(wrapper.findAll('.field')).toHaveLength(3)
  wrapper.unmount()
})
