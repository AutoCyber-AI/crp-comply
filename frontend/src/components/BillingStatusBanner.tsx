import { useQuery } from '@tanstack/react-query'
import { NavLink } from 'react-router-dom'
import { AlertTriangle, AlertCircle, CalendarClock, CreditCard } from 'lucide-react'
import clsx from 'clsx'
import { getBillingStatus } from '@/lib/api'

export function BillingStatusBanner() {
  const { data, isLoading } = useQuery({
    queryKey: ['billing-status'],
    queryFn: getBillingStatus,
    staleTime: 300_000,
    refetchInterval: 300_000,
    refetchIntervalInBackground: false,
  })

  if (isLoading || !data) return null
  if (!data.action_required && !data.cancel_at_period_end) return null

  let icon = <AlertCircle className="h-4 w-4" aria-hidden="true" />
  let message = ''
  const cta = 'Manage billing'
  let tone: 'amber' | 'red' | 'blue' = 'amber'

  if (data.subscription_status === 'past_due' || data.action_reason === 'past_due') {
    icon = <AlertTriangle className="h-4 w-4" aria-hidden="true" />
    message = 'Your subscription payment failed. Please update your payment method.'
    tone = 'red'
  } else if (data.cancel_at_period_end) {
    icon = <CalendarClock className="h-4 w-4" aria-hidden="true" />
    message = `Your subscription ends on ${new Date(data.current_period_end || '').toLocaleDateString()}.`
    tone = 'blue'
  } else if (data.action_reason === 'quota_exceeded') {
    icon = <AlertTriangle className="h-4 w-4" aria-hidden="true" />
    message = 'You have exceeded your monthly call quota.'
    tone = 'red'
  } else {
    message = 'Your billing account needs attention.'
  }

  const styles = {
    amber: 'bg-amber-50 text-amber-900 border-amber-200',
    red: 'bg-red-50 text-red-900 border-red-200',
    blue: 'bg-blue-50 text-blue-900 border-blue-200',
  }[tone]

  return (
    <div className={clsx('border-b px-4 py-2.5', styles)} role="status" aria-live="polite">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm">
          {icon}
          <span>{message}</span>
        </div>
        <NavLink
          to="/app/settings#billing"
          className="inline-flex items-center gap-1 rounded-md bg-white/60 hover:bg-white px-2 py-1 text-xs font-semibold border border-current/20 shrink-0"
        >
          <CreditCard className="h-3 w-3" aria-hidden="true" />
          {cta}
        </NavLink>
      </div>
    </div>
  )
}
