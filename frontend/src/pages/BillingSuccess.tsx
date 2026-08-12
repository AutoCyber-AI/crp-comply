import { useEffect, useMemo, useState } from 'react'
import { useSearchParams, useNavigate, NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Loader2, AlertCircle } from 'lucide-react'
import { getBillingStatus } from '@/lib/api'

const POLL_INTERVAL_MS = 2_500
const TIMEOUT_MS = 60_000

export default function BillingSuccess() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const sessionId = searchParams.get('session_id')
  const [startedAt] = useState(() => Date.now())

  const { data, error } = useQuery({
    queryKey: ['billing-status', sessionId],
    queryFn: getBillingStatus,
    refetchInterval: POLL_INTERVAL_MS,
    retry: 3,
  })

  const active = useMemo(() => {
    if (!data) return false
    return data.subscription_status === 'active' && !data.action_required
  }, [data])

  const timedOut = useMemo(() => {
    return !active && Date.now() - startedAt > TIMEOUT_MS
  }, [active, startedAt])

  useEffect(() => {
    if (active) {
      const timer = window.setTimeout(() => {
        navigate('/app/settings#billing', { replace: true })
      }, 2_500)
      return () => window.clearTimeout(timer)
    }
  }, [active, navigate])

  return (
    <div className="min-h-screen bg-surface-2 flex items-center justify-center p-6">
      <div className="w-full max-w-md card text-center space-y-4">
        {active ? (
          <>
            <CheckCircle2 className="h-12 w-12 text-emerald-500 mx-auto" aria-hidden="true" />
            <h1 className="text-xl font-semibold text-ink">Subscription active</h1>
            <p className="text-sm text-ink-3">
              Welcome to the <span className="font-medium text-ink">{data?.tier}</span> plan. Redirecting you to billing settings…
            </p>
          </>
        ) : timedOut || error ? (
          <>
            <AlertCircle className="h-12 w-12 text-amber-500 mx-auto" aria-hidden="true" />
            <h1 className="text-xl font-semibold text-ink">Still processing</h1>
            <p className="text-sm text-ink-3">
              We are waiting for Stripe to confirm your subscription. You can close this page; your billing settings will update automatically.
            </p>
            <NavLink
              to="/app/settings#billing"
              className="inline-flex items-center justify-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800"
            >
              Go to billing settings
            </NavLink>
          </>
        ) : (
          <>
            <Loader2 className="h-12 w-12 text-primary mx-auto animate-spin" aria-hidden="true" />
            <h1 className="text-xl font-semibold text-ink">Confirming subscription…</h1>
            <p className="text-sm text-ink-3">
              Please wait while we sync your new plan with Stripe.
            </p>
          </>
        )}

        {sessionId && (
          <p className="text-[10px] text-ink-4 font-mono">Session {sessionId}</p>
        )}
      </div>
    </div>
  )
}
