import {
  Copy,
  Download,
  Save,
  AlertTriangle,
  Sparkles,
} from 'lucide-react'
import type { RecipeRunResponse } from '../../lib/api'
import {
  Card,
  Button,
  Chip,
  ProvenancePill,
  Tooltip,
} from '../../design/primitives'
import { ConfidenceLabel } from './ConfidenceLabel'
import { LazyMarkdown as Markdown } from '../../design/LazyMarkdown'
import { parseMarkdownSections, renderCitationsFor } from './binderHelpers'

type RunStage = 'idle' | 'streaming' | 'done' | 'error'

export interface LiveBinderProps {
  result: RecipeRunResponse
  revealedCount: number
  stage: RunStage
  savingToVault: boolean
  onSaveToVault: () => void
  onLoadCitationSummary?: (citation: string) => Promise<string>
}

export function LiveBinder({
  result,
  revealedCount,
  stage,
  savingToVault,
  onSaveToVault,
  onLoadCitationSummary,
}: LiveBinderProps) {
  // Prefer the structured ``json_payload.sections`` (carries per-paragraph
  // provenance) when present; fall back to markdown-heading parsing for
  // deliverables produced by older backend versions.
  const structured = Array.isArray(result.json_payload?.sections)
    ? (result.json_payload!.sections as NonNullable<typeof result.json_payload.sections>)
    : null
  const markdownSections = parseMarkdownSections(result.markdown)
  const sections = structured && structured.length > 0
    ? structured.map((s) => ({ heading: s.title || s.id, body: s.text || '', paragraphs: s.paragraphs, id: s.id }))
    : markdownSections.map((s) => ({ heading: s.heading, body: s.body, paragraphs: undefined as undefined | unknown, id: s.heading }))
  const visible = sections.slice(0, revealedCount || sections.length)

  const copyMarkdown = () => {
    navigator.clipboard.writeText(result.markdown).catch(() => {})
  }

  const downloadMarkdown = () => {
    const blob = new Blob([result.markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${result.recipe_id}.md`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <article className="space-y-6 animate-fade-in">
      {/* Deliverable header */}
      <header className="flex items-start gap-4">
        <div className="flex-1">
          <div className="text-xs font-mono text-ink-3">{result.regulation}</div>
          <h1 className="text-display text-2xl font-bold tracking-tight">{result.title}</h1>
          <div className="flex items-center gap-2 mt-2">
            <Chip tone="success">Draft ready</Chip>
            <ConfidenceLabel score={result.overall_confidence} />
            <Chip className="chip-mono">{(result.duration_ms / 1000).toFixed(1)}s</Chip>
            <Chip className="chip-mono">{sections.length} sections</Chip>
          </div>
        </div>
        <div className="flex gap-2">
          <Tooltip label={result.markdown ? "Copy the rendered markdown to your clipboard" : "Markdown will be ready once drafting finishes"} side="bottom">
            <Button variant="outline" size="sm" iconLeft={<Copy className="h-3.5 w-3.5" />} onClick={copyMarkdown} disabled={!result.markdown}>Copy</Button>
          </Tooltip>
          <Tooltip label={result.markdown ? "Download as a .md file" : "Markdown will be ready once drafting finishes"} side="bottom">
            <Button variant="outline" size="sm" iconLeft={<Download className="h-3.5 w-3.5" />} onClick={downloadMarkdown} disabled={!result.markdown}>Markdown</Button>
          </Tooltip>
          <Tooltip
            label={
              result.report_id
                ? 'Persist this draft and its report to your vault'
                : 'Report ID not available yet - wait for the run to finish or retry.'
            }
            side="bottom"
          >
            <Button
              variant="primary"
              size="sm"
              iconLeft={<Save className="h-3.5 w-3.5" />}
              disabled={!result.report_id || savingToVault}
              loading={savingToVault}
              onClick={onSaveToVault}
            >
              Save to vault
            </Button>
          </Tooltip>
        </div>
      </header>

      {/* Warnings */}
      {result.warnings.length > 0 && (
        <Card className="!p-4 border-warning">
          <div className="flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
            <div className="text-xs space-y-1">
              {result.warnings.map((w, i) => <div key={i}>{w}</div>)}
            </div>
          </div>
        </Card>
      )}

      {/* Sections */}
      {visible.map((s, i) => {
        const paragraphs = Array.isArray((s as { paragraphs?: unknown }).paragraphs)
          ? ((s as { paragraphs: Array<{ text: string; provenance?: Array<{ kind: string; ref: string; label?: string }> }> }).paragraphs)
          : null
        return (
        <Card key={i} className="!p-6 animate-slide-up" style={{ animationDelay: `${i * 40}ms` }}>
          <h2 className="text-display text-lg font-semibold mb-2">{s.heading}</h2>
          {paragraphs && paragraphs.length > 0 ? (
            <div className="space-y-4">
              {paragraphs.map((p, pi) => (
                <div key={pi} className="space-y-1.5">
                  <Markdown>{p.text}</Markdown>
                  {p.provenance && p.provenance.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {p.provenance.map((prov, provIdx) => (
                        <ProvenancePill
                          key={provIdx}
                          kind={(prov.kind as Parameters<typeof ProvenancePill>[0]['kind']) || 'unsourced'}
                          refText={prov.ref}
                          label={prov.label}
                        />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <Markdown>{s.body}</Markdown>
          )}
          {/* Citations */}
          {renderCitationsFor(result, i, onLoadCitationSummary) && (
            <div className="mt-4 pt-4 border-t border-hairline flex flex-wrap gap-1.5">
              <span className="text-xs uppercase tracking-wider text-ink-3 mr-1 self-center">Citations</span>
              {renderCitationsFor(result, i, onLoadCitationSummary)}
            </div>
          )}
        </Card>
        )
      })}

      {/* Staggered-reveal hint during streaming */}
      {stage === 'streaming' && revealedCount < sections.length && (
        <div className="flex items-center gap-2 text-xs text-ink-3 py-4">
          <Sparkles className="h-3 w-3 animate-pulse" />
          Drafting section {revealedCount + 1} of {sections.length}…
        </div>
      )}
    </article>
  )
}
