/**
 * Agent Chat - conversational surface for the LLM compliance agent.
 *
 * Wraps the ``/api/v1/agent/*`` endpoints into a chat transcript:
 *   - First user message calls ``POST /agent/start``.
 *   - Subsequent answers to pending clarifications call
 *     ``POST /agent/{id}/clarify``.
 *   - ``final_text`` renders as a full markdown deliverable with a
 *     "Finalize to vault" action that calls ``POST /agent/{id}/finalize``
 *     so the output persists as a retrievable ``ComplianceReport``.
 *
 * The transcript is derived server-side from ``clarifications`` +
 * ``pending_question`` + ``final_text``; we do not maintain a
 * client-only chat log, so a browser reload resumes the exact server
 * state. Missing ``agent_intelligence`` entitlement or LLM provider
 * surfaces as an inline warning rather than a dead button.
 */
import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '@clerk/react'
import {
  Bot,
  AlertTriangle,
  Zap,
  X,
} from 'lucide-react'
import {
  agentGet,
  agentClarify,
  agentFinalize,
  agentListSessions,
  agentDelete,
  agentStartStream,
  agentLoopStream,
  agentLoopContinueStream,
  agentClarifyStream,
  getProviderStatus,
  listRecipes,
  getPreferences,
  listCheckpoints,
  resolveCheckpoint,
  updatePreferences,
  ApiError,
  type AgentSessionState,
  type AgentSseEvent,
  type RecipeSummary,
  type Checkpoint,
  type UserPreferenceProfile,
  type AutonomyLevel,
} from '../../lib/api'
import { useProfile, type OrgProfile } from '../../lib/profile'
import { ScalesMark as ScalesMarkPrimitive, Chip, Button } from '../../design/primitives'
import { ContentSkeleton } from '../../components/skeletons'
import ReasoningTape from '../../components/ReasoningTape'
import ReasoningTimeline from '../../components/ReasoningTimeline'
import { useToast } from '../../components/toast/ToastProvider'
import { ConfirmDialog } from '../../design/ConfirmDialog'
import type { LoopEvent } from '../../lib/loopEvents'
import {
  AgentSessionSidebar,
  AgentHeader,
  TranscriptBubble,
  TypingIndicator,
  StreamingPhase,
  SuggestedPrompts,
  Composer,
  LearnedPreferenceIndicator,
  type TranscriptLine,
  type SearchDepth,
} from '../../components/agent'

export default function AgentChat() {
  const { sessionId: paramSessionId } = useParams<{ sessionId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const routeId = paramSessionId || searchParams.get('session') || undefined
  const navigate = useNavigate()
  const { profile } = useProfile()
  const { isLoaded: authLoaded, isSignedIn } = useAuth()

  const [sessions, setSessions] = useState<AgentSessionState[] | null>(null)
  const [session, setSession] = useState<AgentSessionState | null>(null)
  const [loading, setLoading] = useState(false)
  const [draft, setDraft] = useState('')
  const seededRecipeIdRef = useRef<string | null>(null)
  const [error, setError] = useState<string>('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [provider, setProvider] = useState<{ configured: boolean; provider?: string | null } | null>(null)
  const [streamEvents, setStreamEvents] = useState<AgentSseEvent[]>([])
  const [loopEvents, setLoopEvents] = useState<LoopEvent[]>([])
  const [streamingText, setStreamingText] = useState('')
  const [hasReceivedFirstChunk, setHasReceivedFirstChunk] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [streamingModel, setStreamingModel] = useState<string | null>(null)
  const [optimisticText, setOptimisticText] = useState<string | null>(null)
  const [lastFailedMessage, setLastFailedMessage] = useState<string | null>(null)
  const [liveStatus, setLiveStatus] = useState('')
  const [searchDepth, setSearchDepth] = useState<SearchDepth>('standard')
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([])
  const [preferences, setPreferences] = useState<UserPreferenceProfile | null>(null)
  const [autonomy, setAutonomy] = useState<AutonomyLevel>('autonomous_with_checkpoints')
  const [resolvingCheckpoint, setResolvingCheckpoint] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const toast = useToast()

  // ── Session list (sidebar) ────────────────────────────────
  const refreshList = () => agentListSessions().then((r) => setSessions(r.sessions)).catch(() => setSessions([]))
  useEffect(() => {
    if (!authLoaded || !isSignedIn) return
    refreshList()
  }, [authLoaded, isSignedIn])

  // ── LLM provider status ───────────────────────────────────
  useEffect(() => {
    if (!authLoaded || !isSignedIn) return
    getProviderStatus().then(setProvider).catch(() => setProvider({ configured: false }))
  }, [authLoaded, isSignedIn])

  // Load default research depth and learned preference profile.
  useEffect(() => {
    if (!authLoaded || !isSignedIn) return
    getPreferences()
      .then((p) => {
        setPreferences(p)
        const d = p.preferred_depth
        if (d === 'brief' || d === 'standard' || d === 'thorough') {
          setSearchDepth(d)
        }
        if (p.preferred_autonomy) {
          setAutonomy(p.preferred_autonomy)
        }
      })
      .catch(() => { /* unauthenticated or not yet created - keep default */ })
  }, [authLoaded, isSignedIn])

  // Poll pending checkpoints for the active session so users can approve
  // them inline instead of switching to the Safety Control Plane dashboard.
  useEffect(() => {
    if (!routeId || !authLoaded || !isSignedIn) return
    let cancelled = false
    const poll = async () => {
      try {
        const data = await listCheckpoints()
        if (cancelled) return
        setCheckpoints(data.checkpoints.filter((cp) => cp.session_id === routeId))
      } catch {
        // non-fatal: checkpoints may not be available in all environments
      }
    }
    void poll()
    const id = setInterval(poll, 3000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [routeId, authLoaded, isSignedIn])

  // ── Recipe-seeded interview ───────────────────────────────
  // Only seed once per recipeId to avoid re-running if the user edits
  // the draft before sending. Depends only on stable URL/identity values.
  const recipeId = searchParams.get('recipe')
  useEffect(() => {
    if (!recipeId || routeId || seededRecipeIdRef.current === recipeId) return
    let cancelled = false
    listRecipes()
      .then((rs: RecipeSummary[]) => {
        if (cancelled) return
        const r = rs.find((x) => x.recipe_id === recipeId)
        const title = r?.title || recipeId
        const regulation = r?.regulation || ''
        const seed =
          `I want to produce the "${title}"${regulation ? ` (${regulation})` : ''} deliverable. ` +
          `Walk me through it as a Socratic, regulation-cited interview - ask one question at a time, ` +
          `cite the specific article or clause each question comes from, and flag any artefact ` +
          `(model card, dataset card, architecture diagram, pen-test report, DPA) or runtime signal I need to gather.`
        seededRecipeIdRef.current = recipeId
        setDraft(seed)
        const next = new URLSearchParams(searchParams)
        next.delete('recipe')
        setSearchParams(next, { replace: true })
      })
      .catch(() => { /* best-effort */ })
    return () => { cancelled = true }
  }, [recipeId, routeId, searchParams, setSearchParams])

  // ── Load selected session ─────────────────────────────────
  useEffect(() => {
    if (!routeId) { setSession(null); return }
    setLoading(true)
    agentGet(routeId).then(setSession).catch((e: Error) => setError(e.message)).finally(() => setLoading(false))
  }, [routeId])

  // ── Derived transcript ────────────────────────────────────
  const transcript: TranscriptLine[] = useMemo(() => {
    if (!session) return []
    const out: TranscriptLine[] = []
    // Phase-7 loop sessions persist the full turn log in ``messages``.
    // Prefer that over the legacy flattened fields so multi-turn follow-ups
    // render correctly.
    if (session.messages && session.messages.length > 0) {
      for (const m of session.messages) {
        const role = String(m.role || '')
        const content = String(m.content || '')
        if (!content) continue
        if (role === 'user') {
          out.push({ role: 'user', kind: 'task', text: content, timestamp: String(m.ts || '') })
        } else if (role === 'assistant') {
          out.push({ role: 'agent', kind: 'final', text: content, timestamp: String(m.ts || ''), confidence: m.confidence })
        }
      }
    } else {
      out.push({ role: 'user', kind: 'task', text: session.task, timestamp: session.created_at })
    }
    for (const c of session.clarifications) {
      if (c.question) out.push({ role: 'agent', kind: 'clarification-q', text: c.question })
      if (c.answer) out.push({ role: 'user', kind: 'clarification-a', text: c.answer })
    }
    if (session.state === 'awaiting_clarification' && session.pending_question) {
      const action = (session.pending_action as 'probe' | 'confirm' | 'repair') || 'probe'
      const kind = action === 'confirm' ? 'confirmation-q' : action === 'repair' ? 'repair-q' : 'clarification-q'
      out.push({
        role: 'agent',
        kind,
        text: session.pending_question,
        priority: (session.pending_priority || 'medium') as 'high' | 'medium' | 'low',
        skippable: session.pending_skippable,
        action,
        options: session.pending_options,
      })
    }
    const lastAssistant = out.length > 0 && out[out.length - 1].role === 'agent' ? out[out.length - 1].text : ''
    if (session.state === 'done' && session.final_text && session.final_text !== lastAssistant) {
      out.push({ role: 'agent', kind: 'final', text: session.final_text, timestamp: session.updated_at, confidence: session.final_confidence })
    }
    if (session.state === 'error' && session.error) {
      out.push({ role: 'agent', kind: 'error', text: session.error })
    }
    return out
  }, [session])

  // ── Live transcript (server state + checkpoints + optimistic user message + streaming bubble)
  const liveTranscript: TranscriptLine[] = useMemo(() => {
    const lines = [...transcript]
    for (const cp of checkpoints) {
      lines.push({
        role: 'agent',
        kind: 'checkpoint',
        text: cp.reason,
        checkpoint: cp,
      })
    }
    if (optimisticText && (streaming || loading)) {
      lines.push({ role: 'user', kind: 'optimistic', text: optimisticText })
    }
    if ((streaming || streamingText.length > 0) && streamingText !== undefined) {
      lines.push({ role: 'agent', kind: 'streaming', text: streamingText, streaming: true })
    }
    return lines
  }, [transcript, checkpoints, optimisticText, streaming, loading, streamingText])

  async function handleResolveCheckpoint(id: string, action: 'approve' | 'reject', note?: string) {
    setResolvingCheckpoint(true)
    try {
      await resolveCheckpoint(id, action, note)
      setCheckpoints((prev) => prev.filter((cp) => cp.checkpoint_id !== id))
      if (routeId) {
        const refreshed = await agentGet(routeId)
        setSession(refreshed)
      }
      toast.success(action === 'approve' ? 'Checkpoint approved' : 'Checkpoint rejected', 'The agent will continue.')
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err)
      toast.error('Checkpoint resolution failed', msg)
    } finally {
      setResolvingCheckpoint(false)
    }
  }

  // ── Auto-scroll to bottom on new turns ────────────────────
  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: 'smooth' })
  }, [transcript.length, session?.state])

  // ── Scroll while streaming, but only if user is already near the bottom ─
  useEffect(() => {
    const el = transcriptRef.current
    if (!el) return
    const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 100
    if (nearBottom) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    }
  }, [loopEvents, streamingText])

  // ── Focus composer when awaiting clarification ────────────
  useEffect(() => {
    if (session?.state === 'awaiting_clarification' && composerRef.current) {
      setTimeout(() => composerRef.current?.focus(), 200)
    }
  }, [session?.state])

  // ── Send handler ──────────────────────────────────────────
  async function consumeStream(stream: AsyncGenerator<AgentSseEvent, void, void>) {
    setStreamEvents([])
    setLoopEvents([])
    setStreaming(true)
    setLiveStatus('Agent is drafting…')
    let finalState: AgentSessionState | null = null
    let observedSessionId: string | null = null
    let loopFinalText = ''
    let loopFinalCitations: Array<Record<string, unknown>> = []
    try {
      for await (const ev of stream) {
        setStreamEvents((prev) => [...prev, ev])
        if (typeof ev.event === 'string' && ev.event.startsWith('loop.')) {
          const data = (ev.data && typeof ev.data === 'object' ? ev.data : {}) as Record<string, unknown>
          const evtName = String(data.event ?? ev.event)
          const tapeEv = { ...data, event: evtName } as unknown as LoopEvent
          setLoopEvents((prev) => [...prev, tapeEv])
          if (evtName === 'loop.opened' && data.model) {
            setStreamingModel(String(data.model))
          } else if (evtName === 'loop.thought.delta' && typeof data.text === 'string') {
            setStreamingText((prev) => prev + data.text)
            setHasReceivedFirstChunk(true)
          } else if (evtName === 'loop.final') {
            loopFinalText = String(data.summary ?? '')
            if (data.summary) setStreamingText(String(data.summary))
            const cits = data.citations
            if (Array.isArray(cits)) loopFinalCitations = cits as Array<Record<string, unknown>>
          }
        }
        if (ev.event === 'done' && ev.data && typeof ev.data === 'object') {
          finalState = ev.data as AgentSessionState
        } else if (ev.data && typeof ev.data === 'object') {
          const maybeId = (ev.data as { session_id?: unknown }).session_id
          if (typeof maybeId === 'string' && maybeId) observedSessionId = maybeId
        }
      }
    } finally {
      setStreaming(false)
      setStreamingText('')
      setHasReceivedFirstChunk(false)
      setStreamingModel(null)
      setOptimisticText(null)
      setLiveStatus('Draft complete')
    }
    return { finalState, observedSessionId, loopFinalText, loopFinalCitations }
  }

  async function submitMessage(text: string) {
    if (!text || loading) return
    setOptimisticText(text)
    setLastFailedMessage(null)
    setError('')
    setLoading(true)
    abortControllerRef.current?.abort()
    const controller = new AbortController()
    abortControllerRef.current = controller
    let reconcileId: string | null = session?.session_id ?? null
    const toastId = toast.loading('Agent is thinking…', session ? 'Processing your message.' : 'Starting a new compliance session.')
    try {
      if (!session) {
        console.log('[AgentChat] Starting new session:', text.substring(0, 100))
        const useLegacy = searchParams.get('legacy') === '1'
        const profileSummary = summariseProfile(profile)
        const stream = useLegacy
          ? agentStartStream({ task: text, extra_context: profileSummary, max_iters: 8, depth: searchDepth, autonomy }, controller.signal)
          : agentLoopStream({ task: text, extra_context: profileSummary, max_iters: 8, depth: searchDepth, autonomy }, controller.signal)
        setDraft('')
        const { finalState, observedSessionId } = await consumeStream(stream)
        toast.dismiss(toastId)
        if (observedSessionId) reconcileId = observedSessionId
        if (finalState) {
          setSession(finalState)
          console.log('[AgentChat] Session complete:', finalState.state, finalState.session_id)
          if (finalState.state === 'done') {
            toast.success('Deliverable ready', 'The agent has completed its analysis. Review below.')
          } else if (finalState.state === 'awaiting_clarification') {
            toast.info('Clarification needed', 'The agent needs more information to proceed.')
          } else if (finalState.state === 'error') {
            toast.error('Session error', finalState.error || 'Something went wrong.')
          }
        }
        else if (reconcileId) setSession(await agentGet(reconcileId))
        refreshList()
        const sid = finalState?.session_id ?? reconcileId
        if (sid) navigate(`/app/draft?mode=chat&session=${sid}`, { replace: true })
      } else if (session.state === 'awaiting_clarification') {
        console.log('[AgentChat] Answering clarification for session:', session.session_id)
        const stream = agentClarifyStream(session.session_id, { answer: text, autonomy }, controller.signal)
        setDraft('')
        const { finalState } = await consumeStream(stream)
        toast.dismiss(toastId)
        if (finalState) {
          setSession(finalState)
          if (finalState.state === 'done') toast.success('Deliverable ready', 'Analysis complete after clarification.')
          else if (finalState.state === 'awaiting_clarification') toast.info('Another question', 'The agent needs more information.')
        }
        else setSession(await agentGet(session.session_id))
      } else {
        console.log('[AgentChat] Continuing loop session:', session.session_id)
        const stream = agentLoopContinueStream(session.session_id, { message: text, depth: searchDepth }, controller.signal)
        setDraft('')
        const { finalState } = await consumeStream(stream)
        toast.dismiss(toastId)
        if (finalState) {
          setSession(finalState)
          if (finalState.state === 'done') toast.success('Deliverable ready', 'Follow-up analysis complete.')
          else if (finalState.state === 'awaiting_clarification') toast.info('Clarification needed', 'The agent has a follow-up question.')
        }
        else setSession(await agentGet(session.session_id))
        refreshList()
      }
    } catch (err) {
      toast.dismiss(toastId)
      if (err instanceof DOMException && err.name === 'AbortError') {
        // User cancelled - no error surface needed.
      } else {
        const msg = err instanceof ApiError ? err.message : String(err)
        console.error('[AgentChat] Submit error:', msg)
        setError(msg)
        setLastFailedMessage(text)
        toast.error('Request failed', msg)
        if (reconcileId) {
          try { setSession(await agentGet(reconcileId)) } catch { /* swallow */ }
        }
      }
    } finally {
      setLoading(false)
      abortControllerRef.current = null
    }
  }

  async function onSubmit(e: FormEvent, overrideText?: string) {
    e.preventDefault()
    const text = (overrideText ?? draft).trim()
    await submitMessage(text)
  }

  function onCancel() {
    abortControllerRef.current?.abort()
    setLoading(false)
    setStreaming(false)
    setStreamingText('')
    setStreamingModel(null)
    setOptimisticText(null)
    setLiveStatus('')
  }

  function onRetry() {
    if (!lastFailedMessage) return
    setError('')
    submitMessage(lastFailedMessage)
  }

  function handleClarifierOption(option: string) {
    if (!session || session.state !== 'awaiting_clarification' || loading) return
    console.log('[AgentChat] Clarifier option selected:', option)
    submitMessage(option)
  }

  async function onSkip() {
    if (!session || session.state !== 'awaiting_clarification' || loading) return
    setLoading(true)
    setError('')
    console.log('[AgentChat] Skipping clarification for session:', session.session_id)
    toast.info('Skipping question…', 'The agent will continue with an explicit assumption.')
    try {
      const next = await agentClarify(session.session_id, { skip: true })
      setSession(next)
      console.log('[AgentChat] Clarification skipped. State:', next.state)
      if (next.state === 'done') toast.success('Deliverable ready', 'Analysis complete with assumptions noted.')
      else if (next.state === 'awaiting_clarification') toast.info('Next question', 'The agent has another question.')
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err)
      console.error('[AgentChat] Skip error:', msg)
      setError(msg)
      toast.error('Skip failed', msg)
    } finally {
      setLoading(false)
    }
  }

  async function onFinalize() {
    if (!session || session.state !== 'done' || loading) return
    setLoading(true)
    setError('')
    console.log('[AgentChat] Finalizing session to vault:', session.session_id)
    const toastId = toast.loading('Saving to vault…', 'Persisting deliverable as a ComplianceReport.')
    try {
      const result = await agentFinalize(session.session_id)
      toast.dismiss(toastId)
      if (result.report_id) {
        console.log('[AgentChat] Finalized. Report ID:', result.report_id)
        toast.success('Saved to vault', `ComplianceReport #${result.report_id.slice(0, 8)} created.`)
        navigate(`/app/vault/${result.report_id}`)
      } else {
        toast.warning('Finalize incomplete', 'No report ID returned. Check the vault.')
      }
    } catch (err) {
      toast.dismiss(toastId)
      const msg = err instanceof ApiError ? err.message : String(err)
      console.error('[AgentChat] Finalize error:', msg)
      setError(msg)
      toast.error('Finalize failed', msg)
    } finally {
      setLoading(false)
    }
  }

  function onDelete(sessionId: string) {
    setConfirmDelete(sessionId)
  }

  async function confirmDeleteSession(sessionId: string) {
    try {
      await agentDelete(sessionId)
      console.log('[AgentChat] Deleted session:', sessionId)
      toast.success('Conversation deleted', 'The session has been permanently removed.')
      if (routeId === sessionId) { setSession(null); navigate('/app/chat', { replace: true }) }
      refreshList()
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err)
      console.error('[AgentChat] Delete error:', msg)
      setError(msg)
      toast.error('Delete failed', msg)
    } finally {
      setConfirmDelete(null)
    }
  }

  function onNew() {
    navigate('/app/chat')
  }

  const canSend = !!draft.trim() && !loading && session?.state !== 'running'
  const awaiting = session?.state === 'awaiting_clarification'
  const pendingPriority = (session?.pending_priority || 'medium') as 'high' | 'medium' | 'low'
  const pendingAction = (session?.pending_action as 'probe' | 'confirm' | 'repair' | undefined) || 'probe'

  return (
    <div className="h-full grid grid-cols-1 lg:grid-cols-[300px_1fr] min-h-0">
      <AgentSessionSidebar
        sessions={sessions}
        routeId={routeId}
        formatTime={formatRelativeTime}
        onDelete={onDelete}
        onNew={onNew}
      />

      {/* ══════════ Transcript ══════════ */}
      <section className="flex flex-col min-h-0">
        <AgentHeader
          session={session}
          loading={loading}
          onRefresh={() => routeId && agentGet(routeId).then(setSession).catch(() => {})}
          provider={provider}
          streamingModel={streamingModel}
          streaming={streaming}
        />

        <div className="px-4 lg:px-6 py-2 border-b border-hairline bg-surface flex flex-wrap items-center justify-between gap-2">
          <AgentChatProfileSummary />
          {preferences && (
            <LearnedPreferenceIndicator
              preferences={preferences}
              onUpdate={(update) => {
                updatePreferences(update)
                  .then((p) => {
                    setPreferences(p)
                    if (p.preferred_depth === 'brief' || p.preferred_depth === 'standard' || p.preferred_depth === 'thorough') {
                      setSearchDepth(p.preferred_depth)
                    }
                    if (p.preferred_autonomy) {
                      setAutonomy(p.preferred_autonomy)
                    }
                    toast.success('Preferences updated', 'Your defaults have been saved.')
                  })
                  .catch((err) => {
                    const msg = err instanceof ApiError ? err.message : String(err)
                    toast.error('Update failed', msg)
                  })
              }}
            />
          )}
        </div>

        {/* Screen-reader live region */}
        <div aria-live="polite" aria-atomic="true" className="sr-only">
          {liveStatus}
        </div>

        {/* LLM provider gate */}
        {provider && !provider.configured && (
          <div className="px-4 lg:px-6 py-3 bg-warning-muted border-b border-warning flex items-start gap-3 animate-slide-up">
            <div className="h-7 w-7 rounded-full bg-warning/20 grid place-items-center shrink-0">
              <AlertTriangle className="h-4 w-4 text-warning" />
            </div>
            <div className="text-xs text-ink-2 leading-relaxed">
              <span className="font-bold">No LLM provider configured.</span> Set up a provider in{' '}
              <Link to="/app/settings" className="underline font-semibold hover:text-ink transition-colors">Settings</Link>{' '}
              so the agent can reason. Until then, agent requests will fail with 502.
            </div>
          </div>
        )}

        {/* Transcript */}
        <div ref={transcriptRef} className="flex-1 overflow-y-auto px-4 lg:px-6 py-6 space-y-5">
          {!session && !routeId ? (
            <div className="flex flex-col items-center justify-center h-full py-12">
              <div className="mx-auto w-16 h-16 rounded-2xl bg-brand-50 border border-brand-200 grid place-items-center mb-5 shadow-sm">
                <Bot className="h-8 w-8 text-brand-800" />
              </div>
              <h2 className="text-xl font-bold text-ink mb-2 font-display">Ask the compliance assistant</h2>
              <p className="text-sm text-ink-3 max-w-lg text-center mb-8 leading-relaxed">
                The agent can pull regulations from the corpus, run risk assessments, draft DPIAs, and recall facts from your customer knowledge file. It'll ask you clarifying questions as it goes.
              </p>
              <SuggestedPrompts onSelect={setDraft} />
            </div>
          ) : loading && !session ? (
            <div className="p-2"><ContentSkeleton lines={3} /></div>
          ) : (
            liveTranscript.map((line, i) => (
              <TranscriptBubble
                key={i}
                line={line}
                formatTime={formatRelativeTime}
                sessionId={session?.session_id || routeId || undefined}
                onSkip={line.kind === 'clarification-q' || line.kind === 'confirmation-q' || line.kind === 'repair-q' ? onSkip : undefined}
                onOption={line.options ? handleClarifierOption : undefined}
                onResolveCheckpoint={handleResolveCheckpoint}
                resolvingCheckpoint={resolvingCheckpoint}
              />
            ))
          )}

          {(loading || session?.state === 'running') && (
            <div className="flex items-start gap-3 px-2 animate-fade-in">
              <div className="h-8 w-8 rounded-lg bg-ink grid place-items-center shrink-0">
                <ScalesMarkPrimitive size={16} className="text-brand-400 animate-tilt-scales" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="rounded-2xl rounded-tl-md border border-hairline bg-surface px-4 py-3 shadow-sm">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-bold text-ink">Compliance Assistant</span>
                    <span className="text-xs text-ink-4">
                      {hasReceivedFirstChunk ? 'Drafting response…' : 'Processing…'}
                    </span>
                  </div>
                  {!hasReceivedFirstChunk ? (
                    <TypingIndicator />
                  ) : (
                    <p className="text-sm text-ink-2 italic">{streamingText.slice(0, 160)}{streamingText.length > 160 ? '…' : ''}</p>
                  )}
                </div>
                <div className="mt-2">
                  <StreamingPhase events={loopEvents} streaming={!hasReceivedFirstChunk || streaming} />
                </div>
                {loopEvents.length > 0 ? (
                  <div className="mt-3 max-h-[40vh] overflow-y-auto rounded-xl border border-hairline bg-surface px-3 py-2 shadow-sm">
                    <ReasoningTimeline events={loopEvents} />
                  </div>
                ) : streamEvents.length > 0 ? (
                  <div className="mt-2 space-y-0.5 font-mono text-[11px] text-ink-3 max-h-32 overflow-y-auto rounded-xl border border-hairline bg-surface-2/50 px-3 py-2">
                    {streamEvents
                      .map((ev) => ({ ev, text: formatStreamEvent(ev) }))
                      .filter(({ text }) => text.length > 0)
                      .slice(-12)
                      .map(({ text }, i) => (
                        <div key={i} className="line-clamp-1">{text}</div>
                      ))}
                  </div>
                ) : null}
              </div>
            </div>
          )}

          {/* Experts consulted + post-run reasoning timeline */}
          {!loading && session?.state !== 'running' && (loopEvents.length > 0 || (session?.reasoning_tape && session.reasoning_tape.length > 0) || (session?.experts_invoked && session.experts_invoked.length > 0)) && (
            <details className="rounded-xl border border-hairline bg-surface px-4 py-3 shadow-sm animate-slide-up">
              <summary className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-ink-3 font-bold cursor-pointer list-none">
                <Zap className="h-3 w-3" /> Show reasoning <span className="text-ink-4 font-normal normal-case">({loopEvents.length || session?.reasoning_tape?.length || 0} event{(loopEvents.length || session?.reasoning_tape?.length || 0) === 1 ? '' : 's'})</span>
              </summary>
              {session?.experts_invoked && session.experts_invoked.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {session.experts_invoked.map((expert) => (
                    <Chip key={expert} tone="primary">{expert}</Chip>
                  ))}
                </div>
              )}
              <div className="mt-3 max-h-[40vh] overflow-y-auto">
                <ReasoningTimeline events={loopEvents.length > 0 ? loopEvents : (session?.reasoning_tape as unknown as LoopEvent[])} />
              </div>
              <details className="mt-3 text-xs text-ink-3">
                <summary className="cursor-pointer hover:text-ink-2 font-medium">Full audit trail</summary>
                <div className="mt-2 max-h-[50vh] overflow-y-auto">
                  <ReasoningTape events={loopEvents.length > 0 ? loopEvents : (session?.reasoning_tape as unknown as LoopEvent[])} />
                </div>
              </details>
            </details>
          )}

          {error && (
            <div className="flex items-start gap-3 p-4 bg-danger-muted border border-danger/20 rounded-2xl text-xs text-danger animate-slide-up">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <div className="flex-1">
                <div className="mb-2">{error}</div>
                {lastFailedMessage && (
                  <Button type="button" variant="outline" size="sm" onClick={onRetry}>
                    Retry
                  </Button>
                )}
              </div>
              <button type="button" aria-label="Dismiss error" onClick={() => setError('')} className="shrink-0 text-ink-3 hover:text-ink transition-colors">
                <X size={14} />
              </button>
            </div>
          )}
        </div>

        <Composer
          draft={draft}
          onDraftChange={setDraft}
          onSubmit={onSubmit}
          onCancel={onCancel}
          onSkip={onSkip}
          onFinalize={onFinalize}
          loading={loading}
          session={session}
          awaiting={awaiting}
          pendingPriority={pendingPriority}
          pendingAction={pendingAction}
          canSend={canSend}
          textareaRef={composerRef}
          depth={searchDepth}
          onDepthChange={setSearchDepth}
        />
      </section>

      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete conversation"
        description="Delete this conversation? Any generated deliverables already saved to your vault will remain."
        variant="danger"
        confirmLabel="Delete"
        onConfirm={() => {
          if (confirmDelete) confirmDeleteSession(confirmDelete)
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  )
}

// ── Profile summary chips ─────────────────────────────────────

const ACTOR_LABELS: Record<string, string> = {
  provider: 'Provider',
  deployer: 'Deployer',
  importer: 'Importer',
  distributor: 'Distributor',
  authorised_representative: 'Authorised representative',
  gpai_provider: 'GPAI provider',
}

export function ProfileSummaryChips({ profile }: { profile: OrgProfile }) {
  const hasProfile = !!profile.actor || !!profile.org_name || (profile.jurisdictions && profile.jurisdictions.length > 0)
  if (!hasProfile) return null

  return (
    <div className="px-4 lg:px-6 py-2 border-b border-hairline bg-surface flex flex-wrap gap-2 items-center animate-fade-in">
      {profile.actor && <Chip tone="primary">{ACTOR_LABELS[profile.actor] ?? profile.actor}</Chip>}
      {profile.jurisdictions && profile.jurisdictions.length > 0 && (
        <Chip>{profile.jurisdictions.join(', ')}</Chip>
      )}
      {profile.is_high_risk && <Chip tone="danger">High risk</Chip>}
      {profile.is_gpai && <Chip tone="warning">GPAI</Chip>}
      {profile.iso_42001_certified && <Chip tone="success">ISO 42001</Chip>}
    </div>
  )
}

export function AgentChatProfileSummary() {
  const { profile } = useProfile()
  return <ProfileSummaryChips profile={profile} />
}

// ── Helpers ────────────────────────────────────────────────────

function summariseProfile(p: Record<string, unknown>): string {
  const bits: string[] = []
  if (p.org_name) bits.push(`Organisation: ${p.org_name}`)
  if (p.actor) bits.push(`Actor: ${p.actor}`)
  if (p.jurisdictions) bits.push(`Jurisdictions: ${(p.jurisdictions as string[]).join(', ')}`)
  if (p.is_high_risk) bits.push('System is high-risk')
  if (p.is_gpai) bits.push('Organisation is a GPAI provider')
  if (p.iso_42001_certified) bits.push('ISO 42001 certified')
  return bits.length > 0 ? `User profile:\n${bits.join('\n')}` : ''
}

function formatRelativeTime(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return d.toLocaleDateString()
}

function formatStreamEvent(ev: AgentSseEvent): string {
  const data = (ev.data && typeof ev.data === 'object' ? ev.data : {}) as Record<string, unknown>
  switch (ev.event) {
    case 'opened': return '↻ session opened'
    case 'crp_context_primed': return `⊕ primed ${data.chunks ?? ''} regulation chunks`
    case 'tool_call_start':
    case 'tool_call': return `→ ${String(data.tool ?? data.name ?? 'tool')} (${(data.arg_keys as string[] | undefined)?.join(', ') || ''})`
    case 'tool_result': return `← ${String(data.tool ?? 'tool')} ${data.ok === false ? '✗' : '✓'}`
    case 'crp_dedup': return `⊖ deduped ${data.chunks_deduped ?? ''} chunks`
    case 'crp_compact': return `▣ context compacted (${data.before ?? '?'}→${data.after ?? '?'})`
    case 'llm_turn':
    case 'llm_response': return `· LLM turn ${data.iter ?? ''}`
    case 'llm_phase': {
      const phase = String(data.phase ?? '')
      if (phase === 'prompt_send') return `… sending prompt to model (iter ${data.iter ?? '?'}, ${data.messages ?? '?'} msgs)`
      if (phase === 'received') {
        const ms = Number(data.elapsed_ms ?? 0)
        const secs = ms > 0 ? `${(ms / 1000).toFixed(1)}s` : ''
        const tcs = Number(data.tool_calls ?? 0)
        const reason = String(data.finish_reason ?? '')
        return `↩ model replied in ${secs}${tcs ? ` (${tcs} tool call${tcs === 1 ? '' : 's'})` : ` (${reason || 'text'})`}`
      }
      return `· phase ${phase}`
    }
    case 'llm_progress': {
      const ms = Number(data.elapsed_ms ?? 0)
      return `… thinking (${(ms / 1000).toFixed(0)}s elapsed)`
    }
    case 'llm_token': return ''
    case 'crp_overflow_refold': return `↻ CRP refold (budget→${data.new_budget ?? '?'})`
    case 'llm_error': return `! LLM error: ${String(data.error ?? '')}`
    case 'clarification_needed': return `? clarification: ${String(data.question ?? '')}`
    case 'session_end': return `■ ${String(data.state ?? '')}`
    case 'done': return '■ done'
    case 'error':
    case 'run_failed': return `! ${String(data.message ?? data.error ?? '')}`
    default: return `· ${ev.event}`
  }
}
