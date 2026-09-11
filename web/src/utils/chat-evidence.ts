import type { SearchResult } from '@/types/search'

export function citationUrl(citation: Partial<SearchResult>): string {
  const value = citation.url || citation.preview_url || ''
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) && !url.username ? url.href : ''
  } catch {
    return ''
  }
}

/** Only exact server-issued numbers resolve to evidence; similar titles are ambiguous. */
export function linkEvidence(markdown: string, citations: SearchResult[] = []): string {
  const byId = new Map(citations.map((c, i) => [c.citation_id || i + 1, c]))
  return markdown.split(/(```[\s\S]*?```|`[^`\n]*`)/g).map((part) => {
    if (part.startsWith('`')) return part
    return part.replace(/\[(\d+)\](?![([])/g, (whole, id: string) => {
      const citation = byId.get(Number(id))
      const url = citation ? citationUrl(citation) : ''
      return url ? `[${id}](<${url.replace(/>/g, '%3E')}>)` : whole
    })
  }).join('')
}
