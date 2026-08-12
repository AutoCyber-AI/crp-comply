import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Show } from '@clerk/react'
import {
  Sparkles,
  AlertTriangle,
  ShieldAlert,
  ShieldCheck,
  FileText,
  ArrowRight,
  Loader2,
  CheckCircle2,
  XCircle,
  Info,
  Brain,
  TrendingUp,
  Building2,
} from 'lucide-react'

type ClassifierResult = {
  risk_level: 'UNACCEPTABLE' | 'HIGH' | 'LIMITED' | 'MINIMAL'
  category: string
  matched_keywords: string[]
  summary: string
  article_citations: { article: string; title: string; url?: string }[]
  obligations: string[]
  fine_exposure: {
    max_fine_eur: number
    max_fine_pct_revenue: number
    source: string
  }
  next_steps: string[]
  upgrade_message: string
  llm_narrative?: string | null
  llm_model?: string | null
  narrative_source?: 'llm' | 'deterministic'
}

type PublicStats = {
  total: number
  last_7_days: number
  by_risk_level: Record<string, number>
  high_risk_pct: number
  actionable_count?: number
  actionable_pct?: number
  top_categories?: { category: string; count: number }[]
  lead_count?: number
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export default function FreeAssessment() {
  const [description, setDescription] = useState('')
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ClassifierResult | null>(null)
  const [stats, setStats] = useState<PublicStats | null>(null)

  // Pull stats once on mount for the social-proof banner. Best-effort -
  // failures are silent (the banner just doesn't render).
  useEffect(() => {
    let mounted = true
    fetch(`${API_BASE}/api/v1/public/risk-classifier/stats`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: PublicStats | null) => {
        if (mounted && data && typeof data.total === 'number') setStats(data)
      })
      .catch(() => { /* offline / cold start */ })
    return () => {
      mounted = false
    }
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setResult(null)

    if (description.trim().length < 20) {
      setError('Please provide at least 20 characters describing your AI system.')
      return
    }

    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/public/risk-classifier`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: description.trim(),
          email: email.trim() || null,
          jurisdiction: 'EU',
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Request failed (${res.status})`)
      }
      const data: ClassifierResult = await res.json()
      setResult(data)
    } catch (err: any) {
      setError(err.message || 'Classification failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-[80vh]">
      <section className="relative pt-16 pb-12 bg-gradient-to-b from-brand-50/40 to-white">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
          <div className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-800 ring-1 ring-brand-200 mb-4">
            <Sparkles className="w-3.5 h-3.5" />
            Free EU AI Act classifier
          </div>
          <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-gray-900">
            Is your AI system high-risk?
          </h1>
          <p className="mt-4 text-lg text-gray-600 max-w-2xl leading-relaxed">
            Describe what your AI system does in a few sentences. We'll classify it against
            EU AI Act Art. 6 and Annex III criteria, cite the relevant articles, and estimate your
            fine exposure. No signup required. For GDPR or ISO 42001 assessments, sign in and run
            the full Recipe Library.
          </p>
        </div>
      </section>

      <section className="pb-20">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
          {!result && (
            <div className="mb-6 rounded-xl border border-brand-100 bg-brand-50/40 px-4 py-3 text-sm text-gray-700">
              <div className="flex flex-wrap items-center gap-x-6 gap-y-1.5">
                <span className="inline-flex items-center gap-1.5 font-semibold text-brand-800">
                  <TrendingUp className="w-4 h-4" />
                  {(stats?.total ?? 0).toLocaleString()} assessments run on this instance (all‑time)
                </span>
                {(stats?.last_7_days ?? 0) > 0 && (
                  <span className="text-gray-600">
                    <strong className="text-gray-900">{stats!.last_7_days.toLocaleString()}</strong> in the last 7 days
                  </span>
                )}
                {(stats?.actionable_pct ?? 0) > 0 && (
                  <span className="text-gray-600">
                    <strong className="text-gray-900">{stats!.actionable_pct}%</strong> required concrete obligations
                  </span>
                )}
                {(stats?.high_risk_pct ?? 0) > 0 && (
                  <span className="text-gray-600">
                    <strong className="text-gray-900">{stats!.high_risk_pct}%</strong> classified high‑risk or prohibited
                  </span>
                )}
                {(!stats || stats.total === 0) && (
                  <span className="text-gray-600 italic">
                    Be the first - your assessment will be counted (anonymously).
                  </span>
                )}
              </div>
              {stats && stats.total > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-600">
                  {(['UNACCEPTABLE','HIGH','LIMITED','MINIMAL'] as const).map((lvl) => {
                    const n = stats.by_risk_level?.[lvl] ?? 0
                    if (!n) return null
                    const color =
                      lvl === 'UNACCEPTABLE' ? 'text-red-700' :
                      lvl === 'HIGH'         ? 'text-orange-700' :
                      lvl === 'LIMITED'      ? 'text-amber-700' :
                                               'text-emerald-700'
                    return (
                      <span key={lvl} className={color}>
                        <strong>{n}</strong> {lvl.toLowerCase()}
                      </span>
                    )
                  })}
                  {stats.top_categories && stats.top_categories.length > 0 && (
                    <span className="text-gray-600">
                      · most common: {stats.top_categories.slice(0, 3).map((c) => c.category.replace(/_/g, ' ').toLowerCase()).join(', ')}
                    </span>
                  )}
                </div>
              )}
            </div>
          )}
          {!result && (
            <form onSubmit={submit} className="rounded-2xl border border-gray-200 bg-white shadow-sm p-6 sm:p-8">
              <label htmlFor="description" className="label">Describe your AI system</label>
              <p className="text-sm text-gray-600 mb-2">
                What does it do, who uses it, what data does it process, what decisions does it make?
                Be specific - the more detail, the better the classification.
              </p>
              <textarea
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Example: Our AI system is a resume screening tool used by HR teams. It ingests candidate CVs, scores them against job requirements, and recommends top candidates. It processes personal data including employment history, education, and demographic information."
                className="input min-h-[180px] resize-y"
                maxLength={2000}
                required
                aria-invalid={!!error}
                aria-describedby={error ? 'description-error' : undefined}
              />
              <div className="mt-1 text-right text-xs text-gray-600">
                {description.length} / 2000
              </div>

              <div className="mt-6">
                <label htmlFor="email" className="label">Email <span className="text-gray-600 font-normal">(optional)</span></label>
                <p className="text-sm text-gray-600 mb-2">
                  Receive your classification, obligations, and EU AI Act article citations.
                </p>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  className="input"
                />
              </div>

              {error && (
                <div id="description-error" className="mt-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-800 flex items-start gap-2">
                  <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0" aria-hidden="true" />
                  <span>{error}</span>
                </div>
              )}

              <div className="mt-6 flex flex-col sm:flex-row items-start sm:items-center gap-3 justify-between">
                <div className="text-xs text-gray-600 flex items-center gap-1.5">
                  <Info className="w-3.5 h-3.5" />
                  Rate-limited to 5 free assessments per hour. No data stored beyond anonymous metrics.
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="btn-primary px-6 py-2.5 disabled:opacity-60 disabled:cursor-not-allowed min-w-[180px]"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Classifying...
                    </>
                  ) : (
                    <>
                      Classify my system
                      <ArrowRight className="w-4 h-4 ml-2" />
                    </>
                  )}
                </button>
              </div>
            </form>
          )}

          {result && (
            <ResultView
              result={result}
              originalDescription={description}
              originalEmail={email}
              onReset={() => {
                setResult(null)
                setDescription('')
              }}
            />
          )}
        </div>
      </section>
    </div>
  )
}

function ResultView({
  result,
  originalDescription,
  originalEmail,
  onReset,
}: {
  result: ClassifierResult
  originalDescription: string
  originalEmail: string
  onReset: () => void
}) {
  const style = RISK_STYLES[result.risk_level]
  const [emailInput, setEmailInput] = useState(originalEmail || '')
  const [sending, setSending] = useState(false)
  const [emailMsg, setEmailMsg] = useState<{ ok: boolean; text: string } | null>(null)

  async function sendEmail() {
    if (!emailInput.trim()) {
      setEmailMsg({ ok: false, text: 'Enter your email address first.' })
      return
    }
    setSending(true)
    setEmailMsg(null)
    try {
      const res = await fetch(`${API_BASE}/api/v1/public/email-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: emailInput.trim(),
          description: originalDescription,
          risk_level: result.risk_level,
          category: result.category,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data.detail || `Send failed (${res.status})`)
      }
      setEmailMsg({ ok: !!data.sent, text: data.message || 'Sent.' })
    } catch (err: any) {
      setEmailMsg({ ok: false, text: err.message || 'Could not send email.' })
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className={`rounded-2xl border-2 p-6 sm:p-8 ${style.container}`}>
        <div className="flex items-start gap-4">
          <div className={`flex-shrink-0 w-12 h-12 rounded-xl flex items-center justify-center ${style.iconBg}`}>
            {style.icon}
          </div>
          <div className="flex-1">
            <div className={`text-xs font-bold uppercase tracking-wider ${style.label}`}>
              {style.headline}
            </div>
            <h2 className="text-3xl sm:text-4xl font-bold text-gray-900 mt-1">
              Risk level: {result.risk_level}
            </h2>
            <p className="mt-2 text-sm text-gray-600">
              Category: <strong className="text-gray-900">{result.category.replace(/_/g, ' ')}</strong>
              {result.matched_keywords.length > 0 && (
                <>
                  {' · '}Matched: {result.matched_keywords.map((k) => (
                    <span key={k} className="inline-block ml-1 rounded-full bg-white px-2 py-0.5 text-xs font-medium">
                      {k}
                    </span>
                  ))}
                </>
              )}
            </p>
          </div>
        </div>
        <p className="mt-6 text-base text-gray-800 leading-relaxed">{result.summary}</p>
      </div>

      {/* LLM Reasoning - primary value-prop. Only renders if the operator has
          a configured LLM provider. Otherwise, the rule-based summary above
          carries the page on its own. */}
      {result.llm_narrative && result.llm_narrative.trim().length > 0 && (
        <div className="rounded-2xl border border-brand-200 bg-gradient-to-br from-brand-50/50 to-white p-6 sm:p-8">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-brand-600 text-brand-900 flex items-center justify-center">
              <Brain className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-brand-800">
              CRP Comply analyst memo
            </h3>
            {result.narrative_source === 'llm' && result.llm_model ? (
              <span className="ml-auto text-xs text-gray-600">via {result.llm_model}</span>
            ) : (
              <span
                className="ml-auto text-xs text-amber-700"
                title="The upstream LLM call failed or no provider was configured. The memo below is the rule-based fallback. Operators: hit Settings → Diagnose to see the exact error."
              >
                rule‑based fallback
              </span>
            )}
          </div>
          <div className="space-y-3 text-sm sm:text-base text-gray-800 leading-relaxed whitespace-pre-line">
            {result.llm_narrative}
          </div>
        </div>
      )}

      {/* Fine Exposure */}
      {result.fine_exposure.max_fine_eur > 0 && (
        <div className="rounded-2xl border border-gray-200 bg-white p-6 sm:p-8">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-600 mb-3">
            Maximum fine exposure
          </h3>
          <div className="flex items-baseline gap-4">
            <div className="text-5xl font-bold text-gray-900">
              €{(result.fine_exposure.max_fine_eur / 1_000_000).toFixed(0)}M
            </div>
            <div className="text-xl text-gray-600">
              or {result.fine_exposure.max_fine_pct_revenue}% of global revenue
            </div>
          </div>
          <div className="mt-2 text-xs text-gray-600">Source: {result.fine_exposure.source}</div>
        </div>
      )}

      {/* Article Citations */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6 sm:p-8">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-600 mb-4 flex items-center gap-2">
          <FileText className="w-4 h-4" />
          Relevant EU AI Act articles
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {result.article_citations.map((c) => (
            <div key={c.article} className="rounded-lg bg-gray-50 p-3 border border-gray-100">
              <div className="text-sm font-bold text-brand-800">{c.article}</div>
              <div className="text-sm text-gray-700 mt-0.5">{c.title}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Obligations */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6 sm:p-8">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-600 mb-4">
          What you must do
        </h3>
        <ul className="space-y-2.5">
          {result.obligations.map((o, i) => (
            <li key={i} className="flex items-start gap-2.5 text-sm text-gray-800 leading-relaxed">
              <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0 text-brand-800" />
              <span>{o}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Email this report */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6 sm:p-8">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-600 mb-3">
          Email me this report
        </h3>
        <p className="text-sm text-gray-600 mb-4">
          Get the analyst memo, obligations checklist and article citations
          delivered to your inbox - useful when you need to forward it to legal,
          your CISO, or a procurement team.
        </p>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="email"
            value={emailInput}
            onChange={(e) => setEmailInput(e.target.value)}
            placeholder="you@company.com"
            className="input flex-1"
          />
          <button
            type="button"
            onClick={sendEmail}
            disabled={sending}
            className="btn-primary px-5 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {sending ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Sending…
              </>
            ) : (
              'Email me the report'
            )}
          </button>
        </div>
        {emailMsg && (
          <div
            className={`mt-3 text-sm flex items-start gap-2 ${
              emailMsg.ok ? 'text-emerald-700' : 'text-amber-700'
            }`}
          >
            {emailMsg.ok ? (
              <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" />
            ) : (
              <Info className="w-4 h-4 mt-0.5 flex-shrink-0" />
            )}
            <span>{emailMsg.text}</span>
          </div>
        )}
      </div>

      {/* Contextual next-step CTA */}
      <AssessmentCta result={result} />

      <div className="text-center">
        <button type="button" onClick={onReset} className="text-sm text-gray-600 hover:text-gray-700 underline">
          Classify another system
        </button>
      </div>
    </div>
  )
}

function AssessmentCta({ result }: { result: ClassifierResult }) {
  const cta = {
    UNACCEPTABLE: {
      headline: 'This practice is likely prohibited under the EU AI Act',
      body: 'You need a compliance review before shipping. We can help you assess scope, redesign the system, or document why an exemption applies.',
      primary: { label: 'Book a compliance review', to: '/contact', icon: <Building2 className="w-5 h-5" /> },
      secondary: { label: 'See pricing', to: '/pricing' },
    },
    HIGH: {
      headline: 'Your system is high-risk - Annex IV is required',
      body: result.upgrade_message,
      primary: { label: 'Get Starter for Annex IV', to: '/pricing', icon: <FileText className="w-5 h-5" /> },
      secondary: { label: 'Product tour', to: '/product' },
    },
    LIMITED: {
      headline: 'Transparency obligations apply',
      body: result.upgrade_message,
      primary: { label: 'Get Starter to draft declarations', to: '/pricing', icon: <FileText className="w-5 h-5" /> },
      secondary: { label: 'Product tour', to: '/product' },
    },
    MINIMAL: {
      headline: 'Low AI Act burden - keep a lightweight record',
      body: result.upgrade_message,
      primary: { label: 'Start free - no card', to: '/sign-up', icon: <Sparkles className="w-5 h-5" /> },
      secondary: { label: 'See pricing', to: '/pricing' },
    },
  }[result.risk_level]

  return (
    <div className="rounded-2xl bg-gradient-brand text-brand-900 p-6 sm:p-8 relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(255,255,255,0.15),transparent_60%)]" />
      <div className="relative">
        <div className="text-xs font-bold uppercase tracking-wider text-white/80 mb-2">Next step</div>
        <h3 className="text-2xl font-bold">{cta.headline}</h3>
        <p className="mt-2 text-white/90 text-sm leading-relaxed max-w-2xl">{cta.body}</p>
        <ul className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          {result.next_steps.map((s, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-white/90">
              <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0 text-white" />
              <span>{s}</span>
            </li>
          ))}
        </ul>
        <div className="mt-6 flex flex-col sm:flex-row gap-3">
          <Show when="signed-out">
            <NavLink
              to={cta.primary.to}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-white px-6 py-3 text-base font-semibold text-gray-900 shadow-lg hover:bg-gray-50 transition-all active:scale-[0.98]"
            >
              {cta.primary.icon}
              {cta.primary.label}
              <ArrowRight className="w-4 h-4" />
            </NavLink>
          </Show>
          <Show when="signed-in">
            <NavLink
              to="/app"
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-white px-6 py-3 text-base font-semibold text-gray-900 shadow-lg hover:bg-gray-50 transition-all"
            >
              Open app
              <ArrowRight className="w-4 h-4" />
            </NavLink>
          </Show>
          <NavLink
            to={cta.secondary.to}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-white/10 backdrop-blur border border-white/20 px-6 py-3 text-base font-semibold text-white hover:bg-white/20 transition-all"
          >
            {cta.secondary.label}
          </NavLink>
        </div>
      </div>
    </div>
  )
}

const RISK_STYLES: Record<ClassifierResult['risk_level'], {
  container: string
  iconBg: string
  icon: JSX.Element
  label: string
  headline: string
}> = {
  UNACCEPTABLE: {
    container: 'border-red-300 bg-red-50',
    iconBg: 'bg-red-600 text-white',
    icon: <ShieldAlert className="w-6 h-6" />,
    label: 'text-red-700',
    headline: 'Prohibited practice likely',
  },
  HIGH: {
    container: 'border-orange-300 bg-orange-50',
    iconBg: 'bg-orange-500 text-white',
    icon: <AlertTriangle className="w-6 h-6" />,
    label: 'text-orange-700',
    headline: 'High-risk AI system',
  },
  LIMITED: {
    container: 'border-amber-300 bg-amber-50',
    iconBg: 'bg-amber-500 text-white',
    icon: <Info className="w-6 h-6" />,
    label: 'text-amber-700',
    headline: 'Transparency obligations apply',
  },
  MINIMAL: {
    container: 'border-emerald-300 bg-emerald-50',
    iconBg: 'bg-emerald-600 text-white',
    icon: <ShieldCheck className="w-6 h-6" />,
    label: 'text-emerald-700',
    headline: 'Low AI Act burden - adjacent rules still apply',
  },
}
