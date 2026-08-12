import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Show, useAuth } from '@clerk/react'
import {
  Check,
  Zap,
  Building2,
  Sparkles,
  Shield,
  ExternalLink,
  Info,
} from 'lucide-react'
import { createCheckoutSession, createPortalSession } from '../lib/api'

type Tier = {
  id: string
  name: string
  price: string
  priceAnnual?: string
  period: string
  periodAnnual?: string
  tagline: string
  audience: string
  priceEnv?: string
  priceEnvAnnual?: string
  contactSales?: boolean
  included: string
  overage: string
  highlight?: boolean
  features: string[]
  integrations: string[]
  icon: React.ComponentType<{ className?: string }>
}

type BillingPeriod = 'monthly' | 'annual'

const TIERS: Tier[] = [
  {
    id: 'free',
    name: 'Free',
    price: '$0',
    period: 'forever',
    tagline: 'Prove your controls operate on the first call.',
    audience: 'Solo builders & prototypes',
    included: '100 audited calls/month',
    overage: 'Calls above quota are blocked',
    icon: Sparkles,
    features: [
      '100 audited calls/month',
      'EU AI Act risk classifier',
      'Streaming compliance assistant',
      'Browse all 36 recipes',
      'Local LLM by default - $0 / call (Ollama, LM Studio)',
      'Bring your own key (OpenAI / Anthropic) optional',
      'Passkey-secured login',
      'Tamper-evident audit log',
      'Community support',
    ],
    integrations: ['Gateway API', 'Python SDK'],
  },
  {
    id: 'starter',
    name: 'Starter',
    price: '$49',
    priceAnnual: '$490',
    period: '/month',
    periodAnnual: '/year',
    tagline: 'Ship AI that is evidence-ready.',
    audience: 'Small teams & indie SaaS',
    priceEnv: 'STRIPE_COMPLY_STARTER_PRICE_ID',
    included: '5,000 audited calls/month',
    overage: '$0.01 per extra call',
    icon: Zap,
    features: [
      'Everything in Free',
      '5,000 audited calls/month',
      'Run all 36 recipes',
      'Full Annex IV drafts',
      'DPIA generation (GDPR Art. 35)',
      'Transparency declarations (Art. 13)',
      'Technical documentation (Art. 11)',
      'Hosted vault for artefacts',
      'Evidence pack export',
      'Scan remediation PRs',
      'Quality grading (S/A/B/C/D)',
      'PDF export with your branding',
      'Right to erasure (GDPR Art. 17)',
      'Email support',
    ],
    integrations: ['Gateway API', 'Python SDK', 'Webhook audits'],
  },
  {
    id: 'scale',
    name: 'Scale',
    price: '$499',
    priceAnnual: '$4,990',
    period: '/month',
    periodAnnual: '/year',
    tagline: 'Continuous evidence for any standard.',
    audience: 'Growing teams & regulated companies',
    priceEnv: 'STRIPE_COMPLY_SCALE_PRICE_ID',
    included: '50,000 audited calls/month',
    overage: '$0.005 per extra call',
    highlight: true,
    icon: Shield,
    features: [
      'Everything in Starter',
      '50,000 audited calls/month',
      'Continuous compliance engine',
      'No-Code Governance scanner',
      'Safety Control Plane',
      'Business Impact Assessment',
      'Auto-remediation PRs',
      'SSO / SAML',
      'Data residency controls',
      'Hosted LLM option',
      'Streaming compliance assistant',
      'GDPR Art. 30 processing records',
      'Custom compliance frameworks',
      'Priority email + chat support + 99.9% SLA',
      'Team seats (fair use)',
    ],
    integrations: ['Gateway API', 'Python SDK', 'Webhook audits', 'LM Studio / Ollama connector'],
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    price: 'Custom',
    period: '',
    tagline: 'Dedicated tenancy. Your data plane.',
    audience: 'Banks, healthcare, public sector',
    contactSales: true,
    included: 'Custom call quota (fair use)',
    overage: 'Annual contract',
    icon: Building2,
    features: [
      'Everything in Scale',
      'Dedicated cloud or on-prem deployment',
      'Private LLM routing (air-gapped capable)',
      'Named compliance success manager',
      'GDPR Art. 17 erasure request tracking + audit chain',
      'Retention policy enforcement (advisory + alerting)',
      'Regulatory export (JSON/CSV) + automated delivery',
      'On-call incident response',
      '7-year audit retention',
      'Custom integrations',
      'Signed DPA; ISO 27001 / SOC 2 audit-context evidence on request',
      '99.95% SLA'
    ],
    integrations: ['All integrations', 'Private cloud LLM routing', 'Signed regulator certificates', 'Bespoke'],
  },
]

export default function Pricing() {
  const [loading, setLoading] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [period, setPeriod] = useState<BillingPeriod>('monthly')
  const { isSignedIn } = useAuth()

  const handleUpgrade = async (tier: Tier) => {
    if (tier.contactSales) {
      window.location.href = 'mailto:sales@crprotocol.io?subject=CRP%20Comply%20Enterprise'
      return
    }
    const priceId = period === 'annual' && tier.priceEnvAnnual
      ? tier.priceEnvAnnual
      : tier.priceEnv
    if (!priceId) return
    if (!isSignedIn) return
    setError('')
    setLoading(tier.id)
    try {
      const res = await createCheckoutSession(priceId)
      window.location.href = res.checkout_url
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start checkout')
    } finally {
      setLoading(null)
    }
  }

  const handleManage = async () => {
    setError('')
    setLoading('manage')
    try {
      const res = await createPortalSession()
      window.location.href = res.portal_url
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to open billing portal')
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="py-12 sm:py-16">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 bg-brand-50 border border-brand-200 rounded-full px-3 py-1 text-xs text-brand-800 font-semibold mb-4">
            <Shield size={12} />
            Usage-based pricing · Cancel anytime
          </div>
          <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-gray-900">
            Pay for proof, not for seats.
          </h1>
          <p className="mt-4 text-lg text-gray-600 max-w-2xl mx-auto">
            Every tier includes the Recipe Library, the Deliverable Vault, and passkey-secured login.
            Pay only for the audited calls you consume through the gateway, SDK, or LM Studio connector.
            That's how we keep you evidence-ready for EU AI Act, AIUC-1, ISO 42001, NIST AI RMF and GDPR
            audits without seat-based gotchas.
          </p>
        </div>

        {error && (
          <div className="mb-6 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 text-center max-w-2xl mx-auto">
            {error}
          </div>
        )}

        {/* Billing period toggle */}
        <div className="mb-8 flex items-center justify-center gap-3">
          <span className={`text-sm font-medium ${period === 'monthly' ? 'text-gray-900' : 'text-gray-600'}`}>
            Monthly
          </span>
          <button
            type="button"
            onClick={() => setPeriod(period === 'monthly' ? 'annual' : 'monthly')}
            className="relative inline-flex h-6 w-11 items-center rounded-full bg-gray-200 transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2"
            aria-label="Toggle annual billing"
            role="switch"
            aria-checked={period === 'annual'}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                period === 'annual' ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
          <span className={`text-sm font-medium ${period === 'annual' ? 'text-gray-900' : 'text-gray-600'}`}>
            Annual
          </span>
          {period === 'annual' && (
            <span className="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
              Save ~17%
            </span>
          )}
        </div>

        {/* Three-lane positioning - Readiness / Operational / Managed.
            Matches the posture model in COMPLIANCE_MODEL_ANALYSIS §9:
            tiers are rungs on a ladder, not isolated SKUs. */}
        <div className="mb-8 grid grid-cols-1 md:grid-cols-3 gap-3 max-w-5xl mx-auto">
          <LaneCard
            label="Readiness"
            tiers="Free · Starter"
            body="Understand your obligations, draft first-pass policies, wire the gateway for a prototype."
          />
          <LaneCard
            label="Operational"
            tiers="Scale"
            body="Live evidence from production traffic, full deliverable set, LLM-powered tailoring, shared-tenant controls."
            highlight
          />
          <LaneCard
            label="Managed"
            tiers="Enterprise"
            body="Dedicated tenancy, SSO, private LLM routing, named compliance contact. For regulated operators."
          />
        </div>

        <div className="mb-6 max-w-5xl mx-auto rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-white p-5 flex flex-col md:flex-row md:items-center gap-4">
          <div className="flex-1">
            <div className="text-xs font-semibold uppercase tracking-wider text-emerald-700">
              Free trial - no card, no key
            </div>
            <div className="text-base font-semibold text-gray-900 mt-1">
              Free forever: 100 audited calls/mo. New accounts also get a one-time $5 hosted-LLM credit.
            </div>
            <p className="text-sm text-gray-600 mt-1 max-w-2xl">
              Run the EU AI Act risk classifier, chat with the streaming compliance assistant,
              and produce a tamper-evident audit report on real data - all before you pick a
              tier or wire up a key. Starter unlocks full recipe runs such as Annex IV and DPIA.
              No card required.
            </p>
          </div>
          <NavLink to="/sign-up" className="btn-primary text-sm whitespace-nowrap">
            Start free trial →
          </NavLink>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          {TIERS.map((tier) => (
            <TierCard
              key={tier.id}
              tier={tier}
              isSignedIn={!!isSignedIn}
              loading={loading === tier.id}
              onUpgrade={() => handleUpgrade(tier)}
              period={period}
            />
          ))}
        </div>

        <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-6">
          <Show when="signed-in">
            <button
              type="button"
              onClick={handleManage}
              disabled={loading === 'manage'}
              className="inline-flex items-center gap-2 text-sm text-brand-800 hover:text-brand-800 font-medium"
            >
              <ExternalLink size={14} />
              {loading === 'manage' ? 'Opening...' : 'Manage existing subscription'}
            </button>
          </Show>
          <div className="inline-flex items-center gap-2 text-xs text-gray-600">
            <Info size={12} />
            Prices in USD. VAT added at checkout for EU customers.
          </div>
        </div>

        <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-4">
          <InfoBlock
            title="Why usage-based?"
            body="EU AI Act fines scale with risk exposure, not seat count. A 50-call prototype and a 500K-call production system have very different compliance needs. You pay for the proof you actually consume."
          />
          <InfoBlock
            title="Local LLM by default"
            body="Every tier runs on a local LLM (Ollama / LM Studio) at $0 marginal cost - a 16 GB laptop is enough. Bring an OpenAI / Anthropic key if you prefer; buy hosted credit packs ($5 / $20 / $50) if you want speed without setup. Same audit chain, same artefacts, regardless of runtime."
          />
          <InfoBlock
            title="Every integration is metered"
            body="Gateway API, Python SDK, and the LM Studio connector all post audit records to your CRP Comply tenant. One quota, one source of truth for regulators."
          />
        </div>
      </div>
    </div>
  )
}

function TierCard({
  tier,
  isSignedIn,
  loading,
  onUpgrade,
  period,
}: {
  tier: Tier
  isSignedIn: boolean
  loading: boolean
  onUpgrade: () => void
  period: BillingPeriod
}) {
  const Icon = tier.icon
  const displayPrice = period === 'annual' && tier.priceAnnual ? tier.priceAnnual : tier.price
  const displayPeriod = period === 'annual' && tier.periodAnnual ? tier.periodAnnual : tier.period
  return (
    <div
      className={`relative rounded-2xl border p-5 flex flex-col bg-white ${
        tier.highlight
          ? 'border-brand-500 ring-2 ring-brand-200 shadow-xl shadow-brand-100/50'
          : 'border-gray-200 shadow-sm'
      }`}
    >
      {tier.highlight && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2">
          <div className="rounded-full bg-gradient-brand px-3 py-1 text-xs font-bold text-brand-900 shadow-md">
            Most popular
          </div>
        </div>
      )}
      <div className="flex items-center gap-2 mb-2">
        <Icon className={`h-4 w-4 ${tier.highlight ? 'text-brand-800' : 'text-gray-600'}`} />
        <h2 className="text-base font-semibold text-gray-900">{tier.name}</h2>
      </div>
      <div className="mb-1">
        <span className="text-3xl font-bold text-gray-900">{displayPrice}</span>
        <span className="text-sm text-gray-600">{displayPeriod}</span>
      </div>
      <p className="text-xs font-medium text-brand-800 mb-2">{tier.tagline}</p>
      <p className="text-xs text-gray-600 mb-4">{tier.audience}</p>

      <div className="rounded-lg bg-gray-50 border border-gray-100 p-3 mb-4">
        <div className="text-xs font-semibold text-gray-900">{tier.included}</div>
        <div className="text-xs text-gray-600 mt-0.5">{tier.overage}</div>
      </div>

      <ul className="space-y-1.5 mb-4 flex-1">
        {tier.features.map((f) => (
          <li key={f} className="flex items-start gap-1.5 text-xs text-gray-700 leading-snug">
            <Check className="h-3.5 w-3.5 text-emerald-500 mt-0.5 shrink-0" />
            {f}
          </li>
        ))}
      </ul>

      <div className="mb-4">
        <div className="text-xs font-bold uppercase tracking-wider text-gray-600 mb-1.5">
          Integrations
        </div>
        <div className="flex flex-wrap gap-1">
          {tier.integrations.map((i) => (
            <span
              key={i}
              className="inline-block rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-900"
            >
              {i}
            </span>
          ))}
        </div>
      </div>

      {tier.id === 'free' ? (
        <>
          <Show when="signed-out">
            <NavLink
              to="/sign-up"
              className="block w-full text-center py-2 rounded-lg text-sm font-semibold bg-gray-900 text-white hover:bg-gray-800"
            >
              Get started free
            </NavLink>
          </Show>
          <Show when="signed-in">
            <NavLink
              to="/app"
              className="w-full text-center py-2 rounded-lg text-sm font-semibold bg-gray-900 text-white hover:bg-gray-800"
            >
              Open app
            </NavLink>
          </Show>
        </>
      ) : tier.contactSales ? (
        <button
          type="button"
          onClick={onUpgrade}
          className="w-full py-2 rounded-lg text-sm font-semibold bg-gray-900 text-white hover:bg-gray-800"
        >
          Talk to sales
        </button>
      ) : isSignedIn ? (
        <button
          type="button"
          onClick={onUpgrade}
          disabled={loading}
          className={`w-full py-2 rounded-lg text-sm font-semibold disabled:opacity-50 ${
            tier.highlight
              ? 'bg-brand-600 text-brand-900 hover:bg-brand-500'
              : 'bg-gray-900 text-white hover:bg-gray-800'
          }`}
        >
          {loading ? 'Redirecting...' : `Upgrade to ${tier.name}`}
        </button>
      ) : (
        <NavLink
          to="/sign-up"
          className={`block w-full text-center py-2 rounded-lg text-sm font-semibold ${
            tier.highlight
              ? 'bg-brand-600 text-brand-900 hover:bg-brand-500'
              : 'bg-gray-900 text-white hover:bg-gray-800'
          }`}
        >
          Get {tier.name}
        </NavLink>
      )}
    </div>
  )
}

function InfoBlock({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <h3 className="text-sm font-semibold text-gray-900 mb-1.5">{title}</h3>
      <p className="text-xs text-gray-600 leading-relaxed">{body}</p>
    </div>
  )
}

/**
 * Lane card - summarises one of the three compliance postures
 * (Readiness / Operational / Managed) that the tier ladder serves.
 * Sits above the per-tier grid so users can self-select the band
 * they belong in before scanning individual SKUs.
 */
function LaneCard({
  label,
  tiers,
  body,
  highlight = false,
}: { label: string; tiers: string; body: string; highlight?: boolean }) {
  return (
    <div
      className={
        'rounded-xl border p-4 ' +
        (highlight
          ? 'border-brand-300 bg-brand-50'
          : 'border-gray-200 bg-white')
      }
    >
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900">{label}</h3>
        <span className="text-xs text-gray-600 font-medium">{tiers}</span>
      </div>
      <p className="text-xs text-gray-600 leading-relaxed mt-1.5">{body}</p>
    </div>
  )
}
