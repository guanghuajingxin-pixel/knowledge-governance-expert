import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import DingTalkDocTreeDialog from '../DingTalkDocTreeDialog.vue'
import { fetchDingTalkNodes, fetchDingTalkWorkspaces } from '@/api/knowledge-center'

vi.mock('@/api/knowledge-center', () => ({
  fetchDingTalkWorkspaces: vi.fn(),
  fetchDingTalkNodes: vi.fn(),
}))

// 树结构：root → [目录A, 文件1]；目录A → [文件2, 子目录B]；子目录B → [文件3]
const NODES: Record<string, any[]> = {
  root: [
    { node_id: 'dir-1', name: '目录A', is_folder: true, has_children: true, extension: null, size: 0, url: null },
    { node_id: 'file-1', name: '文件1.docx', is_folder: false, has_children: false, extension: 'docx', size: 100, url: null },
  ],
  'dir-1': [
    { node_id: 'file-2', name: '文件2.pdf', is_folder: false, has_children: false, extension: 'pdf', size: 200, url: null },
    { node_id: 'dir-2', name: '子目录B', is_folder: true, has_children: true, extension: null, size: 0, url: null },
  ],
  'dir-2': [
    { node_id: 'file-3', name: '文件3.xlsx', is_folder: false, has_children: false, extension: 'xlsx', size: 300, url: null },
  ],
}

beforeEach(() => {
  localStorage.clear()
  vi.mocked(fetchDingTalkWorkspaces).mockResolvedValue({
    items: [{ id: 'ws-1', name: '知识库A', root_node_id: 'root' }],
    error: '',
  } as any)
  vi.mocked(fetchDingTalkNodes).mockImplementation(async (parentId: string) =>
    ({ items: NODES[parentId] || [] }) as any)
})
afterEach(() => { document.body.innerHTML = ''; vi.clearAllMocks() })

function mountDialog() {
  return mount(DingTalkDocTreeDialog, {
    props: { modelValue: true },
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
}

/** 找到指定名称树节点行的复选框并点击 */
async function checkNode(name: string) {
  const row = [...document.querySelectorAll('.el-tree-node__content')]
    .find((n) => n.textContent?.includes(name))
  expect(row, `树节点「${name}」应已渲染`).toBeTruthy()
  ;(row!.querySelector('.el-checkbox') as HTMLElement).click()
  await flushPromises()
}

describe('选择文档：勾选目录递归收集其下全部文件', () => {
  it('勾选一级目录后确定按钮激活，确认携带目录下全部文件（含子目录）', async () => {
    const wrapper = mountDialog()
    await flushPromises() // 工作区 + 根级懒加载
    await flushPromises()

    // 初始：无选择，确认按钮置灰
    let confirmBtn = [...document.querySelectorAll('.el-dialog__footer button')]
      .find((b) => b.textContent?.trim() === '确认') as HTMLButtonElement
    expect(confirmBtn.disabled).toBe(true)

    await checkNode('目录A')
    await flushPromises() // 递归收集 dir-1 → dir-2

    // 已选 = 文件2 + 文件3（目录A 子树全部文件；文件1 未勾选）
    expect(document.body.textContent).toContain('已选 2 个文档')
    confirmBtn = [...document.querySelectorAll('.el-dialog__footer button')]
      .find((b) => b.textContent?.trim() === '确认') as HTMLButtonElement
    expect(confirmBtn.disabled).toBe(false)

    confirmBtn.click()
    await flushPromises()
    const sel = wrapper.emitted('selected')![0][0] as any
    expect(sel.nodes.map((n: any) => n.node_id).sort()).toEqual(['file-2', 'file-3'])
    expect(sel.workspaceId).toBe('ws-1')
    wrapper.unmount()
  })

  it('取消勾选目录后，其收集的文件随之移出已选', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    await flushPromises()

    await checkNode('目录A')
    await flushPromises()
    expect(document.body.textContent).toContain('已选 2 个文档')

    await checkNode('目录A') // 再次点击 = 取消勾选
    expect(document.body.textContent).toContain('已选 0 个文档')
    const confirmBtn = [...document.querySelectorAll('.el-dialog__footer button')]
      .find((b) => b.textContent?.trim() === '确认') as HTMLButtonElement
    expect(confirmBtn.disabled).toBe(true)
    wrapper.unmount()
  })
})
