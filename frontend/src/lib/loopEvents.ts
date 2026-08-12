// Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
// Licensed under Elastic License 2.0 - see LICENSE.md for details.
//
// Typed bindings for the Phase-7 language-agent loop event taxonomy.
// Mirrors ``src/crp_comply/api/events.py`` - keep these in lockstep
// when the Python registry grows. The reasoning tape switches on
// the ``event`` discriminant, so any event name not declared here
// falls through to a "raw" renderer instead of a UI dead-letter.

export type LoopEventName =
  | 'loop.opened'
  | 'loop.plan'
  | 'loop.step.start'
  | 'loop.thought.delta'
  | 'loop.tool.call'
  | 'loop.tool.result'
  | 'loop.reflection'
  | 'loop.clarifier.ask'
  | 'loop.clarifier.answer'
  | 'loop.step.end'
  | 'loop.recipe.start'
  | 'loop.recipe.delta'
  | 'loop.recipe.done'
  | 'loop.final'
  | 'loop.error'
  | 'loop.heartbeat'
  | 'loop.triage'
  | 'loop.cache.hit'
  | 'loop.cache.miss'
  | 'loop.web.start'
  | 'loop.web.result'
  | 'loop.ckf.query'
  | 'loop.abort'
  | 'loop.web.expand'
  | 'loop.web.rerank'
  | 'loop.web.cite'
  | 'loop.pii_warning'
  | 'loop.phase.complete'

export const ALL_LOOP_EVENTS: readonly LoopEventName[] = [
  'loop.opened',
  'loop.plan',
  'loop.step.start',
  'loop.thought.delta',
  'loop.tool.call',
  'loop.tool.result',
  'loop.reflection',
  'loop.clarifier.ask',
  'loop.clarifier.answer',
  'loop.step.end',
  'loop.recipe.start',
  'loop.recipe.delta',
  'loop.recipe.done',
  'loop.final',
  'loop.error',
  'loop.heartbeat',
  'loop.triage',
  'loop.cache.hit',
  'loop.cache.miss',
  'loop.web.start',
  'loop.web.result',
  'loop.ckf.query',
  'loop.abort',
  'loop.web.expand',
  'loop.web.rerank',
  'loop.web.cite',
  'loop.pii_warning',
  'loop.phase.complete',
]

export type TriageLane = 'cache' | 'fast' | 'slow'
export type TriageComplexity =
  | 'trivial'
  | 'simple'
  | 'moderate'
  | 'complex'
  | 'comprehensive'
export type CacheKeyKind = 'exact' | 'semantic' | 'plan'
export type WebBackend = 'local' | 'brave' | 'tavily' | 'searxng'
export type WebIntent =
  | 'regulation_text'
  | 'case_law'
  | 'guidance'
  | 'enforcement'
  | 'news'
  | 'vendor'
  | 'general'
export type CKFMode =
  | 'pattern_query'
  | 'graph_walk'
  | 'community_summary'
  | 'temporal_query'
  | 'recall_facts'
  | 'semantic'
export type CKFScope = 'corpus' | 'tenant' | 'federated'
export type TrustTier = 1 | 2 | 3 | 4

export interface LoopEventBase {
  event: LoopEventName
  ts: number
  run_id: string
}

export interface OpenedEvent extends LoopEventBase {
  event: 'loop.opened'
  session_id: string
  query: string
  model?: string
}

export interface PlanStep {
  id: string
  intent: string
  tool_hint?: string | null
}

export interface PlanEvent extends LoopEventBase {
  event: 'loop.plan'
  steps: PlanStep[]
  should_loop?: boolean
  depth?: 'brief' | 'standard' | 'thorough' | string
}

export interface StepStartEvent extends LoopEventBase {
  event: 'loop.step.start'
  step_id: string
  intent: string
  attempt?: number
}

export interface ThoughtDeltaEvent extends LoopEventBase {
  event: 'loop.thought.delta'
  step_id: string
  text: string
}

export interface ToolCallEvent extends LoopEventBase {
  event: 'loop.tool.call'
  step_id: string
  tool: string
  args: Record<string, unknown>
}

export interface ToolResultEvent extends LoopEventBase {
  event: 'loop.tool.result'
  step_id: string
  tool: string
  summary?: string
  citations?: Array<Record<string, unknown>>
  error?: string | null
}

export interface ReflectionEvent extends LoopEventBase {
  event: 'loop.reflection'
  step_id: string
  verdict: 'ok' | 'retry' | 'revise_plan' | 'clarify_first' | 'abort'
  notes?: string
}

export interface ClarifierAskEvent extends LoopEventBase {
  event: 'loop.clarifier.ask'
  step_id: string
  question: string
  slot_id: string
  options?: string[] | null
  resume_token?: string | null
}

export interface ClarifierAnswerEvent extends LoopEventBase {
  event: 'loop.clarifier.answer'
  slot_id: string
  answer: string
}

export interface StepEndEvent extends LoopEventBase {
  event: 'loop.step.end'
  step_id: string
  status: 'ok' | 'skipped' | 'failed'
}

export interface RecipeStartEvent extends LoopEventBase {
  event: 'loop.recipe.start'
  recipe_id: string
  inputs?: Record<string, unknown>
}

export interface RecipeDeltaEvent extends LoopEventBase {
  event: 'loop.recipe.delta'
  recipe_id: string
  kind: string
  text?: string
}

export interface RecipeDoneEvent extends LoopEventBase {
  event: 'loop.recipe.done'
  recipe_id: string
  artefact_id: string
}

export interface FinalEvent extends LoopEventBase {
  event: 'loop.final'
  artefacts?: Array<Record<string, unknown>>
  summary?: string
  total_steps?: number
}

export interface ErrorEvent extends LoopEventBase {
  event: 'loop.error'
  message: string
  step_id?: string | null
}

export interface HeartbeatEvent extends LoopEventBase {
  event: 'loop.heartbeat'
  state?: string
}

export interface TriageEvent extends LoopEventBase {
  event: 'loop.triage'
  complexity: TriageComplexity
  intent: string
  confidence: number
  lane: TriageLane
  reasoning?: string
  slots?: Record<string, string | number | boolean | null>
}

export interface CacheHitEvent extends LoopEventBase {
  event: 'loop.cache.hit'
  key_kind: CacheKeyKind
  similarity?: number | null
  age_seconds?: number
  citations?: Array<Record<string, unknown>>
}

export interface CacheMissEvent extends LoopEventBase {
  event: 'loop.cache.miss'
  key_kind: CacheKeyKind
  lookup_ms?: number
}

export interface WebStartEvent extends LoopEventBase {
  event: 'loop.web.start'
  query: string
  backend: WebBackend
  profile?: string | null
  freshness?: 'any' | 'day' | 'week' | 'month'
}

export interface WebResultHit {
  domain: string
  trust_tier: TrustTier
  url?: string
  title?: string
  blocked?: boolean
}

export interface WebResultEvent extends LoopEventBase {
  event: 'loop.web.result'
  backend: WebBackend
  hits: WebResultHit[]
  blocked?: number
  latency_ms?: number
  quota_remaining?: number | null
}

export interface CKFQueryEvent extends LoopEventBase {
  event: 'loop.ckf.query'
  mode: CKFMode
  scope: CKFScope
  hits?: number
  top_confidence?: number
}

export type AbortDimension =
  | 'steps'
  | 'tokens'
  | 'wall_clock'
  | 'clarifiers'
  | 'plan_revisions'

export interface AbortEvent extends LoopEventBase {
  event: 'loop.abort'
  reason: 'budget_exceeded'
  dimension: AbortDimension
  limit: number
  usage: number
  detail?: string | null
  budget?: Record<string, number>
  totals?: Record<string, number>
}

export interface WebExpandEvent extends LoopEventBase {
  event: 'loop.web.expand'
  goal: string
  intent: WebIntent
  sub_queries: string[]
  strategy: string
}

export interface WebRerankEvent extends LoopEventBase {
  event: 'loop.web.rerank'
  model: string
  candidates_in: number
  candidates_out: number
  latency_ms: number
}

export interface WebCiteEvent extends LoopEventBase {
  event: 'loop.web.cite'
  citation_id: string
  source_id: string
  chunk_index: number
  score: number
  excerpt?: string
}

export interface PiiWarningEvent extends LoopEventBase {
  event: 'loop.pii_warning'
  step_id?: string
  categories?: string[]
  source?: string
  iter?: number | null
}

export type LoopEvent =
  | OpenedEvent
  | PlanEvent
  | StepStartEvent
  | ThoughtDeltaEvent
  | ToolCallEvent
  | ToolResultEvent
  | ReflectionEvent
  | ClarifierAskEvent
  | ClarifierAnswerEvent
  | StepEndEvent
  | RecipeStartEvent
  | RecipeDeltaEvent
  | RecipeDoneEvent
  | FinalEvent
  | ErrorEvent
  | HeartbeatEvent
  | TriageEvent
  | CacheHitEvent
  | CacheMissEvent
  | WebStartEvent
  | WebResultEvent
  | CKFQueryEvent
  | AbortEvent
  | WebExpandEvent
  | WebRerankEvent
  | WebCiteEvent
  | PiiWarningEvent
  | PhaseCompleteEvent

export interface PhaseCompleteEvent extends LoopEventBase {
  event: 'loop.phase.complete'
  phase: string
  step_ids?: string[]
  facts_gathered?: number
  citations_count?: number
  notes?: string
}

export function isLoopEvent(name: string): name is LoopEventName {
  return (ALL_LOOP_EVENTS as readonly string[]).includes(name)
}
