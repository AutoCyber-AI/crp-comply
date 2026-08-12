import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { QuotaBar } from '../QuotaBar'
import { getBillingStatus } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  getBillingStatus: vi.fn(),
}))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

function Wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('QuotaBar', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('renders a compact usage bar from billing status', async () => {
    vi.mocked(getBillingStatus).mockResolvedValue({
      tier: 'pro',
      stripe_customer_id: null,
      stripe_subscription_id: null,
      subscription_status: 'active',
      cancel_at_period_end: false,
      current_period_end: null,
      renewal_date: null,
      quota_used: 250,
      quota_limit: 5000,
      remaining: 4750,
      pct_used: 5,
      overage_calls: 0,
      overage_allowed: true,
      credit_balance_usd: 0,
      action_required: false,
      action_reason: null,
    })

    render(<QuotaBar />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('250 / 5,000')).toBeInTheDocument()
    })
  })

  it('shows a warning when the quota is exceeded', async () => {
    vi.mocked(getBillingStatus).mockResolvedValue({
      tier: 'free',
      stripe_customer_id: null,
      stripe_subscription_id: null,
      subscription_status: 'active',
      cancel_at_period_end: false,
      current_period_end: null,
      renewal_date: null,
      quota_used: 100,
      quota_limit: 100,
      remaining: 0,
      pct_used: 100,
      overage_calls: 0,
      overage_allowed: false,
      credit_balance_usd: 0,
      action_required: false,
      action_reason: null,
    })

    render(<QuotaBar />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText(/Quota exceeded/i)).toBeInTheDocument()
    })
  })
})
