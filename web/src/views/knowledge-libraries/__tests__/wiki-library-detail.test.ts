import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import Page from '../WikiLibraryDetail.vue'
import { getWikiLibrary, listWikiPages, listWikiRuns } from '@/api/wiki'
import type { WikiRun } from '@/api/wiki'

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/apply/knowledge-libraries/43/wiki' }),
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/api/wiki', () => ({
  getWikiLibrary: vi.fn(), listWikiPages: vi.fn(), listWikiRuns: vi.fn(),
  retryWikiRun: vi.fn(), triggerWikiLint: vi.fn(), latestWikiLint: vi.fn(),
  updateWikiLibrary: vi.fn(), generateWiki: vi.fn(),
}))
vi.mock('@/api/document-library', () => ({
  listLibraryDocuments: vi.fn(), downloadOriginal: vi.fn(), deleteLibraryDocument: vi.fn(),
}))
vi.mock('@/api/sync', () => ({ sourcesStatsAll: vi.fn() }))
vi.mock('@/utils/file-icon', () => ({ fileIcon: vi.fn(() => 'icon.png') }))
vi.mock('@/stores/user', () => ({ useUserStore: () => ({ userInfo: { role: 'admin' } }) }))
vi.mock('@/stores/tabs', () => ({ useTabsStore: () => ({ updateTabTitle: vi.fn() }) }))
vi.mock('@/components/kb/AddKnowledgeDialog.vue', () => ({ default: { name: 'AddKnowledgeDialog', render: () => null } }))

const failedRun: WikiRun = {
  id: 'r1', kind: 'ingest', document_ids: ['d1'], status: 'FAILED',
  pages_created: 0, pages_updated: 0, report: {},
  error: '页面规划失败：LLM 账户余额不足（Error 402），请为当前模型服务充值，或在「模型配置」中切换可用的 LLM 后重试',
  triggered_by: 'auto', started_at: null,
  finished_at: '2026-10-18T02:46:43Z', created_at: '2026-10-18T02:46:39Z',
}
const okRun: WikiRun = {
  id: 'r2', kind: 'ingest', document_ids: ['d2'], status: 'COMPLETED',
  pages_created: 3, pages_updated: 1, report: {}, error: '',
  triggered_by: 'auto', started_at: null,
  finished_at: '2026-10-18T03:00:00Z', created_at: '2026-10-18T02:50:00Z',
}

beforeEach(() => {
  vi.mocked(getWikiLibrary).mockResolvedValue({
    id: 43, name: 'SAP', description: '', enabled: true, creator: 'admin',
    auto_generate: true, page_count: 0, document_count: 5, last_run: failedRun,
    created_at: '2026-10-18T00:00:00Z', updated_at: '2026-10-18T00:00:00Z',
  })
  vi.mocked(listWikiPages).mockResolvedValue([])
  vi.mocked(listWikiRuns).mockResolvedValue([failedRun, okRun])
})
afterEach(() => { document.body.innerHTML = ''; vi.clearAllMocks() })

function mountPage() {
  return mount(Page, {
    props: { libId: 43 },
    attachTo: document.body,
    global: { plugins: [ElementPlus], stubs: { transition: false } },
  })
}

describe('Wiki 库详情 · 生成记录失败原因暗提示', () => {
  it('失败任务显示统一 HelpTip ? 角标（hover 提示失败原因），成功任务不显示', async () => {
    const wrapper = mountPage()
    await flushPromises()
    // 打开生成记录抽屉（teleport 到 body）
    await wrapper.findAll('button').find(b => b.text() === '生成记录')!.trigger('click')
    await flushPromises()

    const badges = document.querySelectorAll('.help-tip.is-badge')
    expect(badges.length).toBe(1)  // 仅失败任务有角标
    expect(badges[0].getAttribute('aria-label')).toBe('查看失败原因')
    // hover 角标后 tooltip 显示完整失败原因
    badges[0].dispatchEvent(new MouseEvent('mouseenter', { bubbles: false }))
    await flushPromises()
    await new Promise(r => setTimeout(r, 300))
    expect(document.body.innerHTML).toContain('余额不足')
    wrapper.unmount()
  })

  it('页面顶部驻留最近一次失败的告警与原因', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('最近一次生成失败')
    expect(wrapper.text()).toContain('余额不足')
    wrapper.unmount()
  })
})
