import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import Page from '../KnowledgeCenter.vue'
import { batchDeleteAllSourceDocuments, batchDeleteSourceDocuments, fetchSourceDocuments, fetchSourceDocumentTags } from '@/api/knowledge-center'
import type { SourceDoc } from '@/types/knowledge-center'

vi.mock('@/api/knowledge-center', () => ({
  fetchSourceDocuments: vi.fn(),
  fetchSourceDocumentTags: vi.fn(),
  updateSourceDocument: vi.fn(),
  batchDeleteSourceDocuments: vi.fn(),
  batchDeleteAllSourceDocuments: vi.fn(),
}))
vi.mock('@/api/document-library', () => ({ downloadOriginal: vi.fn() }))
vi.mock('@/utils/file-icon', () => ({ fileIcon: vi.fn(() => 'icon.png') }))

const doc: SourceDoc = {
  id: 'd1', name: '产品手册.pdf', tags: [], source: 'local', status: 'COMPLETED',
  size: 1, library_id: 1, library_name: '库A', updated_by: 'u', expire_at: null,
  updated_at: '2026-01-01T00:00:00+00:00', source_url: null, source_workspace_name: null,
}

beforeEach(() => {
  vi.mocked(fetchSourceDocuments).mockResolvedValue({ items: [{ ...doc }], total: 1 })
  vi.mocked(fetchSourceDocumentTags).mockResolvedValue({ items: [] })
})
afterEach(() => { document.body.innerHTML = ''; vi.clearAllMocks() })

function mountPage() {
  return mount(Page, { attachTo: document.body, global: { plugins: [ElementPlus], stubs: { transition: false } } })
}

function confirmButton(text = '删除'): HTMLButtonElement {
  const btn = [...document.querySelectorAll('.el-message-box__btns button')]
    .find((b) => b.textContent?.trim() === text) as HTMLButtonElement | undefined
  expect(btn).toBeTruthy()
  return btn!
}

/** 悬停打开「批量管理」下拉（菜单 teleport 到 body），返回菜单项 */
async function openBatchMenu(wrapper: VueWrapper): Promise<HTMLElement[]> {
  await wrapper.find('.el-dropdown').trigger('mouseenter')
  await flushPromises()
  return [...document.querySelectorAll('.el-dropdown-menu__item')] as HTMLElement[]
}

function menuItem(items: HTMLElement[], text: string): HTMLElement {
  const item = items.find((el) => el.textContent?.trim() === text)
  expect(item).toBeTruthy()
  return item!
}

describe('知识中心批量管理', () => {
  it('未勾选时「删除选中」禁用；勾选后二次确认删除并提示清理文件数', async () => {
    vi.mocked(batchDeleteSourceDocuments).mockResolvedValue({ ok: true, deleted: 1, storage_objects: 3 })
    const wrapper = mountPage()
    await flushPromises()

    const items0 = await openBatchMenu(wrapper)
    expect(items0.map((el) => el.textContent?.trim())).toEqual(['删除选中', '删除全部'])
    expect(menuItem(items0, '删除选中').classList).toContain('is-disabled')  // 未勾选禁用
    expect(menuItem(items0, '删除全部').classList).not.toContain('is-disabled')  // 有数据可用

    await wrapper.find('.el-table__body-wrapper .el-checkbox').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已选 1 项知识')

    const items1 = await openBatchMenu(wrapper)
    expect(menuItem(items1, '删除选中').classList).not.toContain('is-disabled')
    menuItem(items1, '删除选中').click()
    await flushPromises()
    expect(confirmButton()).toBeTruthy()  // 危险操作有二次确认
    confirmButton().click()
    await flushPromises()
    expect(batchDeleteSourceDocuments).toHaveBeenCalledWith(['d1'])
    wrapper.unmount()
  })

  it('「删除全部」二次确认后分批删除：每批带 limit，deleted=0 时停止并提示累计数', async () => {
    vi.mocked(batchDeleteAllSourceDocuments)
      .mockResolvedValueOnce({
        ok: true, deleted: 50, excluded: 0, storage_objects: 30, message: '已删除 50 项知识',
      })
      .mockResolvedValueOnce({
        ok: true, deleted: 0, excluded: 0, storage_objects: 0, message: '当前范围内没有可删除的知识',
      })
    const wrapper = mountPage()
    await flushPromises()

    const items = await openBatchMenu(wrapper)
    menuItem(items, '删除全部').click()
    await flushPromises()
    expect(confirmButton('全部删除')).toBeTruthy()
    confirmButton('全部删除').click()
    await flushPromises()
    // 分批循环：每批带 limit=50，直到 deleted=0 停止
    expect(batchDeleteAllSourceDocuments).toHaveBeenCalledTimes(2)
    expect(batchDeleteAllSourceDocuments).toHaveBeenCalledWith({
      search: undefined, source: undefined, tag: undefined, limit: 50,
    })
    wrapper.unmount()
  })

  it('解析中的文档禁止勾选（后端拒绝删除）', async () => {
    vi.mocked(fetchSourceDocuments).mockResolvedValue({
      items: [{ ...doc, id: 'd2', status: 'PARSING' }], total: 1,
    })
    const wrapper = mountPage()
    await flushPromises()
    const cb = wrapper.find('.el-table__body-wrapper .el-checkbox')
    expect(cb.classes()).toContain('is-disabled')
    wrapper.unmount()
  })
})
