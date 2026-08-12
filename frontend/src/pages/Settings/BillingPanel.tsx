import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Shield,
  CreditCard,
  AlertTriangle,
  Gauge,
  ExternalLink,
  Info,
} from 'lucide-react'
import { getMe, createPortalSession } from '@/lib/api'
import { Tooltip } from '@/design/primitives'
import { useStepUp } from '@/hooks/useStepUp'
import { PasskeyStepUpModal } from '@/components/PasskeyStepUpModal'

export function BillingPanel() {
  const [portalLoading, setPortalLoading] = useState(false)
  const [portalError, setPortalError] = useState('')
  const stepUp = useStepUp({ actionName: 'Billing portal access' })
  const meQuery = useQuery({
    queryKey: ['me'],
    queryFn: getMe,
    refetchInterval: 60_000,
  })

  if (meQuery.isLoading) {
    return (
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Shield className="h-5 w-5" /> Subscription & Usage
        </h2>
        <p className="text-sm text-gray-600">Loading…</p>
      </div>
    )
  }

  if (meQuery.isError || !meQuery.data) {
    return (
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Shield className="h-5 w-5" /> Subscription & Usage
        </h2>
        <p className="text-sm text-red-600">Could not load subscription info.</p>
      </div>
    )
  }

  const me = meQuery.data as any
  const tier = (me.tier || 'free') as string
  const usage = me.usage as
    | {
        used: number
        quota: number
        remaining: number
        pct_used: number
        overage_calls: number
        blocked: boolean
        policy: string
        period: string
        resets_at: string
      }
    | null
    | undefined

  const tierBadge = TIER_DISPLAY[tier] || TIER_DISPLAY.free
  const pct = usage ? Math.min(100, usage.pct_used) : 0
  const isWarn = pct >= 75 && pct < 100
  const isCrit = pct >= 100

  const openPortal = async () => {
    setPortalError('')
    setPortalLoading(true)
    try {
      const r = await createPortalSession()
      window.location.href = r.portal_url
    } catch (e: unknown) {
      setPortalError(e instanceof Error ? e.message : 'Failed to open billing portal')
    } finally {
      setPortalLoading(false)
    }
  }

  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <Shield className="h-5 w-5" /> Subscription & Usage
      </h2>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Tier card */}
        <div className={`rounded-xl border p-5 ${tierBadge.container}`}>
          <div className="flex items-start justify-between">
            <div>
              <div className={`text-xs font-bold uppercase tracking-wider ${tierBadge.label}`}>
                Current plan
              </div>
              <div className="text-2xl font-bold text-gray-900 mt-1">{tierBadge.name}</div>
              <div className="text-xs text-gray-600 mt-1">{tierBadge.tagline}</div>
            </div>
            <div className={`rounded-full px-2.5 py-1 text-xs font-bold ${tierBadge.pill}`}>
              {tier.toUpperCase()}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <NavLink
              to="/pricing"
              className="inline-flex items-center gap-1 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-800"
            >
              <CreditCard className="w-3.5 h-3.5" />
              {tier === 'free' ? 'Upgrade' : 'Change plan'}
            </NavLink>
            {me.stripe_customer_id && (
              <button
                type="button"
                onClick={() => stepUp.requireStepUp(openPortal)}
                disabled={portalLoading}
                className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                {portalLoading ? 'Opening…' : 'Billing portal'}
              </button>
            )}
          </div>
          {portalError && (
            <div className="mt-2 text-xs text-red-600">{portalError}</div>
          )}
        </div>

        {/* Usage card */}
        <div className="rounded-xl border border-gray-200 p-5 bg-white">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Gauge className="w-4 h-4 text-gray-600" />
              <div className="text-xs font-bold uppercase tracking-wider text-gray-600">
                Audited calls this month
              </div>
              <Tooltip label="Any prompt or event scanned and signed by CRP Comply - including recipe runs, risk classifications, and SDK/gateway calls.">
                <Info className="w-3.5 h-3.5 text-gray-400 cursor-help" />
              </Tooltip>
            </div>
            {isCrit && (
              <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-bold text-red-700">
                <AlertTriangle className="w-3 h-3" />
                {usage?.policy === 'HARD_BLOCK' ? 'Blocked' : 'Overage'}
              </span>
            )}
            {isWarn && !isCrit && (
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-bold text-amber-700">
                {pct}% used
              </span>
            )}
          </div>

          <div className="mt-3 flex items-baseline gap-2">
            <div className="text-3xl font-bold text-gray-900">
              {usage ? usage.used.toLocaleString() : '-'}
            </div>
            <div className="text-sm text-gray-600">
              / {usage ? usage.quota.toLocaleString() : '-'} included
            </div>
          </div>

          {/* Progress bar */}
          <div className="mt-3 h-2 w-full rounded-full bg-gray-100 overflow-hidden">
            <div
              className={`h-full transition-all ${
                isCrit ? 'bg-red-500' : isWarn ? 'bg-amber-500' : 'bg-emerald-500'
              }`}
              style={{ width: `${pct}%` }}
            />
          </div>

          <div className="mt-3 flex items-center justify-between text-xs text-gray-600">
            <span>
              {usage ? `${usage.remaining.toLocaleString()} remaining` : ''}
            </span>
            <span>
              Resets {usage ? new Date(usage.resets_at).toLocaleDateString() : ''}
            </span>
          </div>

          {usage && usage.overage_calls > 0 && (
            <div className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-2 text-xs text-amber-800">
              <strong>{usage.overage_calls.toLocaleString()}</strong> overage calls this period.{' '}
              {usage.policy === 'SOFT_ALLOW'
                ? 'These will be billed at your tier overage rate.'
                : 'Calls are blocked until quota resets or you upgrade.'}
            </div>
          )}

          {isCrit && usage?.policy === 'HARD_BLOCK' && (
            <NavLink
              to="/pricing"
              className="mt-3 inline-flex items-center justify-center gap-1 w-full rounded-lg bg-brand-600 px-3 py-2 text-xs font-semibold text-brand-900 hover:bg-brand-500"
            >
              Upgrade to keep building
            </NavLink>
          )}
        </div>
      </div>

      <div className="mt-4 text-xs text-gray-600">
        Every audited call (risk assessment, compliance report, DPIA, transparency, technical
        documentation, session audit, evidence pack) counts toward your monthly quota.
        Public free risk classifier calls are rate-limited per IP and do not count.
      </div>
      <PasskeyStepUpModal
        open={stepUp.open}
        actionName={stepUp.actionName}
        onClose={stepUp.close}
        onVerified={stepUp.onVerified}
      />
    </div>
  )
}

const TIER_DISPLAY: Record<
  string,
  { name: string; tagline: string; container: string; label: string; pill: string }
> = {
  free: {
    name: 'Free',
    tagline: 'Prove compliance on your first call.',
    container: 'border-gray-200 bg-gradient-to-br from-gray-50 to-white',
    label: 'text-gray-600',
    pill: 'bg-gray-200 text-gray-800',
  },
  starter: {
    name: 'Starter',
    tagline: 'Ship a compliant product.',
    container: 'border-blue-200 bg-gradient-to-br from-blue-50 to-white',
    label: 'text-blue-700',
    pill: 'bg-blue-100 text-blue-800',
  },
  pro: {
    name: 'Starter',
    tagline: 'Full governance stack, audit-ready.',
    container: 'border-brand-300 bg-gradient-to-br from-brand-50 to-white ring-1 ring-brand-200',
    label: 'text-brand-800',
    pill: 'bg-brand-100 text-brand-800',
  },
  team: {
    name: 'Scale',
    tagline: 'Team governance and shared workflows.',
    container: 'border-brand-300 bg-gradient-to-br from-brand-50 to-white ring-1 ring-brand-200',
    label: 'text-brand-800',
    pill: 'bg-brand-100 text-brand-800',
  },
  scale: {
    name: 'Scale',
    tagline: 'Team governance and shared workflows.',
    container: 'border-brand-300 bg-gradient-to-br from-brand-50 to-white ring-1 ring-brand-200',
    label: 'text-brand-800',
    pill: 'bg-brand-100 text-brand-800',
  },
  enterprise: {
    name: 'Enterprise',
    tagline: 'Enterprise-grade, shared tenancy.',
    container: 'border-violet-300 bg-gradient-to-br from-violet-50 to-white',
    label: 'text-violet-700',
    pill: 'bg-violet-100 text-violet-800',
  },
  cloud: {
    name: 'Cloud',
    tagline: 'Dedicated cloud or on-prem.',
    container: 'border-amber-300 bg-gradient-to-br from-amber-50 to-orange-50',
    label: 'text-amber-700',
    pill: 'bg-amber-100 text-amber-800',
  },
}
