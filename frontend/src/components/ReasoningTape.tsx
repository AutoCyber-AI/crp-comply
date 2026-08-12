// Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
// Licensed under Elastic License 2.0 - see LICENSE.md for details.
//
// Reasoning Tape - Phase 7.11
// ────────────────────────────
// Always-mounted, never-collapsible event ribbon that renders the
// 22 typed loop events emitted by the language-agent loop. Per
// PHASE_7 §3.4 + §7.11:
//
//   • Lane banner (cache / fast / slow) anchored from ``loop.triage``.
//   • One renderer per event kind; unknown events get a "raw" card so
//     nothing is silently dropped.
//   • Trust-tier pills for web hits (T1 official → T4 muted).
//   • Scope pills for CKF queries (corpus / tenant / federated).
//   • Clarifier card - surfaces the most recent unanswered question.
//   • Keyboard navigation: ↑/↓ moves focus, Enter/Space toggles a
//     card's expanded state, Escape collapses the active card. The
//     tape itself never collapses.
//
// No-bypass guarantees:
//   • The tape consumes raw events from the SSE stream without
//     client-side filtering.
//   • Placeholder cards are forbidden - every card corresponds to a
//     real event the backend emitted.

import { useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import type {
  LoopEvent,
  LoopEventName,
  TrustTier,
} from '@/lib/loopEvents'

// ─── Helpers ────────────────────────────────────────────────────

function fmtTime(ts: number): string {
  if (!ts) return ''
  try {
    const d = new Date(ts * 1000)
    return d.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return ''
  }
}

function trustTierLabel(tier: TrustTier): string {
  return (
    {
      1: 'T1 · Regulator',
      2: 'T2 · Standards body',
      3: 'T3 · Industry analysis',
      4: 'T4 · Other',
    } as const
  )[tier]
}

function trustTierColor(tier: TrustTier): string {
  return (
    {
      1: 'bg-emerald-100 text-emerald-900 ring-emerald-300',
      2: 'bg-sky-100 text-sky-900 ring-sky-300',
      3: 'bg-slate-100 text-slate-800 ring-slate-300',
      4: 'bg-zinc-100 text-zinc-700 ring-zinc-300',
    } as const
  )[tier]
}

function laneClasses(lane: 'cache' | 'fast' | 'slow'): string {
  return (
    {
      cache: 'bg-emerald-50 border-emerald-200 text-emerald-900',
      fast: 'bg-sky-50 border-sky-200 text-sky-900',
      slow: 'bg-amber-50 border-amber-200 text-amber-900',
    } as const
  )[lane]
}

// ─── Pills ──────────────────────────────────────────────────────

export function TrustTierPill({ tier }: { tier: TrustTier }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1',
        trustTierColor(tier)
      )}
      aria-label={trustTierLabel(tier)}
    >
      {trustTierLabel(tier)}
    </span>
  )
}

export function ScopePill({ scope }: { scope: 'corpus' | 'tenant' | 'federated' }) {
  const cls = (
    {
      corpus: 'bg-indigo-100 text-indigo-900 ring-indigo-300',
      tenant: 'bg-violet-100 text-violet-900 ring-violet-300',
      federated: 'bg-fuchsia-100 text-fuchsia-900 ring-fuchsia-300',
    } as const
  )[scope]
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1',
        cls
      )}
    >
      {scope}
    </span>
  )
}

// ─── Lane banner ────────────────────────────────────────────────

export function LaneBanner({
  lane,
  complexity,
  intent,
  reasoning,
  confidence,
}: {
  lane: 'cache' | 'fast' | 'slow'
  complexity: string
  intent: string
  reasoning?: string
  confidence?: number
}) {
  return (
    <div
      role="status"
      className={clsx(
        'flex items-start gap-3 rounded-lg border px-3 py-2 text-sm',
        laneClasses(lane)
      )}
    >
      <span className="rounded-md bg-white/60 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ring-1 ring-current/20">
        {lane} lane
      </span>
      <div className="min-w-0 flex-1">
        <div className="font-medium">
          {complexity} · {intent}
        </div>
        {reasoning ? <div className="text-xs opacity-75">{reasoning}</div> : null}
      </div>
      {typeof confidence === 'number' ? (
        <div className="shrink-0 text-xs opacity-75">
          {Math.round(confidence * 100)}% conf
        </div>
      ) : null}
    </div>
  )
}

// ─── Per-event renderers ────────────────────────────────────────

interface CardProps {
  evt: LoopEvent
  expanded: boolean
}

function CardHeader({
  label,
  ts,
  tone = 'default',
}: {
  label: string
  ts: number
  tone?: 'default' | 'success' | 'warn' | 'error' | 'muted'
}) {
  const toneCls = (
    {
      default: 'text-slate-900',
      success: 'text-emerald-800',
      warn: 'text-amber-800',
      error: 'text-rose-800',
      muted: 'text-slate-600',
    } as const
  )[tone]
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className={clsx('font-semibold uppercase tracking-wide', toneCls)}>
        {label}
      </span>
      <span className="font-mono text-slate-600">{fmtTime(ts)}</span>
    </div>
  )
}

function RawJSON({ value }: { value: unknown }) {
  return (
    <pre className="mt-2 max-h-64 overflow-auto rounded bg-slate-50 p-2 text-xs text-slate-700 ring-1 ring-slate-200">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

function renderCard({ evt, expanded }: CardProps): JSX.Element {
  switch (evt.event) {
    case 'loop.opened':
      return (
        <div>
          <CardHeader label="Session opened" ts={evt.ts} />
          <div className="mt-1 text-sm text-slate-800">"{evt.query}"</div>
          {evt.model ? (
            <div className="mt-0.5 text-xs text-slate-600">model: {evt.model}</div>
          ) : null}
        </div>
      )

    case 'loop.plan':
      return (
        <div>
          <CardHeader label="Plan" ts={evt.ts} />
          <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-sm text-slate-800">
            {evt.steps.map((s) => (
              <li key={s.id}>
                <span className="font-medium">{s.intent}</span>
                {s.tool_hint ? (
                  <span className="text-slate-600"> → {s.tool_hint}</span>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      )

    case 'loop.step.start':
      return (
        <div>
          <CardHeader label={`Step ${evt.step_id} · start`} ts={evt.ts} tone="muted" />
          <div className="mt-1 text-sm text-slate-700">{evt.intent}</div>
          {evt.attempt && evt.attempt > 1 ? (
            <div className="text-xs text-slate-600">attempt #{evt.attempt}</div>
          ) : null}
        </div>
      )

    case 'loop.thought.delta':
      return (
        <div>
          <CardHeader label="Thought" ts={evt.ts} tone="muted" />
          <div className="mt-1 whitespace-pre-wrap text-sm text-slate-700">
            {evt.text}
          </div>
        </div>
      )

    case 'loop.tool.call':
      return (
        <div>
          <CardHeader label={`Tool · ${evt.tool}`} ts={evt.ts} />
          <div className="mt-1 text-xs text-slate-600">
            args: {Object.keys(evt.args || {}).join(', ') || '(none)'}
          </div>
          {expanded ? <RawJSON value={evt.args} /> : null}
        </div>
      )

    case 'loop.tool.result': {
      const tone = evt.error ? 'error' : 'success'
      return (
        <div>
          <CardHeader label={`Tool result · ${evt.tool}`} ts={evt.ts} tone={tone} />
          {evt.error ? (
            <div className="mt-1 text-sm text-rose-700">{evt.error}</div>
          ) : (
            <div className="mt-1 text-sm text-slate-700">
              {evt.summary || '(no summary)'}
            </div>
          )}
          {evt.citations && evt.citations.length ? (
            <div className="mt-1 text-xs text-slate-600">
              {evt.citations.length} citation(s)
            </div>
          ) : null}
        </div>
      )
    }

    case 'loop.reflection': {
      const tone =
        evt.verdict === 'ok'
          ? 'success'
          : evt.verdict === 'abort'
            ? 'error'
            : 'warn'
      return (
        <div>
          <CardHeader label={`Reflection · ${evt.verdict}`} ts={evt.ts} tone={tone} />
          {evt.notes ? (
            <div className="mt-1 text-sm text-slate-700">{evt.notes}</div>
          ) : null}
        </div>
      )
    }

    case 'loop.clarifier.ask':
      return (
        <div>
          <CardHeader label="Clarifier needs an answer" ts={evt.ts} tone="warn" />
          <div className="mt-1 text-sm font-medium text-slate-900">
            {evt.question}
          </div>
          {evt.options && evt.options.length ? (
            <ul className="mt-1 list-disc pl-5 text-sm text-slate-700">
              {evt.options.map((o, i) => (
                <li key={i}>{o}</li>
              ))}
            </ul>
          ) : null}
          <div className="mt-1 text-xs text-slate-600">slot: {evt.slot_id}</div>
        </div>
      )

    case 'loop.clarifier.answer':
      return (
        <div>
          <CardHeader label="Clarifier answered" ts={evt.ts} tone="success" />
          <div className="mt-1 text-sm text-slate-700">
            <span className="text-slate-600">{evt.slot_id}</span>: {evt.answer}
          </div>
        </div>
      )

    case 'loop.step.end': {
      const tone =
        evt.status === 'ok' ? 'success' : evt.status === 'failed' ? 'error' : 'muted'
      return (
        <div>
          <CardHeader
            label={`Step ${evt.step_id} · ${evt.status}`}
            ts={evt.ts}
            tone={tone}
          />
        </div>
      )
    }

    case 'loop.recipe.start':
      return (
        <div>
          <CardHeader label={`Recipe start · ${evt.recipe_id}`} ts={evt.ts} />
          {evt.inputs && Object.keys(evt.inputs).length ? (
            <div className="mt-1 text-xs text-slate-600">
              inputs: {Object.keys(evt.inputs).join(', ')}
            </div>
          ) : null}
        </div>
      )

    case 'loop.recipe.delta':
      return (
        <div>
          <CardHeader label={`Recipe · ${evt.kind}`} ts={evt.ts} tone="muted" />
          <div className="mt-1 text-sm text-slate-700">{evt.text}</div>
        </div>
      )

    case 'loop.recipe.done':
      return (
        <div>
          <CardHeader label="Recipe complete" ts={evt.ts} tone="success" />
          <div className="mt-1 text-sm text-slate-700">
            {evt.recipe_id} → artefact{' '}
            <span className="font-mono text-slate-900">{evt.artefact_id}</span>
          </div>
        </div>
      )

    case 'loop.final':
      return (
        <div>
          <CardHeader label="Final" ts={evt.ts} tone="success" />
          {evt.summary ? (
            <div className="mt-1 whitespace-pre-wrap text-sm text-slate-800">
              {evt.summary}
            </div>
          ) : null}
          {evt.artefacts && evt.artefacts.length ? (
            <div className="mt-1 text-xs text-slate-600">
              {evt.artefacts.length} artefact(s) ·{' '}
              {evt.total_steps ?? 0} step(s)
            </div>
          ) : null}
        </div>
      )

    case 'loop.error':
      return (
        <div>
          <CardHeader label="Error" ts={evt.ts} tone="error" />
          <div className="mt-1 text-sm text-rose-700">{evt.message}</div>
        </div>
      )

    case 'loop.abort':
      return (
        <div>
          <CardHeader
            label={`Aborted · ${evt.dimension}`}
            ts={evt.ts}
            tone="error"
          />
          <div className="mt-1 text-sm text-rose-700">
            {evt.detail
              ? `Loop stopped: ${evt.detail}`
              : `Loop stopped because the ${evt.dimension} budget was exceeded`}{' '}
            (used <span className="font-medium">{evt.usage}</span> of{' '}
            <span className="font-medium">{evt.limit}</span>).
          </div>
          {expanded && evt.totals ? (
            <pre className="mt-2 max-h-40 overflow-auto rounded bg-rose-50 p-2 text-xs text-rose-900">
              {JSON.stringify(evt.totals, null, 2)}
            </pre>
          ) : null}
        </div>
      )

    case 'loop.heartbeat':
      return (
        <div>
          <CardHeader label={`Heartbeat · ${evt.state ?? 'idle'}`} ts={evt.ts} tone="muted" />
        </div>
      )

    case 'loop.triage':
      return (
        <div>
          <CardHeader label={`Triage · ${evt.lane}`} ts={evt.ts} />
          <div className="mt-1 text-sm text-slate-800">
            {evt.complexity} · {evt.intent}
          </div>
          {evt.reasoning ? (
            <div className="text-xs text-slate-600">{evt.reasoning}</div>
          ) : null}
        </div>
      )

    case 'loop.cache.hit':
      return (
        <div>
          <CardHeader label={`Cache hit · ${evt.key_kind}`} ts={evt.ts} tone="success" />
          <div className="mt-1 text-xs text-slate-600">
            {typeof evt.similarity === 'number'
              ? `similarity ${evt.similarity.toFixed(2)} · `
              : ''}
            age {evt.age_seconds ?? 0}s ·{' '}
            {evt.citations?.length ?? 0} cached citation(s)
          </div>
        </div>
      )

    case 'loop.cache.miss':
      return (
        <div>
          <CardHeader label={`Cache miss · ${evt.key_kind}`} ts={evt.ts} tone="muted" />
          {typeof evt.lookup_ms === 'number' ? (
            <div className="mt-1 text-xs text-slate-600">
              lookup {evt.lookup_ms.toFixed(1)}ms
            </div>
          ) : null}
        </div>
      )

    case 'loop.web.start':
      return (
        <div>
          <CardHeader label={`Web search · ${evt.backend}`} ts={evt.ts} />
          <div className="mt-1 text-sm text-slate-800">"{evt.query}"</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <span>profile: {evt.profile ?? '(default)'}</span>
            <span>·</span>
            <span>freshness: {evt.freshness ?? 'any'}</span>
          </div>
        </div>
      )

    case 'loop.web.result':
      return (
        <div>
          <CardHeader
            label={`Web result · ${evt.backend} · ${evt.hits.length} hit(s)`}
            ts={evt.ts}
            tone="success"
          />
          <ul className="mt-1 space-y-1 text-sm text-slate-800">
            {evt.hits.slice(0, expanded ? 50 : 5).map((h, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <TrustTierPill tier={h.trust_tier} />
                <span className="font-medium text-slate-900">{h.domain}</span>
                {h.title ? <span className="text-slate-600">{h.title}</span> : null}
                {h.blocked ? (
                  <span className="text-xs text-rose-700">blocked</span>
                ) : null}
              </li>
            ))}
          </ul>
          {(evt.blocked ?? 0) > 0 ? (
            <div className="mt-1 text-xs text-rose-700">
              {evt.blocked} hit(s) blocked by trust filter
            </div>
          ) : null}
        </div>
      )

    case 'loop.ckf.query':
      return (
        <div>
          <CardHeader label={`CKF · ${evt.mode}`} ts={evt.ts} />
          <div className="mt-1 flex items-center gap-2 text-sm text-slate-700">
            <ScopePill scope={evt.scope} />
            <span>{evt.hits ?? 0} hit(s)</span>
            {typeof evt.top_confidence === 'number' ? (
              <span className="text-slate-600">
                · top confidence {(evt.top_confidence * 100).toFixed(0)}%
              </span>
            ) : null}
          </div>
        </div>
      )

    case 'loop.pii_warning':
      return (
        <div>
          <CardHeader label="PII detected in pipeline" ts={evt.ts} tone="warn" />
          <div className="mt-1 text-sm text-amber-700">
            {evt.categories && evt.categories.length
              ? `Categories: ${evt.categories.join(', ')}`
              : 'Personal data detected'}
            {evt.source ? ` · source: ${evt.source}` : null}
          </div>
        </div>
      )

    default: {
      // Should be unreachable per the LoopEvent union; we keep this
      // defensive branch so a backend that ships ahead of the
      // frontend doesn't dead-letter - the operator can still see
      // the raw payload in dev tools.
      const fallback = evt as { event: string; ts: number }
      return (
        <div>
          <CardHeader label={fallback.event} ts={fallback.ts} tone="warn" />
          <RawJSON value={evt} />
        </div>
      )
    }
  }
}

// ─── Tape ───────────────────────────────────────────────────────

export interface ReasoningTapeProps {
  events: LoopEvent[]
  className?: string
  emptyMessage?: string
}

/**
 * The reasoning tape itself. Always-mounted, never collapsible.
 *
 * Keyboard navigation:
 *   ArrowUp / ArrowDown : move focus between cards
 *   Enter / Space        : toggle the active card's expanded state
 *   Escape               : collapse the active card
 *
 * Cards are expanded for richer detail (raw JSON, full hit list).
 * Card identity uses the array index because the tape is append-only
 * within a session - events never reorder retroactively.
 */
export default function ReasoningTape({
  events,
  className,
  emptyMessage = 'Waiting for the agent to start reasoning…',
}: ReasoningTapeProps) {
  const [active, setActive] = useState<number>(-1)
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set())
  const tapeRef = useRef<HTMLDivElement>(null)

  // Pin the lane banner from the most recent triage event.
  const triage = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i]
      if (e.event === 'loop.triage') return e
    }
    return null
  }, [events])

  // Auto-scroll to bottom when new events arrive - matches the
  // reasoning-tape "live ribbon" feel.
  useEffect(() => {
    const el = tapeRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [events.length])

  function onKey(e: React.KeyboardEvent) {
    if (events.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(events.length - 1, Math.max(0, i + 1)))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(0, i === -1 ? events.length - 1 : i - 1))
    } else if (e.key === 'Enter' || e.key === ' ') {
      if (active < 0) return
      e.preventDefault()
      setExpanded((prev) => {
        const next = new Set(prev)
        if (next.has(active)) next.delete(active)
        else next.add(active)
        return next
      })
    } else if (e.key === 'Escape') {
      if (active < 0) return
      e.preventDefault()
      setExpanded((prev) => {
        if (!prev.has(active)) return prev
        const next = new Set(prev)
        next.delete(active)
        return next
      })
    }
  }

  return (
    <section
      aria-label="Agent reasoning tape"
      className={clsx(
        'flex h-full min-h-[16rem] flex-col rounded-lg border border-slate-200 bg-white',
        className
      )}
    >
      <header className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
        <h2 className="text-sm font-semibold text-slate-800">Reasoning tape</h2>
        <span className="text-xs text-slate-600">
          {events.length} event{events.length === 1 ? '' : 's'}
        </span>
      </header>

      {triage ? (
        <div className="border-b border-slate-200 p-2">
          <LaneBanner
            lane={triage.lane}
            complexity={triage.complexity}
            intent={triage.intent}
            reasoning={triage.reasoning}
            confidence={triage.confidence}
          />
        </div>
      ) : null}

      <div
        ref={tapeRef}
        role="list"
        tabIndex={0}
        onKeyDown={onKey}
        aria-keyshortcuts="ArrowUp ArrowDown Enter Escape"
        className="flex-1 space-y-2 overflow-auto p-2 outline-none focus:ring-2 focus:ring-sky-200"
      >
        {events.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-600">
            {emptyMessage}
          </div>
        ) : (
          events.map((evt, i) => {
            const isActive = i === active
            const isExpanded = expanded.has(i)
            return (
              <article
                key={i}
                role="listitem"
                aria-current={isActive ? 'true' : undefined}
                aria-expanded={isExpanded}
                aria-label={`${evt.event} card`}
                onClick={() => setActive(i)}
                className={clsx(
                  'cursor-pointer rounded border bg-white px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'border-sky-400 ring-2 ring-sky-200'
                    : 'border-slate-200 hover:border-slate-300'
                )}
                data-event={evt.event as LoopEventName}
              >
                {renderCard({ evt, expanded: isExpanded })}
              </article>
            )
          })
        )}
      </div>
    </section>
  )
}
