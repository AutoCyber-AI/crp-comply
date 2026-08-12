// Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
// Licensed under Elastic License 2.0 - see LICENSE.md for details.
//
// Reasoning Timeline - Phase 7.17
// ────────────────────────────────
// A compact, progressive-disclosure UI for the agent's reasoning tape.
// Built from the same `LoopEvent` stream as `ReasoningTape` but
// optimised for the live chat surface:
//
//   * One-line entries (icon + title + meta), not boxy cards.
//   * Consecutive ``loop.thought.delta`` events collapse into a single
//     "Reasoning" entry whose live text streams in-place.
//   * Tool call + tool result pair into a single timeline node so we
//     don't show two boxes per RAG lookup.
//   * Step entries collapse into a single "Step N - intent" node.
//   * The whole timeline lives in a single bounded-height scroll
//     container so the chat composer is always visible.
//   * Click any node to expand its raw payload.
//
// This intentionally does NOT replace `ReasoningTape` - that
// component remains the authoritative full-fidelity audit view. This
// component is the user-friendly progressive-disclosure projection.

import { useMemo, useState } from 'react'
import clsx from 'clsx'
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  FileText,
  Globe,
  HelpCircle,
  Lightbulb,
  ListChecks,
  Network,
  PauseCircle,
  Search,
  Sparkles,
  XCircle,
  Zap,
} from 'lucide-react'
import type { LoopEvent } from '@/lib/loopEvents'

interface TimelineNode {
  key: string
  ts: number
  kind:
    | 'opened'
    | 'triage'
    | 'cache'
    | 'plan'
    | 'step'
    | 'thought'
    | 'tool'
    | 'web'
    | 'ckf'
    | 'reflection'
    | 'clarifier'
    | 'recipe'
    | 'final'
    | 'error'
    | 'abort'
    | 'other'
  title: string
  meta?: string
  body?: string
  ok?: boolean | null
  events: LoopEvent[]
}

// ── Aggregate raw events into timeline nodes ─────────────────────

function aggregate(events: LoopEvent[]): TimelineNode[] {
  const out: TimelineNode[] = []
  let activeStep: TimelineNode | null = null
  let activeThought: TimelineNode | null = null

  const push = (node: TimelineNode) => {
    activeThought = null
    out.push(node)
  }

  for (let i = 0; i < events.length; i++) {
    const ev = events[i]
    switch (ev.event) {
      case 'loop.opened':
        // Render only once even if the backend re-emits.
        if (out.some((n) => n.kind === 'opened')) break
        push({
          key: `o-${i}`,
          ts: ev.ts,
          kind: 'opened',
          title: 'Session started',
          meta: ev.model ? `model: ${ev.model}` : undefined,
          body: ev.query
            ? `"${ev.query.length > 220 ? ev.query.slice(0, 220) + '…' : ev.query}"`
            : undefined,
          events: [ev],
        })
        break

      case 'loop.triage':
        push({
          key: `t-${i}`,
          ts: ev.ts,
          kind: 'triage',
          title: `Intent · ${ev.intent}`,
          meta: `${(ev.confidence * 100).toFixed(0)}% · ${ev.lane} lane${
            ev.slots?.depth ? ` · ${ev.slots.depth}` : ''
          }`,
          body: ev.reasoning,
          events: [ev],
        })
        break

      case 'loop.cache.hit':
        push({
          key: `ch-${i}`,
          ts: ev.ts,
          kind: 'cache',
          title: 'Cache hit',
          meta: `${ev.key_kind}${
            typeof ev.similarity === 'number'
              ? ` · sim ${(ev.similarity * 100).toFixed(0)}%`
              : ''
          } · ${ev.citations?.length ?? 0} citation(s)`,
          ok: true,
          events: [ev],
        })
        break

      case 'loop.cache.miss':
        push({
          key: `cm-${i}`,
          ts: ev.ts,
          kind: 'cache',
          title: 'Cache miss',
          meta:
            typeof ev.lookup_ms === 'number'
              ? `${ev.key_kind} · lookup ${ev.lookup_ms.toFixed(1)}ms`
              : ev.key_kind,
          ok: false,
          events: [ev],
        })
        break

      case 'loop.plan':
        push({
          key: `p-${i}`,
          ts: ev.ts,
          kind: 'plan',
          title: `Plan · ${ev.steps.length} step${ev.steps.length === 1 ? '' : 's'}${ev.depth ? ` · ${ev.depth}` : ''}`,
          body: ev.steps
            .map(
              (s, k) =>
                `${k + 1}. ${s.intent}${s.tool_hint ? ` → ${s.tool_hint}` : ''}`
            )
            .join('\n'),
          events: [ev],
        })
        break

      case 'loop.step.start':
        activeStep = {
          key: `s-${ev.step_id}-${i}`,
          ts: ev.ts,
          kind: 'step',
          title: `Step ${ev.step_id}`,
          meta: ev.intent,
          events: [ev],
        }
        push(activeStep)
        break

      case 'loop.step.end':
        if (activeStep && out.length) {
          activeStep.events.push(ev)
          activeStep.ok = ev.status === 'ok'
          activeStep.title = `Step ${ev.step_id} · ${ev.status}`
          activeStep = null
        } else {
          push({
            key: `se-${i}`,
            ts: ev.ts,
            kind: 'step',
            title: `Step ${ev.step_id} · ${ev.status}`,
            ok: ev.status === 'ok',
            events: [ev],
          })
        }
        break

      case 'loop.thought.delta':
        // Collapse consecutive deltas into one streaming node.
        if (activeThought) {
          activeThought.body = (activeThought.body || '') + ev.text
          activeThought.events.push(ev)
        } else {
          activeThought = {
            key: `th-${i}`,
            ts: ev.ts,
            kind: 'thought',
            title: 'Reasoning',
            body: ev.text,
            events: [ev],
          }
          out.push(activeThought)
        }
        break

      case 'loop.tool.call': {
        const node: TimelineNode = {
          key: `tc-${i}`,
          ts: ev.ts,
          kind: 'tool',
          title: `Tool · ${ev.tool}`,
          meta:
            ev.args && Object.keys(ev.args).length
              ? `args: ${Object.keys(ev.args).join(', ')}`
              : '(no args)',
          events: [ev],
        }
        push(node)
        break
      }

      case 'loop.tool.result': {
        // Pair with the most recent unmatched tool-call node.
        const last = [...out].reverse().find(
          (n) => n.kind === 'tool' && n.events.length === 1
        )
        if (last) {
          last.events.push(ev)
          last.ok = !ev.error
          last.title = `Tool · ${ev.tool}${ev.error ? ' · failed' : ''}`
          if (ev.error) {
            last.body = ev.error
          } else if (ev.summary) {
            last.body = ev.summary
          }
          if (ev.citations?.length) {
            last.meta =
              (last.meta ? last.meta + ' · ' : '') +
              `${ev.citations.length} citation(s)`
          }
        } else {
          push({
            key: `tr-${i}`,
            ts: ev.ts,
            kind: 'tool',
            title: `Tool result · ${ev.tool}`,
            ok: !ev.error,
            body: ev.error || ev.summary,
            events: [ev],
          })
        }
        break
      }

      case 'loop.web.start':
        push({
          key: `ws-${i}`,
          ts: ev.ts,
          kind: 'web',
          title: 'Web search',
          meta: `${ev.backend} · ${ev.freshness ?? 'any'}${
            ev.profile ? ' · ' + ev.profile : ''
          }`,
          body: `"${ev.query}"`,
          events: [ev],
        })
        break

      case 'loop.web.result': {
        const last = [...out].reverse().find(
          (n) => n.kind === 'web' && n.events.length === 1
        )
        const summary = `${ev.hits.length} hit(s)${
          (ev.blocked ?? 0) > 0 ? ` · ${ev.blocked} blocked` : ''
        }`
        if (last) {
          last.events.push(ev)
          last.ok = true
          last.meta = (last.meta ? last.meta + ' · ' : '') + summary
        } else {
          push({
            key: `wr-${i}`,
            ts: ev.ts,
            kind: 'web',
            title: 'Web result',
            meta: summary,
            ok: true,
            events: [ev],
          })
        }
        break
      }

      case 'loop.web.expand':
        push({
          key: `we-${i}`,
          ts: ev.ts,
          kind: 'web',
          title: 'Web expansion',
          meta: `${ev.intent} · ${ev.sub_queries.length} sub-query${ev.sub_queries.length === 1 ? '' : 'ies'}`,
          body: ev.sub_queries.join('\n'),
          events: [ev],
        })
        break

      case 'loop.web.rerank':
        push({
          key: `wrr-${i}`,
          ts: ev.ts,
          kind: 'web',
          title: 'Web rerank',
          meta: `${ev.candidates_in} → ${ev.candidates_out}${ev.model ? ` · ${ev.model}` : ''}`,
          events: [ev],
        })
        break

      case 'loop.web.cite':
        push({
          key: `wc-${i}`,
          ts: ev.ts,
          kind: 'web',
          title: 'Web citation',
          meta: `${ev.source_id} · score ${(ev.score * 100).toFixed(0)}%`,
          body: ev.excerpt,
          events: [ev],
        })
        break

      case 'loop.ckf.query':
        push({
          key: `ckf-${i}`,
          ts: ev.ts,
          kind: 'ckf',
          title: `CKF · ${ev.mode}`,
          meta: `${ev.scope} · ${ev.hits ?? 0} hit(s)${
            typeof ev.top_confidence === 'number'
              ? ` · ${(ev.top_confidence * 100).toFixed(0)}%`
              : ''
          }`,
          events: [ev],
        })
        break

      case 'loop.phase.complete':
        push({
          key: `ph-${i}`,
          ts: ev.ts,
          kind: 'plan',
          title: `Phase complete · ${ev.phase}`,
          meta: `${ev.facts_gathered ?? 0} fact(s) · ${ev.citations_count ?? 0} citation(s)`,
          events: [ev],
        })
        break

      case 'loop.reflection':
        push({
          key: `r-${i}`,
          ts: ev.ts,
          kind: 'reflection',
          title: `Reflection · ${ev.verdict}`,
          body: ev.notes,
          ok: ev.verdict === 'ok',
          events: [ev],
        })
        break

      case 'loop.clarifier.ask':
        push({
          key: `ca-${i}`,
          ts: ev.ts,
          kind: 'clarifier',
          title: 'Question for you',
          body: ev.question,
          meta:
            ev.options && ev.options.length
              ? `options: ${ev.options.join(' · ')}`
              : undefined,
          events: [ev],
        })
        break

      case 'loop.clarifier.answer':
        push({
          key: `cn-${i}`,
          ts: ev.ts,
          kind: 'clarifier',
          title: 'Answered',
          body: `${ev.slot_id}: ${ev.answer}`,
          ok: true,
          events: [ev],
        })
        break

      case 'loop.recipe.start':
        push({
          key: `rs-${i}`,
          ts: ev.ts,
          kind: 'recipe',
          title: `Recipe · ${ev.recipe_id}`,
          events: [ev],
        })
        break

      case 'loop.recipe.delta':
        push({
          key: `rd-${i}`,
          ts: ev.ts,
          kind: 'recipe',
          title: `Recipe · ${ev.kind}`,
          body: ev.text,
          events: [ev],
        })
        break

      case 'loop.recipe.done':
        push({
          key: `rdn-${i}`,
          ts: ev.ts,
          kind: 'recipe',
          title: 'Recipe complete',
          meta: `${ev.recipe_id} → ${ev.artefact_id}`,
          ok: true,
          events: [ev],
        })
        break

      case 'loop.final':
        push({
          key: `f-${i}`,
          ts: ev.ts,
          kind: 'final',
          title: 'Final answer ready',
          meta: `${ev.total_steps ?? 0} step(s)${
            ev.artefacts?.length ? ` · ${ev.artefacts.length} artefact(s)` : ''
          }`,
          ok: true,
          events: [ev],
        })
        break

      case 'loop.error':
        push({
          key: `e-${i}`,
          ts: ev.ts,
          kind: 'error',
          title: 'Error',
          body: ev.message,
          ok: false,
          events: [ev],
        })
        break

      case 'loop.abort':
        push({
          key: `ab-${i}`,
          ts: ev.ts,
          kind: 'abort',
          title: `Aborted · ${ev.dimension}`,
          meta: `used ${ev.usage} of ${ev.limit}`,
          ok: false,
          events: [ev],
        })
        break

      case 'loop.heartbeat':
        // Hide heartbeats from the user-facing timeline.
        break

      case 'loop.pii_warning':
        push({
          key: `pii-${i}`,
          ts: ev.ts,
          kind: 'other',
          title: 'PII detected in pipeline',
          meta: ev.categories?.length ? ev.categories.join(', ') : undefined,
          ok: false,
          events: [ev],
        })
        break

      default:
        // Unknown / future event types: keep them visible but quiet.
        push({
          key: `x-${i}`,
          ts: (ev as { ts: number }).ts,
          kind: 'other',
          title: (ev as { event: string }).event,
          events: [ev as LoopEvent],
        })
    }
  }
  return out
}

// ── Icon lookup ──────────────────────────────────────────────────

function NodeIcon({ kind, ok }: { kind: TimelineNode['kind']; ok?: boolean | null }) {
  const cls = 'h-3.5 w-3.5'
  if (ok === false) return <XCircle className={clsx(cls, 'text-rose-600')} />
  switch (kind) {
    case 'opened':
      return <Sparkles className={clsx(cls, 'text-violet-600')} />
    case 'triage':
      return <Zap className={clsx(cls, 'text-amber-600')} />
    case 'cache':
      return <Database className={clsx(cls, 'text-emerald-600')} />
    case 'plan':
      return <ListChecks className={clsx(cls, 'text-sky-600')} />
    case 'step':
      return <ChevronRight className={clsx(cls, 'text-slate-600')} />
    case 'thought':
      return <Brain className={clsx(cls, 'text-indigo-600')} />
    case 'tool':
      return <Search className={clsx(cls, 'text-sky-700')} />
    case 'web':
      return <Globe className={clsx(cls, 'text-emerald-700')} />
    case 'ckf':
      return <Network className={clsx(cls, 'text-fuchsia-700')} />
    case 'reflection':
      return <Lightbulb className={clsx(cls, 'text-amber-700')} />
    case 'clarifier':
      return <HelpCircle className={clsx(cls, 'text-amber-700')} />
    case 'recipe':
      return <FileText className={clsx(cls, 'text-slate-700')} />
    case 'final':
      return <CheckCircle2 className={clsx(cls, 'text-emerald-700')} />
    case 'error':
      return <XCircle className={clsx(cls, 'text-rose-600')} />
    case 'abort':
      return <PauseCircle className={clsx(cls, 'text-rose-600')} />
    default:
      return <ChevronRight className={clsx(cls, 'text-slate-600')} />
  }
}

function fmtTime(ts: number): string {
  if (!ts) return ''
  try {
    return new Date(ts * 1000).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return ''
  }
}

// ── Component ────────────────────────────────────────────────────

export interface ReasoningTimelineProps {
  events: LoopEvent[]
  /** Compact (default) vs. full-fidelity audit. */
  compact?: boolean
  /** Max body characters shown before truncation in compact mode. */
  maxBodyChars?: number
  className?: string
  /** Render only the last N nodes (live mode). */
  tailOnly?: number
}

export default function ReasoningTimeline({
  events,
  compact = true,
  maxBodyChars = 240,
  className,
  tailOnly,
}: ReasoningTimelineProps) {
  const nodes = useMemo(() => aggregate(events), [events])
  const visible = useMemo(
    () => (typeof tailOnly === 'number' ? nodes.slice(-tailOnly) : nodes),
    [nodes, tailOnly]
  )
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())

  if (visible.length === 0) {
    return null
  }

  return (
    <ol
      className={clsx(
        'relative space-y-1 text-[13px]',
        compact ? '' : 'text-sm',
        className
      )}
      aria-label="Agent reasoning timeline"
    >
      {/* Vertical rail */}
      <div
        aria-hidden="true"
        className="absolute left-[7px] top-1.5 bottom-1.5 w-px bg-hairline"
      />
      {visible.map((node) => {
        const isExpanded = expanded.has(node.key)
        const body = node.body || ''
        const showExpandBody =
          body.length > maxBodyChars || node.events.length > 0
        const displayBody =
          isExpanded || body.length <= maxBodyChars
            ? body
            : body.slice(0, maxBodyChars) + '…'
        return (
          <li key={node.key} className="relative pl-6">
            <span className="absolute left-0 top-1 grid h-4 w-4 place-items-center rounded-full bg-surface ring-1 ring-hairline">
              <NodeIcon kind={node.kind} ok={node.ok ?? null} />
            </span>
            <button
              type="button"
              onClick={() =>
                setExpanded((prev) => {
                  const next = new Set(prev)
                  if (next.has(node.key)) next.delete(node.key)
                  else next.add(node.key)
                  return next
                })
              }
              className="flex w-full items-baseline gap-2 rounded text-left hover:bg-surface-2 px-1 py-0.5 focus:outline-none focus:ring-2 focus:ring-primary/40"
              aria-expanded={isExpanded}
            >
              {showExpandBody ? (
                isExpanded ? (
                  <ChevronDown className="h-3 w-3 shrink-0 text-ink-3" />
                ) : (
                  <ChevronRight className="h-3 w-3 shrink-0 text-ink-3" />
                )
              ) : (
                <span className="inline-block w-3 shrink-0" aria-hidden="true" />
              )}
              <span className="font-medium text-ink-1">{node.title}</span>
              {node.meta ? (
                <span className="truncate text-ink-3 text-xs">
                  {node.meta}
                </span>
              ) : null}
              <span className="ml-auto shrink-0 font-mono text-xs text-ink-4">
                {fmtTime(node.ts)}
              </span>
            </button>
            {body ? (
              <div
                className={clsx(
                  'ml-4 mt-0.5 whitespace-pre-wrap text-ink-2',
                  isExpanded ? 'text-[12px]' : 'text-[11.5px] line-clamp-3'
                )}
              >
                {displayBody}
              </div>
            ) : null}
            {isExpanded && node.events.length > 0 && (
              <pre className="ml-4 mt-1 max-h-48 overflow-auto rounded bg-surface-2 p-2 text-xs text-ink-3 ring-1 ring-hairline">
                {JSON.stringify(node.events, null, 2)}
              </pre>
            )}
          </li>
        )
      })}
    </ol>
  )
}
