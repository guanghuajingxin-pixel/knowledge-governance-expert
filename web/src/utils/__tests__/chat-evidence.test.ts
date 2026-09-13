import { describe, it, expect } from 'vitest'
import { citationUrl, linkEvidence } from '../chat-evidence'
import type { SearchResult } from '@/types/search'

describe('evidence links', () => {
  const sources = [{ citation_id: 1, document_title: '相似制度 V1', url: 'https://example.test/doc' }] as SearchResult[]
  it('links exact references and strips dangling references', () => {
    expect(linkEvidence('结论 [1] [9]', sources)).toBe('结论 [1](<https://example.test/doc>) ')
    expect(linkEvidence('《相似制度》', sources)).toBe('《相似制度》')
  })
  it('keeps plain marker when citation has no safe url', () => {
    const noUrl = [{ citation_id: 1, document_title: '本地文档' }] as SearchResult[]
    expect(linkEvidence('见 [1]', noUrl)).toBe('见 [1]')
  })
  it('strips all markers when no citations resolved', () => {
    expect(linkEvidence('基准分为 100 分 [1]。', [])).toBe('基准分为 100 分 。')
  })
  it('does not rewrite code or an existing markdown link', () => {
    expect(linkEvidence('`[1]`\n```\n[1]\n```\n[1](https://test)', sources))
      .toBe('`[1]`\n```\n[1]\n```\n[1](https://test)')
  })
  it('rejects executable URLs and credentials', () => {
    for (const url of ['javascript:alert(1)', 'data:text/html,evil', 'https://name:secret@host', 'invalid']) {
      expect(citationUrl({ url })).toBe('')
    }
  })
})
