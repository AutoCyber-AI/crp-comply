import { useQuery } from '@tanstack/react-query'
import { Gauge } from 'lucide-react'
import { getBillingStatus } from '@/lib/api'

export function QuotaBar() {
  const { data, isLoading } = useQuery({
    queryKey: ['billing-status'],
    queryFn: getBillingStatus,
    staleTime: 300_000,
    refetchInterval: 300_000,
    refetchIntervalInBackground: false,
  })

  if (isLoading || !data) {
    return (
      <div className="rounded-md bg-surface-2 border border-hairline px-3 py-2">
        <div className="h-2 w-full rounded-full bg-surface animate-pulse" />
      </div>
    )
  }

  const pct = Math.min(100, Math.max(0, data.pct_used))
  const isWarn = pct >= 75 && pct < 100
  const isCrit = pct >= 100

  return (
    <div className="rounded-md bg-surface-2 border border-hairline px-3 py-2">
      <div className="flex items-center justify-between text-xs mb-1.5">
        <span className="flex items-center gap-1.5 font-medium text-ink-2">
          <Gauge className="h-3 w-3" />
          Calls this month
        </span>
        <span className="text-ink-3">
          {data.quota_used.toLocaleString()} / {data.quota_limit.toLocaleString()}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-surface overflow-hidden">
        <div
          className={`h-full transition-all ${
            isCrit ? 'bg-red-500' : isWarn ? 'bg-amber-500' : 'bg-emerald-500'
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {isCrit && (
        <p className="mt-1.5 text-[10px] font-medium text-red-600">
          Quota exceeded - upgrade to continue
        </p>
      )}
    </div>
  )
}
