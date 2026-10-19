import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import AddKnowledgeDialog from '../AddKnowledgeDialog.vue'
import DingTalkDocTreeDialog from '../DingTalkDocTreeDialog.vue'
import {
  discardStagedDocuments, importDingTalk, listLibraryDocuments, stageLibraryDocument,
} from '@/api/document-library'
import { createSource } from '@/api/sync'

vi.mock('@/api/document', () => ({ uploadDocument: vi.fn(), listDocuments: vi.fn() }))
vi.mock('@/api/document-library', () => ({
  importDingTalk: vi.fn(),
  stageLibraryDocument: vi.fn(),
  discardStagedDocuments: vi.fn(() => Promise.resolve({ ok: true, discarded: 1 })),
  commitStagedDocuments: vi.fn(),
  listLibraryDocuments: vi.fn(),
}))
vi.mock('@/api/sync', () => ({ createSource: vi.fn() }))

const docSelection = {
  workspaceId: 'ws-1',
  workspaceName: '钉钉知识库A',
  rootNodeId: 'root-1',
  nodes: [
    { node_id: 'n1', name: '文档一', workspace_id: 'ws-1' },
    { node_id: 'n2', name: '文档二', workspace_id: 'ws-1' },
  ],
}

// el-dialog 内容 teleport 到 body：统一用 document 查询 + 原生 click
function mountDialog() {
  return mount(AddKnowledgeDialog, {
    props: { modelValue: true, libraryId: 1, libraryName: '目标库' },
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
}

function byText(selector: string, text: string): HTMLElement {
  const el = [...document.querySelectorAll(selector)]
    .find((n) => n.textContent?.trim() === text) as HTMLElement | undefined
  expect(el, `${selector} "${text}" 应存在`).toBeTruthy()
  return el!
}

/** 打开钉钉文档选择器并选中文档（stub 场景下直接对子弹窗 emit 选中结果） */
async function selectDocs(wrapper: ReturnType<typeof mountDialog>) {
  await flushPromises() // 等待 el-dialog teleport 渲染到 body
  const card = byText('.dt-card-title', '钉钉文档').closest('.dt-card') as HTMLElement | null
  expect(card).toBeTruthy()
  card!.click()
  await flushPromises()
  wrapper.findComponent(DingTalkDocTreeDialog).vm.$emit('selected', docSelection)
  await flushPromises()
}

let listCalls = 0
beforeEach(() => {
  vi.useFakeTimers()
  listCalls = 0
  // 第 1 次 = 打开弹窗拉取已有文档名（空库）；第 2 次 = 提交前 ID 快照（空库）；之后 = 等待轮询（返回新落库的占位文档）
  vi.mocked(listLibraryDocuments).mockImplementation(async () => {
    listCalls++
    return listCalls <= 2 ? []
      : [{ id: 'nd-1', name: '新文档.docx', source: 'dingtalk', status: 'PENDING' } as any]
  })
})
afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
  vi.clearAllMocks()
})

/** 点确定并推进到「首批数据落库」轮询命中（组件轮询间隔 2s） */
async function confirmAndWaitFirstBatch() {
  byText('button', '确定').click()
  await flushPromises() // 提交 API + 快照完成，进入等待循环
  await vi.advanceTimersByTimeAsync(2_000)
  await flushPromises()
}

describe('添加知识：等首批编目数据落库后再关闭弹窗', () => {
  it('单次导入指定文档：首批文档出现后才 emit success 并关闭', async () => {
    vi.mocked(importDingTalk).mockResolvedValue({
      queued: true, source_id: 42, source_name: 's', message: 'ok',
    })
    const wrapper = mountDialog()
    await selectDocs(wrapper)
    // 切到「单次导入」（默认是自动同步）
    ;([...document.querySelectorAll('.import-option input')][0] as HTMLInputElement).click()
    await flushPromises()

    byText('button', '确定').click()
    await flushPromises() // 提交 API + 快照完成，进入等待循环
    // 等待期间：任务已提交但弹窗未关、未 emit success
    expect(importDingTalk).toHaveBeenCalledWith(1, {
      node_ids: ['n1', 'n2'], workspace_id: 'ws-1', root_node_id: 'root-1',
      workspace_name: '钉钉知识库A', import_mode: 'once',
    })
    expect(wrapper.emitted('success')).toBeUndefined()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    await vi.advanceTimersByTimeAsync(2_000) // 首批占位文档落库，轮询命中
    await flushPromises()
    expect(wrapper.emitted('success')).toEqual([[[42]]])
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]]) // 首批出现后才关闭
    wrapper.unmount()
  })

  it('自动同步指定文档：首批文档出现后才 emit success 携带源 id', async () => {
    vi.mocked(createSource).mockResolvedValue({
      id: 7, name: '钉钉文档 · 钉钉知识库A', workspace_id: 'ws-1', root_node_id: 'root-1',
    } as any)
    const wrapper = mountDialog()
    await selectDocs(wrapper)
    await confirmAndWaitFirstBatch()

    expect(createSource).toHaveBeenCalled()
    expect(wrapper.emitted('success')).toEqual([[[7]]])
    wrapper.unmount()
  })

  it('等待期间用户取消：不再等待也不 emit success（任务已在后台）', async () => {
    vi.mocked(importDingTalk).mockResolvedValue({
      queued: true, source_id: 42, source_name: 's', message: 'ok',
    })
    const wrapper = mountDialog()
    await selectDocs(wrapper)
    ;([...document.querySelectorAll('.import-option input')][0] as HTMLInputElement).click()
    await flushPromises()

    byText('button', '确定').click()
    await flushPromises()
    byText('button', '取消').click() // 等待中取消
    await wrapper.setProps({ modelValue: false }) // 模拟父组件响应关闭
    await vi.advanceTimersByTimeAsync(10_000)
    await flushPromises()

    expect(importDingTalk).toHaveBeenCalled() // 任务已提交（后台继续）
    expect(wrapper.emitted('success')).toBeUndefined() // 取消等待后不再回显
    wrapper.unmount()
  })
})

describe('添加知识：本地上传重名提示', () => {
  function switchToLocal() {
    const localItem = [...document.querySelectorAll('.source-item')]
      .find((n) => n.textContent?.includes('本地文件')) as HTMLElement
    localItem.click()
  }

  function pickFiles(files: File[]) {
    const input = document.querySelector('.local-upload input[type="file"]') as HTMLInputElement
    Object.defineProperty(input, 'files', { value: files })
    input.dispatchEvent(new Event('change'))
  }

  it('文件名与库内已有文档完全一致时，在关闭按钮前显示红色重复标记', async () => {
    vi.mocked(listLibraryDocuments).mockResolvedValue([
      { id: 'd1', name: '同步触发机制改造.md', source: 'local', status: 'COMPLETED' } as any,
    ])
    vi.mocked(stageLibraryDocument).mockImplementation(async (_id, file: File) => ({
      staging_id: `s-${file.name}`, name: file.name, size: file.size,
    }))
    const wrapper = mountDialog()
    await flushPromises() // 打开弹窗：拉取库内已有文档名

    switchToLocal()
    await flushPromises()
    pickFiles([
      new File(['a'], '同步触发机制改造.md'),
      new File(['b'], '全新文档.md'),
    ])
    await flushPromises() // 暂存上传完成

    const items = [...document.querySelectorAll('.upload-file-item')]
    expect(items).toHaveLength(2)
    const dupItem = items.find((n) => n.textContent?.includes('同步触发机制改造.md'))
    expect(dupItem).toBeTruthy()
    const dupBadge = dupItem!.querySelector('.upload-file-dup')
    expect(dupBadge?.textContent?.trim()).toBe('重复')
    // 标记位于关闭按钮之前
    const closeBtn = dupItem!.querySelector('.upload-file-close')
    expect(closeBtn).toBeTruthy()
    expect(
      dupBadge!.compareDocumentPosition(closeBtn!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    // 非重名文件不显示标记
    const newItem = items.find((n) => n.textContent?.includes('全新文档.md'))
    expect(newItem?.querySelector('.upload-file-dup')).toBeNull()
    wrapper.unmount()
  })

  it('移除文件后标记随行消失，且同步丢弃暂存对象', async () => {
    vi.mocked(listLibraryDocuments).mockResolvedValue([
      { id: 'd1', name: '同步触发机制改造.md', source: 'local', status: 'COMPLETED' } as any,
    ])
    vi.mocked(stageLibraryDocument).mockImplementation(async (_id, file: File) => ({
      staging_id: `s-${file.name}`, name: file.name, size: file.size,
    }))
    const wrapper = mountDialog()
    await flushPromises()

    switchToLocal()
    await flushPromises()
    pickFiles([new File(['a'], '同步触发机制改造.md')])
    await flushPromises()

    ;(document.querySelector('.upload-file-close') as HTMLElement).click()
    await flushPromises()
    expect(document.querySelectorAll('.upload-file-item')).toHaveLength(0)
    expect(discardStagedDocuments).toHaveBeenCalledWith(1, ['s-同步触发机制改造.md'])
    wrapper.unmount()
  })
})
