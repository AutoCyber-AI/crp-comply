/**
 * NoCode Agent Panel - embedded compact agent chat for the No-Code page.
 *
 * Reuses the existing /agent/loop/stream endpoint with no-code context
 * seeded in extra_context so the agent can explain policies, recommend
 * configurations, and apply presets conversationally.
 */
import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import {
  Send,
  X,
  Sparkles,
  Bot,
  User,
  Wand2,
  MessageCircle,
  ChevronDown,
  Shield,
  Square,
  AlertTriangle,
  GripVertical,
  RotateCcw,
  Zap,
} from 'lucide-react'
import { agentLoopStream } from '../lib/api'
import { LazyMarkdown as Markdown } from '../design/LazyMarkdown'
import { useToast } from './toast/ToastProvider'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { useReducedMotion } from '../hooks/useReducedMotion'
import ReasoningTimeline from './ReasoningTimeline'
import ReasoningTape from './ReasoningTape'
import type { LoopEvent } from '@/lib/loopEvents'
import clsx from 'clsx'

interface ChatMessage {
  role: 'user' | 'agent'
  text: string
  loading?: boolean
  timestamp?: number
}

interface NoCodeAgentPanelProps {
  profile?: string
  grounding?: number
  globalCapabilities?: Set<string>
  scanFindingsCount?: number
  onApplyPreset?: (preset: string) => void
  mode?: 'no-code' | 'global'
}

const SUGGESTED_PROMPTS = [
  { text: 'What does halt-on-critical do?', icon: Shield },
  { text: 'Should I enable PII detection for medical?', icon: Shield },
  { text: 'Apply the strict preset', icon: Wand2 },
  { text: 'Explain my current policy', icon: Bot },
  { text: 'Which capabilities satisfy GDPR?', icon: Shield },
]

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 px-1 py-2">
      <div className="h-1.5 w-1.5 rounded-full bg-ink-3 animate-typing-dot" style={{ animationDelay: '0ms' }} />
      <div className="h-1.5 w-1.5 rounded-full bg-ink-3 animate-typing-dot" style={{ animationDelay: '150ms' }} />
      <div className="h-1.5 w-1.5 rounded-full bg-ink-3 animate-typing-dot" style={{ animationDelay: '300ms' }} />
    </div>
  )
}

export default function NoCodeAgentPanel({
  profile = 'general',
  grounding = 0.75,
  globalCapabilities = new Set(),
  scanFindingsCount = 0,
  onApplyPreset,
  mode = 'no-code',
}: NoCodeAgentPanelProps) {
  const isGlobal = mode === 'global'
  const defaultGreeting = isGlobal
    ? "I'm your AI governance assistant. Ask me about CRP capabilities, compliance frameworks, safety policies, or how to get started."
    : `I can explain governance capabilities, recommend presets based on your ${scanFindingsCount} finding(s), and help you understand regulatory requirements. What would you like to know?`
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'agent',
      text: defaultGreeting,
      timestamp: Date.now(),
    },
  ])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [streamingModel, setStreamingModel] = useState<string | null>(null)
  const [lastFailedMessage, setLastFailedMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [unreadCount, setUnreadCount] = useState(0)
  const [loopEvents, setLoopEvents] = useState<LoopEvent[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const messagesRef = useRef<HTMLDivElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const streamingTextRef = useRef(streamingText)
  const panelRef = useFocusTrap<HTMLDivElement>({
    active: open,
    onEscape: () => setOpen(false),
  })
  const prefersReducedMotion = useReducedMotion()
  const toast = useToast()

  // Draggable global popup state
  const storageKey = 'crp:global-assistant:position'
  const defaultPosition = { x: 0, y: 0 }
  const [position, setPosition] = useState<{ x: number; y: number }>(() => {
    if (typeof window === 'undefined') return defaultPosition
    try {
      const raw = window.localStorage.getItem(storageKey)
      const parsed = raw ? JSON.parse(raw) : null
      if (parsed && typeof parsed.x === 'number' && typeof parsed.y === 'number') {
        return parsed
      }
    } catch {
      // ignore corrupt storage
    }
    return defaultPosition
  })
  const dragState = useRef({
    active: false,
    startX: 0,
    startY: 0,
    initialX: 0,
    initialY: 0,
  })
  const panelRectRef = useRef<{ width: number; height: number }>({ width: 0, height: 0 })

  useEffect(() => {
    streamingTextRef.current = streamingText
  }, [streamingText])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth' })
  }, [messages, streamingText, open, prefersReducedMotion])

  // Clamp the saved popup position when the viewport changes so it cannot
  // be dragged entirely off-screen.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const clamp = () => {
      const el = panelRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      panelRectRef.current = { width: rect.width, height: rect.height }
      const maxX = Math.max(0, window.innerWidth - rect.width)
      const maxY = Math.max(0, window.innerHeight - rect.height)
      setPosition((prev) => ({
        x: Math.max(-maxX, Math.min(maxX, prev.x)),
        y: Math.max(-maxY, Math.min(maxY, prev.y)),
      }))
    }
    clamp()
    window.addEventListener('resize', clamp)
    return () => window.removeEventListener('resize', clamp)
  }, [open, panelRef])

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isGlobal) return
    const el = panelRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    panelRectRef.current = { width: rect.width, height: rect.height }
    dragState.current = {
      active: true,
      startX: e.clientX,
      startY: e.clientY,
      initialX: position.x,
      initialY: position.y,
    }
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
  }

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragState.current.active || !isGlobal) return
    const dx = e.clientX - dragState.current.startX
    const dy = e.clientY - dragState.current.startY
    const rect = panelRectRef.current
    const maxX = Math.max(0, window.innerWidth - rect.width)
    const maxY = Math.max(0, window.innerHeight - rect.height)
    setPosition({
      x: Math.max(-maxX, Math.min(maxX, dragState.current.initialX + dx)),
      y: Math.max(-maxY, Math.min(maxY, dragState.current.initialY + dy)),
    })
  }

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragState.current.active) return
    dragState.current.active = false
    ;(e.target as HTMLElement).releasePointerCapture?.(e.pointerId)
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(position))
    } catch {
      // ignore storage errors
    }
  }

  const resetPosition = () => {
    setPosition(defaultPosition)
    try {
      window.localStorage.removeItem(storageKey)
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    if (open && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 200)
    }
  }, [open])

  const buildContext = useCallback(() => {
    const caps = Array.from(globalCapabilities)
    if (isGlobal) {
      return (
        `You are a helpful AI governance assistant embedded in CRP Comply. ` +
        `You explain CRP capabilities in plain language, compare governance strategies, ` +
        `and help users understand regulatory requirements such as the EU AI Act, ISO 42001, NIST AI RMF, and GDPR. ` +
        `Keep answers concise (2-4 sentences) unless the user asks for detail. ` +
        `When recommending, mention the specific regulation article or control where possible.`
      )
    }
    return (
      `Current no-code configuration:\n` +
      `- Profile: ${profile}\n` +
      `- Grounding threshold: ${grounding}\n` +
      `- Enabled capabilities: ${caps.length > 0 ? caps.join(', ') : 'none'}\n` +
      `- Scan findings: ${scanFindingsCount}\n\n` +
      `You are a helpful AI governance assistant embedded in the No-Code Governance UI. ` +
      `You explain CRP capabilities in plain language, recommend policies based on industry and findings, ` +
      `and help users understand regulatory requirements. Keep answers concise (2-4 sentences) ` +
      `unless the user asks for detail. When recommending, mention the specific regulation article.`
    )
  }, [profile, grounding, globalCapabilities, scanFindingsCount, isGlobal])

  const send = async (text: string, isRetry = false) => {
    if (!text.trim() || loading) return
    setLoading(true)
    setDraft('')
    setError(null)
    setStreamingText('')
    setStreamingModel(null)
    setLoopEvents([])
    if (!isRetry) setLastFailedMessage(text)
    const now = Date.now()
    setMessages((prev) => [...prev, { role: 'user', text, timestamp: now }])

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const stream = agentLoopStream(
        {
          task: text,
          system_id: 'no-code-governance',
          customer_id: 'no-code-user',
          extra_context: buildContext(),
          max_iters: 6,
        },
        controller.signal,
      )

      for await (const ev of stream) {
        const eventName = String(ev.event || '')
        const data = (ev.data && typeof ev.data === 'object' ? ev.data : {}) as Record<string, unknown>

        // Normalise the SSE frame into a LoopEvent so the reasoning tape
        // can render it the same way v2/AgentChat does.
        if (typeof eventName === 'string' && eventName.startsWith('loop.')) {
          const evtName = String(data.event ?? eventName)
          const tapeEv = { ...data, event: evtName } as unknown as LoopEvent
          setLoopEvents((prev) => [...prev, tapeEv])
        }

        if (eventName === 'loop.opened') {
          const model = String(data.model || '')
          if (model) setStreamingModel(model)
        }

        if (eventName === 'loop.thought.delta') {
          setStreamingText((prev) => prev + String(data.text || ''))
        }

        if (eventName === 'loop.final') {
          const summary = String(data.summary || '')
          if (summary) setStreamingText(summary)
        }

        if (eventName === 'loop.error') {
          throw new Error(String(data.message || 'Agent error'))
        }

        if (eventName === 'done') break
      }

      const finalText = streamingTextRef.current
      setMessages((prev) => [
        ...prev,
        { role: 'agent', text: finalText, loading: false, timestamp: Date.now() },
      ])
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Something went wrong.'
      setError(msg)
      setMessages((prev) => [
        ...prev,
        { role: 'agent', text: `Error: ${msg}`, loading: false, timestamp: Date.now() },
      ])
    } finally {
      abortControllerRef.current = null
      setLoading(false)
      setStreamingText('')
      setStreamingModel(null)
      if (!open) {
        setUnreadCount((c) => c + 1)
      }
    }
  }

  const handleCancel = () => {
    abortControllerRef.current?.abort()
  }

  const handleRetry = () => {
    if (lastFailedMessage) send(lastFailedMessage, true)
  }

  const latestThinkingLabel = useMemo(() => {
    if (streamingText) return ''
    for (let i = loopEvents.length - 1; i >= 0; i--) {
      const ev = loopEvents[i]
      if (ev.event === 'loop.step.start' && ev.intent) {
        return ev.intent
      }
      if (ev.event === 'loop.tool.call' && ev.tool) {
        return `Calling ${ev.tool}…`
      }
      if (ev.event === 'loop.web.start' && ev.query) {
        return `Searching the web for "${ev.query}"…`
      }
    }
    return 'Thinking…'
  }, [loopEvents, streamingText])

  const detectedSlots = useMemo(() => {
    const nlu = loopEvents.find((e) => (e as unknown as { event: string }).event === 'loop.nlu')
    if (!nlu || !('slots' in nlu)) return null
    return (nlu as unknown as { slots: Record<string, string | undefined> }).slots
  }, [loopEvents])

  const handlePresetCommand = (text: string) => {
    if (!onApplyPreset) return false
    const lower = text.toLowerCase()
    const presets = ['balanced', 'strict', 'medical', 'financial', 'minimal']
    for (const p of presets) {
      if (lower.includes(`apply the ${p}`) || lower.includes(`use ${p}`) || lower.includes(`set ${p}`)) {
        onApplyPreset(p)
        console.log(`[NoCodeAgent] Applied ${p} preset via chat command`)
        toast.success('Preset applied', `The ${p} preset has been applied to your configuration.`)
        return true
      }
    }
    return false
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (handlePresetCommand(draft)) {
      const matched = draft.match(/(balanced|strict|medical|financial|minimal)/i)
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: draft, timestamp: Date.now() },
        { role: 'agent', text: `Applied the **${matched?.[0] || 'selected'}** preset to your configuration.`, loading: false, timestamp: Date.now() },
      ])
      setDraft('')
      return
    }
    send(draft)
  }

  const formatTime = (ts?: number) => {
    if (!ts) return ''
    const d = new Date(ts)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => { setOpen(true); setUnreadCount(0) }}
        className="fixed bottom-6 right-6 z-50 group inline-flex items-center gap-2.5 rounded-full bg-ink text-white px-5 py-3.5 shadow-crp-lg hover:shadow-xl hover:bg-ink-2 transition-all duration-crp ease-crp animate-scale-in"
        aria-label="Open Governance Assistant chat"
      >
        <div className="relative">
          <Sparkles className="h-5 w-5 text-brand-400" aria-hidden="true" />
          {unreadCount > 0 && (
            <span className="absolute -top-1.5 -right-1.5 h-4 w-4 rounded-full bg-danger text-white text-[9px] font-bold grid place-items-center animate-scale-in" aria-label={`${unreadCount} unread messages`}>
              {unreadCount}
            </span>
          )}
        </div>
        <span className="text-sm font-semibold">Governance Assistant</span>
        <ChevronDown className="h-3.5 w-3.5 text-ink-3" aria-hidden="true" />
      </button>
    )
  }

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-label="Governance Assistant"
      className="fixed bottom-6 right-6 z-50 w-[22rem] sm:w-[28rem] h-[32rem] flex flex-col rounded-2xl border border-hairline bg-surface/95 backdrop-blur-xl shadow-2xl overflow-hidden animate-scale-in"
      style={{ transform: 'translate(' + position.x + 'px, ' + position.y + 'px)' }}
    >
      {/* Header */}
      <div
        className={clsx(
          'flex items-center justify-between px-5 py-3.5 border-b border-hairline bg-gradient-to-r from-surface to-surface-2 select-none',
          isGlobal && 'cursor-move'
        )}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        <div className="flex items-center gap-3">
          {isGlobal && (
            <div className="text-ink-3" aria-label="Drag to move" title="Drag to move">
              <GripVertical className="h-4 w-4" />
            </div>
          )}
          <div className="h-9 w-9 rounded-xl bg-brand-100 grid place-items-center relative">
            <Bot className="h-5 w-5 text-brand-800" />
            <span className="absolute bottom-0 right-0 h-2.5 w-2.5 rounded-full bg-emerald-500 border-2 border-surface" />
          </div>
          <div>
            <div className="text-sm font-bold text-ink">Governance Assistant</div>
            <div className="text-[10px] text-ink-3 font-medium flex items-center gap-1.5">
              <span>Online · Ask about policies, regulations, setup</span>
              {streamingModel && (
                <span className="inline-flex items-center rounded-full bg-brand-100 px-1.5 py-0.5 text-[9px] font-semibold text-brand-800">
                  {streamingModel}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {isGlobal && (
            <button
              type="button"
              aria-label="Reset assistant position"
              title="Reset position"
              onClick={resetPosition}
              className="h-8 w-8 rounded-full bg-surface-2 hover:bg-surface-3 grid place-items-center text-ink-3 hover:text-ink transition-all duration-crp"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          )}
          <button
            type="button"
            aria-label="Close Governance Assistant"
            onClick={() => setOpen(false)}
            className="h-8 w-8 rounded-full bg-surface-2 hover:bg-surface-3 grid place-items-center text-ink-3 hover:text-ink transition-all duration-crp"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mx-5 mt-3 rounded-xl border border-danger/20 bg-danger-muted px-3 py-2 text-xs text-danger flex items-start gap-2">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          <div className="flex-1">{error}</div>
          {lastFailedMessage && (
            <button
              type="button"
              onClick={handleRetry}
              className="font-semibold underline underline-offset-2 hover:text-danger/80"
            >
              Retry
            </button>
          )}
        </div>
      )}

      {/* Messages */}
      <div
        ref={messagesRef}
        className="flex-1 overflow-y-auto px-5 py-4 space-y-4"
        role="log"
        aria-live="polite"
        aria-atomic="false"
        aria-label="Conversation transcript"
      >
        {messages.map((m, i) => (
          <div key={i} className={clsx('flex gap-3', m.role === 'user' ? 'justify-end' : 'justify-start')}>
            {m.role === 'agent' && (
              <div className="h-7 w-7 rounded-lg bg-brand-100 grid place-items-center shrink-0 mt-0.5">
                <Bot className="h-3.5 w-3.5 text-brand-800" />
              </div>
            )}
            <div className="flex flex-col max-w-[82%]">
              <div
                className={clsx(
                  'rounded-2xl px-4 py-2.5 text-xs leading-relaxed shadow-sm transition-all duration-300',
                  m.role === 'user'
                    ? 'bg-ink text-white rounded-br-md'
                    : 'bg-surface-2 text-ink-2 border border-hairline rounded-bl-md',
                )}
              >
                {m.loading ? (
                  <TypingIndicator />
                ) : m.role === 'agent' ? (
                  <Markdown className="prose-xs">{m.text}</Markdown>
                ) : (
                  <span>{m.text}</span>
                )}
              </div>
              <span className={clsx('text-[9px] text-ink-4 mt-1 px-1', m.role === 'user' ? 'text-right' : 'text-left')}>
                {formatTime(m.timestamp)}
              </span>
            </div>
            {m.role === 'user' && (
              <div className="h-7 w-7 rounded-lg bg-surface-3 grid place-items-center shrink-0 mt-0.5">
                <User className="h-3.5 w-3.5 text-ink-3" />
              </div>
            )}
          </div>
        ))}
        {(loading || streamingText.length > 0) && (
          <div className="flex gap-3 justify-start animate-fade-in">
            <div className="h-7 w-7 rounded-lg bg-brand-100 grid place-items-center shrink-0 mt-0.5">
              <Bot className="h-3.5 w-3.5 text-brand-800" />
            </div>
            <div className="flex flex-col max-w-[82%]">
              <div className="rounded-2xl px-4 py-2.5 text-xs leading-relaxed shadow-sm bg-surface-2 text-ink-2 border border-hairline rounded-bl-md">
                {streamingText.length > 0 ? (
                  <>
                    <Markdown className="prose-xs">{streamingText}</Markdown>
                    <span className="inline-block h-2 w-2 rounded-full bg-brand-500 ml-1 animate-pulse" aria-hidden="true" />
                  </>
                ) : (
                  <div className="space-y-1">
                    <div className="italic text-ink-3">{latestThinkingLabel}</div>
                    <TypingIndicator />
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Reasoning / audit trail */}
      {loopEvents.length > 0 && (
        <div className="px-5 pb-2">
          {detectedSlots && (
            <div className="mb-2 flex flex-wrap gap-1">
              {detectedSlots.jurisdiction && (
                <span className="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-700 ring-1 ring-indigo-200">
                  {String(detectedSlots.jurisdiction)}
                </span>
              )}
              {detectedSlots.regulation && (
                <span className="inline-flex items-center rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-700 ring-1 ring-sky-200">
                  {String(detectedSlots.regulation)}
                </span>
              )}
              {detectedSlots.system_type && (
                <span className="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700 ring-1 ring-emerald-200">
                  {String(detectedSlots.system_type)}
                </span>
              )}
              {detectedSlots.intent && (
                <span className="inline-flex items-center rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-medium text-violet-700 ring-1 ring-violet-200">
                  intent: {String(detectedSlots.intent)}
                </span>
              )}
            </div>
          )}
          <details className="rounded-xl border border-hairline bg-surface px-3 py-2 shadow-sm">
            <summary className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-ink-3 font-bold cursor-pointer list-none">
              <Zap className="h-3 w-3" /> Show reasoning{' '}
              <span className="text-ink-4 font-normal normal-case">({loopEvents.length} event{loopEvents.length === 1 ? '' : 's'})</span>
            </summary>
            <div className="mt-2 max-h-40 overflow-y-auto">
              <ReasoningTimeline events={loopEvents} />
            </div>
            <details className="mt-2 text-[10px] text-ink-3">
              <summary className="cursor-pointer hover:text-ink-2 font-medium">Full audit trail</summary>
              <div className="mt-1 max-h-40 overflow-y-auto">
                <ReasoningTape events={loopEvents} />
              </div>
            </details>
          </details>
        </div>
      )}

      {/* Suggested prompts */}
      {messages.length <= 2 && !loading && (
        <div className="px-5 pb-3 flex flex-wrap gap-1.5" role="list" aria-label="Suggested questions">
          {SUGGESTED_PROMPTS.map((p) => {
            const Icon = p.icon
            return (
              <button
                type="button"
                key={p.text}
                onClick={() => send(p.text)}
                className="group inline-flex items-center gap-1.5 rounded-full border border-hairline bg-surface px-3 py-1.5 text-xs text-ink-3 hover:border-brand-300 hover:text-brand-800 hover:bg-brand-50 transition-all duration-crp"
                aria-label={`Ask: ${p.text}`}
              >
                <Icon className="h-3 w-3" aria-hidden="true" />
                {p.text}
              </button>
            )
          })}
        </div>
      )}

      {/* Composer */}
      <form onSubmit={handleSubmit} className="px-5 py-3.5 border-t border-hairline bg-surface">
        <div className="flex items-center gap-2 bg-surface-2 rounded-full border border-hairline px-1 py-1 focus-within:border-brand-300 focus-within:ring-2 focus-within:ring-brand-200/50 transition-all duration-crp">
          <MessageCircle className="h-3.5 w-3.5 text-ink-4 ml-3 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Ask about policies, regulations, or presets…"
            aria-label="Ask the Governance Assistant"
            className="flex-1 bg-transparent px-1 py-2 text-xs text-ink placeholder:text-ink-4 focus:outline-none"
          />
          {loading ? (
            <button
              type="button"
              onClick={handleCancel}
              aria-label="Stop generating"
              className="h-8 w-8 rounded-full bg-danger text-white grid place-items-center hover:bg-danger/90 transition-all duration-crp shrink-0"
            >
              <Square className="h-3.5 w-3.5" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!draft.trim()}
              className="h-8 w-8 rounded-full bg-ink text-white grid place-items-center hover:bg-ink-2 disabled:opacity-40 disabled:hover:bg-ink transition-all duration-crp shrink-0"
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <div className="text-center mt-1.5">
          <span className="text-[9px] text-ink-4">Press Enter to send · AI-generated, verify critical decisions</span>
        </div>
      </form>
    </div>
  )
}
