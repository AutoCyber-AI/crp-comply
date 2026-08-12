// Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
// Licensed under Elastic License 2.0 - see LICENSE.md for details.
import { Loader2, Sparkles, Wrench, Search, BookOpen, BrainCircuit, FileText } from 'lucide-react'
import type { LoopEvent } from '../../lib/loopEvents'
import { Chip } from '../../design/primitives'

const PHASE_LABELS: Record<string, string> = {
  triage: 'Triage',
  plan: 'Planning',
  recall: 'Recalling facts',
  retrieve: 'Retrieving context',
  reason: 'Reasoning',
  reflect: 'Reflecting',
  clarify: 'Asking clarifier',
  synthesize: 'Synthesising answer',
  finalise: 'Finalising',
  done: 'Done',
}

const PHASE_ICONS: Record<string, typeof Sparkles> = {
  triage: Sparkles,
  plan: BrainCircuit,
  recall: BookOpen,
  retrieve: Search,
  reason: BrainCircuit,
  reflect: BrainCircuit,
  clarify: FileText,
  synthesize: Sparkles,
  finalise: Sparkles,
  done: Sparkles,
}

function normalisePhase(phase: string): string {
  const key = phase.toLowerCase().replace(/[^a-z]/g, '')
  if (key.includes('triag')) return 'triage'
  if (key.includes('plan')) return 'plan'
  if (key.includes('recall')) return 'recall'
  if (key.includes('retriev') || key.includes('search') || key.includes('fetch')) return 'retrieve'
  if (key.includes('reflect')) return 'reflect'
  if (key.includes('clarif')) return 'clarify'
  if (key.includes('synth') || key.includes('answer')) return 'synthesize'
  if (key.includes('final')) return 'finalise'
  if (key.includes('done') || key.includes('complete')) return 'done'
  if (key.includes('reason') || key.includes('think')) return 'reason'
  return 'reason'
}

function latestPhase(events: LoopEvent[]): { key: string; label: string } | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i]
    if (ev.event === 'loop.phase.complete') {
      const raw = (ev as LoopEvent & { phase?: string }).phase ?? ''
      const key = normalisePhase(raw)
      return { key, label: PHASE_LABELS[key] || raw || 'Processing' }
    }
    if (ev.event === 'loop.plan' && (ev as LoopEvent & { steps?: unknown[] }).steps) {
      return { key: 'plan', label: PHASE_LABELS.plan }
    }
    if (ev.event === 'loop.recipe.start') {
      return { key: 'synthesize', label: PHASE_LABELS.synthesize }
    }
  }
  return null
}

function recentTools(events: LoopEvent[]): Array<{ tool: string; status: 'running' | 'done' | 'error' }> {
  const tools = new Map<string, { tool: string; status: 'running' | 'done' | 'error' }>()
  for (const ev of events) {
    if (ev.event === 'loop.tool.call') {
      const tool = (ev as LoopEvent & { tool?: string }).tool ?? 'tool'
      const stepId = (ev as LoopEvent & { step_id?: string }).step_id ?? tool
      tools.set(stepId, { tool, status: 'running' })
    } else if (ev.event === 'loop.tool.result') {
      const tool = (ev as LoopEvent & { tool?: string }).tool ?? 'tool'
      const stepId = (ev as LoopEvent & { step_id?: string }).step_id ?? tool
      const error = (ev as LoopEvent & { error?: string | null }).error
      const existing = tools.get(stepId)
      if (existing) {
        existing.status = error ? 'error' : 'done'
      } else {
        tools.set(stepId, { tool, status: error ? 'error' : 'done' })
      }
    }
  }
  return Array.from(tools.values()).slice(-3)
}

export interface StreamingPhaseProps {
  events: LoopEvent[]
  streaming?: boolean
}

export function StreamingPhase({ events, streaming = true }: StreamingPhaseProps) {
  const phase = latestPhase(events)
  const tools = recentTools(events)
  const PhaseIcon = phase ? PHASE_ICONS[phase.key] ?? BrainCircuit : BrainCircuit

  return (
    <div className="flex flex-wrap items-center gap-2" aria-live="polite" aria-atomic="false">
      {phase ? (
        <Chip tone={streaming ? 'primary' : 'neutral'}>
          <PhaseIcon className="h-3 w-3" />
          {phase.label}
          {streaming && <Loader2 className="h-3 w-3 animate-spin" />}
        </Chip>
      ) : streaming ? (
        <Chip tone="neutral">
          <Loader2 className="h-3 w-3 animate-spin" />
          Thinking
        </Chip>
      ) : null}

      {tools.map((t) => (
        <Chip
          key={t.tool}
          tone={t.status === 'error' ? 'danger' : t.status === 'done' ? 'success' : 'neutral'}
        >
          <Wrench className="h-3 w-3" />
          {t.tool}
        </Chip>
      ))}
    </div>
  )
}
