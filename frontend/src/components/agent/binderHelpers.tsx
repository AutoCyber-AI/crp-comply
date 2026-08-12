import type { RecipeRunResponse } from '../../lib/api'
import { type ReactNode } from 'react'
import { CitationHoverCard } from './CitationHoverCard'

export interface ParsedSection { heading: string; body: string }

export function parseMarkdownSections(md: string): ParsedSection[] {
  if (!md) return []
  const lines = md.split('\n')
  const out: ParsedSection[] = []
  let cur: ParsedSection | null = null
  for (const line of lines) {
    const m = /^#{1,3}\s+(.*)$/.exec(line)
    if (m) {
      if (cur) out.push(cur)
      cur = { heading: m[1].trim(), body: '' }
    } else if (cur) {
      cur.body += (cur.body ? '\n' : '') + line
    }
  }
  if (cur) out.push(cur)
  // Trim trailing empty bodies.
  return out.map((s) => ({ ...s, body: s.body.trim() })).filter((s) => s.heading)
}

export function renderCitationsFor(
  result: RecipeRunResponse,
  idx: number,
  onLoadSummary?: (citation: string) => Promise<string>,
): ReactNode {
  const sectionKeys = Object.keys(result.section_citations)
  const key = sectionKeys[idx]
  if (!key) return null
  const cites = result.section_citations[key] ?? []
  if (cites.length === 0) return null
  return cites.map((c, i) => (
    <CitationHoverCard key={`${key}-${i}`} citation={c} onLoadSummary={onLoadSummary}>
      <span>{c}</span>
    </CitationHoverCard>
  ))
}
