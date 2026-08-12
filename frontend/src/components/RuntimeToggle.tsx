/* Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
 * Licensed under Elastic License 2.0 - see LICENSE.md for details. */

/**
 * RuntimeToggle - topbar pill that lets the user switch between
 * Hosted (Groq), Local (Ollama / LM Studio / llama.cpp) and BYOK
 * mid-session.
 *
 * Why this exists
 * ───────────────
 * Customers hesitate over tier selection ("what if my laptop can't
 * keep up later?"). The toggle makes the trade-off concrete and
 * reversible: pick a mode now, switch any time, never lose state.
 *
 * Behaviour
 * ─────────
 * - Calls `getLLMStrategy()` on mount + every 60 s to drive the
 *   recommendation badge.
 * - "Hosted" → removes any user-pinned provider (server falls back
 *   to system default Groq).
 * - "Local"  → configures the first detected local candidate via
 *   `configureProvider`. If none detected, opens the install guide.
 * - "BYOK"   → opens Settings → AI provider so the user can paste a
 *   key.
 *
 * The selected mode is mirrored to localStorage so the badge sticks
 * across reloads even before the next strategy fetch lands.
 */

import { Cloud, Cpu, Key, ChevronDown, Sparkles, AlertCircle, ExternalLink } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  configureProvider,
  getLLMStrategy,
  getProviderStatus,
  removeProvider,
  type RuntimeMode,
  type StrategyResponse,
} from '../lib/api'
import { Tooltip } from '../design/primitives'

const STORAGE_KEY = 'crp.runtimeMode'

type ResolvedMode = Exclude<RuntimeMode, 'buy_credits'>

const MODE_META: Record<ResolvedMode, { label: string; icon: typeof Cloud; blurb: string }> = {
  hosted: {
    label: 'Hosted',
    icon: Cloud,
    blurb: 'Fast cloud LLM (Groq). Counts against your monthly quota.',
  },
  local: {
    label: 'Local',
    icon: Cpu,
    blurb: '$0 marginal cost. Runs on your machine. Privacy by default.',
  },
  byok: {
    label: 'BYOK',
    icon: Key,
    blurb: 'Bring your own key (OpenAI, Anthropic, Azure). Centralised billing.',
  },
}

function readStoredMode(): ResolvedMode {
  if (typeof window === 'undefined') return 'hosted'
  const v = window.localStorage.getItem(STORAGE_KEY)
  if (v === 'local' || v === 'byok' || v === 'hosted') return v
  return 'hosted'
}

export function RuntimeToggle() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<ResolvedMode>(readStoredMode)
  const [strategy, setStrategy] = useState<StrategyResponse | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dropdownRef = useRef<HTMLDivElement | null>(null)

  // Fetch strategy on mount + every 60 s.
  useEffect(() => {
    let alive = true
    const refresh = async () => {
      try {
        const s = await getLLMStrategy()
        if (alive) setStrategy(s)
      } catch {
        /* anonymous user / endpoint unavailable - silent */
      }
    }
    refresh()
    const id = window.setInterval(refresh, 60_000)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [])

  // Reflect current provider configuration → mode badge.
  useEffect(() => {
    let alive = true
    getProviderStatus()
      .then((status) => {
        if (!alive) return
        if (status.configured && status.source === 'user') {
          // A user-pinned provider. Map to the toggle's three buckets:
          // - ``local_worker`` (SDK worker attached) → Local
          // - ``ollama`` / ``lmstudio`` → Local
          // - loopback / RFC1918 base_url → Local
          // - everything else → BYOK (e.g. OpenAI, Anthropic, Azure)
          const provider = status.provider
          const isWorker = provider === 'local_worker'
          const isLocalProvider = provider === 'ollama' || provider === 'lmstudio'
          const localish = (status.base_url || '').match(
            /127\.0\.0\.1|localhost|192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\./i,
          )
          setMode(isWorker || isLocalProvider || localish ? 'local' : 'byok')
        } else {
          setMode('hosted')
        }
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  // Click-outside and Escape to close dropdown.
  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const persist = useCallback((next: ResolvedMode) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* private mode - ignore */
    }
    setMode(next)
  }, [])

  const switchTo = useCallback(
    async (next: ResolvedMode) => {
      setError(null)
      setOpen(false)
      if (next === mode) return
      setBusy(true)
      try {
        if (next === 'hosted') {
          await removeProvider().catch(() => undefined)
          persist('hosted')
        } else if (next === 'local') {
          // On a hosted (SaaS) instance the API server cannot reach
          // 127.0.0.1 / RFC1918 addresses on the user's machine, so a
          // direct configureProvider() call would just 422. Route the
          // user to the Settings → SDK-worker flow instead.
          if (strategy && strategy.self_hosted === false) {
            navigate('/app/settings#sdk-worker')
            persist('local')
            return
          }
          const candidate = strategy?.local_candidates?.[0]
          if (!candidate) {
            // Nothing detected - send the user to the guide.
            navigate('/app/settings#ai-provider')
            setError('No local LLM detected. See the install guide on the Settings page.')
            return
          }
          await configureProvider({
            provider: (candidate.provider === 'ollama' || candidate.provider === 'lmstudio'
              ? candidate.provider
              : 'custom') as 'ollama' | 'lmstudio' | 'custom',
            base_url: candidate.base_url,
            // Backend requires api_key.min_length=1; local endpoints don't validate it.
            api_key: 'local-no-auth',
            model: '',
          })
          persist('local')
        } else if (next === 'byok') {
          // BYOK requires the user to paste a key - drop into Settings.
          navigate('/app/settings#ai-provider')
          persist('byok')
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Failed to switch runtime mode'
        setError(msg)
      } finally {
        setBusy(false)
      }
    },
    [mode, navigate, persist, strategy],
  )

  const ModeIcon = MODE_META[mode].icon
  const recommended = strategy?.recommended
  const showRecommendBadge =
    recommended && recommended !== 'buy_credits' && recommended !== mode

  return (
    <div className="relative" ref={dropdownRef}>
      <Tooltip
        label={
          showRecommendBadge
            ? `Recommended: ${MODE_META[recommended as ResolvedMode]?.label} - ${strategy?.reason ?? ''}`
            : `Currently running in ${MODE_META[mode].label} mode. Click to switch.`
        }
        side="bottom"
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label={`AI runtime: ${MODE_META[mode].label}. Click to change.`}
          disabled={busy}
          className="flex items-center gap-1.5 h-10 px-2.5 rounded-md text-xs font-medium border border-hairline bg-surface-2 hover:bg-surface text-ink-2 hover:text-ink focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-60"
        >
          <ModeIcon className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{MODE_META[mode].label}</span>
          {showRecommendBadge && (
            <Sparkles
              className="h-3 w-3 text-amber-500 dark:text-amber-400"
              aria-label="Recommendation available"
            />
          )}
          <ChevronDown className="h-3 w-3 opacity-60" aria-hidden="true" />
        </button>
      </Tooltip>

      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-1.5 w-72 rounded-lg border border-hairline bg-surface shadow-lg z-50 p-1.5"
        >
          <div className="px-2 py-1.5 text-xs uppercase tracking-wide text-ink-4 font-semibold">
            AI runtime
          </div>
          {(Object.keys(MODE_META) as ResolvedMode[]).map((key) => {
            const meta = MODE_META[key]
            const Icon = meta.icon
            const isActive = mode === key
            const isRecommended = recommended === key && !isActive
            return (
              <button
                type="button"
                key={key}
                role="menuitemradio"
                aria-checked={isActive}
                onClick={() => switchTo(key)}
                disabled={busy}
                className={`w-full text-left flex gap-2.5 items-start px-2.5 py-2 rounded-md text-sm hover:bg-surface-2 disabled:opacity-60 ${
                  isActive ? 'bg-surface-2' : ''
                }`}
              >
                <Icon className="h-4 w-4 mt-0.5 text-ink-3 shrink-0" aria-hidden="true" />
                <span className="flex-1 min-w-0">
                  <span className="flex items-center gap-2">
                    <span className="font-medium text-ink">{meta.label}</span>
                    {isActive && (
                      <span className="text-xs uppercase text-emerald-600 dark:text-emerald-400 font-semibold">
                        Active
                      </span>
                    )}
                    {isRecommended && (
                      <span className="text-xs uppercase text-amber-600 dark:text-amber-400 font-semibold">
                        Recommended
                      </span>
                    )}
                  </span>
                  <span className="block text-sm leading-snug text-ink-3 mt-0.5">
                    {meta.blurb}
                  </span>
                </span>
              </button>
            )
          })}

          {strategy && showRecommendBadge && (
            <div className="mx-1 mt-1 mb-1 p-2 rounded-md bg-amber-500/10 border border-amber-500/20 text-sm leading-snug text-amber-700 dark:text-amber-300 flex gap-1.5">
              <Sparkles className="h-3 w-3 mt-0.5 shrink-0" aria-hidden="true" />
              <span>{strategy.reason}</span>
            </div>
          )}

          {error && (
            <div className="mx-1 mt-1 p-2 rounded-md bg-rose-500/10 border border-rose-500/20 text-sm leading-snug text-rose-700 dark:text-rose-300 flex gap-1.5">
              <AlertCircle className="h-3 w-3 mt-0.5 shrink-0" aria-hidden="true" />
              <span>{error}</span>
            </div>
          )}

          <a
            href="/docs/local-llm-guide"
            onClick={(e) => {
              e.preventDefault()
              setOpen(false)
              navigate('/app/guide#runtime-modes')
            }}
            className="flex items-center gap-1.5 px-2.5 py-1.5 mt-1 text-sm text-ink-3 hover:text-ink rounded-md"
          >
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
            Why does this matter?
          </a>
        </div>
      )}
    </div>
  )
}

