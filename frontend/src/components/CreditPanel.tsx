/**
 * CreditPanel - prepaid credit balance + buy-pack buttons.
 *
 * Shows the user's current $ balance (welcome bonus + any past purchases),
 * recent ledger entries, and three Stripe-hosted top-up buttons. Mounted
 * inside Settings at #credits and inside the 402 quota-exhausted modal.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Coins, Loader2, Plus, ExternalLink, Sparkles } from 'lucide-react'

import {
  getCreditsBalance,
  createCreditsCheckout,
  type CreditBalance,
} from '@/lib/api'

const PACKS = [
  { label: '$5', envAlias: 'STRIPE_COMPLY_CREDITS_5_PRICE_ID', usd: 5, calls: 100 },
  { label: '$20', envAlias: 'STRIPE_COMPLY_CREDITS_20_PRICE_ID', usd: 20, calls: 400, recommended: true },
  { label: '$50', envAlias: 'STRIPE_COMPLY_CREDITS_50_PRICE_ID', usd: 50, calls: 1000 },
]

export function CreditPanel({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient()
  const [pendingAlias, setPendingAlias] = useState<string | null>(null)

  const balanceQ = useQuery({
    queryKey: ['credits-balance'],
    queryFn: getCreditsBalance,
    refetchInterval: 60_000,
  })

  const checkout = useMutation({
    mutationFn: (alias: string) => createCreditsCheckout(alias),
    onSuccess: (data) => {
      if (data?.checkout_url) {
        window.location.href = data.checkout_url
      } else {
        qc.invalidateQueries({ queryKey: ['credits-balance'] })
      }
    },
    onSettled: () => setPendingAlias(null),
  })

  const balance: CreditBalance | undefined = balanceQ.data
  const lowBalance = balance ? balance.balance_usd < 1 : false

  return (
    <div id="credits" className={compact ? '' : 'card scroll-mt-20'}>
      {!compact && (
        <div className="mb-4 flex items-start gap-3">
          <Coins className="mt-0.5 h-5 w-5 text-amber-600" />
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Prepaid hosted-LLM credits
            </h2>
            <p className="mt-1 max-w-2xl text-sm text-gray-600">
              When you exceed your monthly tier quota, the platform draws
              from your prepaid balance instead of blocking you. Every
              new account gets a $5 welcome bonus (~100 hosted calls) so
              you can experience the full agent before bringing your own
              key.
            </p>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
        <div className="flex items-baseline justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-amber-700">
            Current balance
          </span>
          {balance?.lifetime_usd ? (
            <span className="text-xs text-amber-700/80">
              Lifetime ${balance.lifetime_usd.toFixed(2)}
            </span>
          ) : null}
        </div>
        <div className="mt-1 flex items-center gap-2">
          {balanceQ.isLoading ? (
            <Loader2 className="h-5 w-5 animate-spin text-amber-700" />
          ) : (
            <>
              <span className="text-3xl font-bold text-amber-900">
                ${(balance?.balance_usd ?? 0).toFixed(2)}
              </span>
              {lowBalance && balance && balance.lifetime_usd > 0 ? (
                <span className="rounded-full bg-amber-200 px-2 py-0.5 text-xs font-semibold uppercase tracking-wider text-amber-900">
                  Low
                </span>
              ) : null}
              {balance && balance.lifetime_usd === 0 ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold uppercase tracking-wider text-emerald-800">
                  <Sparkles className="h-3 w-3" />
                  Welcome bonus loading
                </span>
              ) : null}
            </>
          )}
        </div>
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-600">
          Top up
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {PACKS.map((p) => {
            const busy = pendingAlias === p.envAlias && checkout.isPending
            return (
              <button
                type="button"
                key={p.envAlias}
                onClick={() => {
                  setPendingAlias(p.envAlias)
                  checkout.mutate(p.envAlias)
                }}
                disabled={checkout.isPending}
                className={
                  p.recommended
                    ? 'group flex flex-col items-start gap-1 rounded-lg border-2 border-brand-600 bg-white p-3 text-left hover:bg-brand-50 disabled:opacity-50'
                    : 'group flex flex-col items-start gap-1 rounded-lg border border-gray-200 bg-white p-3 text-left hover:border-gray-300 disabled:opacity-50'
                }
              >
                <span className="flex w-full items-center justify-between">
                  <span className="text-base font-bold text-gray-900">{p.label}</span>
                  {p.recommended && (
                    <span className="rounded-full bg-brand-600 px-1.5 py-0.5 text-xs font-bold uppercase tracking-wider text-brand-900">
                      Best value
                    </span>
                  )}
                </span>
                <span className="text-xs text-gray-600">~{p.calls} hosted calls</span>
                <span className="mt-1 inline-flex items-center gap-1 text-sm font-medium text-brand-800 group-hover:underline">
                  {busy ? (
                    <>
                      <Loader2 className="h-3 w-3 animate-spin" /> Redirecting…
                    </>
                  ) : (
                    <>
                      <Plus className="h-3 w-3" /> Buy
                    </>
                  )}
                </span>
              </button>
            )
          })}
        </div>
        {checkout.isError && (
          <p className="mt-2 text-xs text-red-700">
            Could not start checkout: {(checkout.error as Error)?.message}
          </p>
        )}
        <p className="mt-2 text-sm text-gray-600">
          Stripe-hosted, one-time payment. Funds never expire. Refunds via{' '}
          <a
            href="mailto:billing@crprotocol.io"
            className="underline hover:text-gray-700"
          >
            billing@crprotocol.io
          </a>
          <ExternalLink className="ml-0.5 inline h-3 w-3" />.
        </p>
      </div>
    </div>
  )
}

export default CreditPanel
