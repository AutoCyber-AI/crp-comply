import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { BillingStatusBanner } from '../BillingStatusBanner'
import { getBillingStatus } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  getBillingStatus: vi.fn(),
}))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </MemoryRouter>
  )
}

const baseStatus = {
  tier: 'pro',
  stripe_customer_id: 'cus_123',
  stripe_subscription_id: 'sub_123',
  subscription_status: 'active',
  cancel_at_period_end: false,
  current_period_end: '2026-07-01T00:00:00Z',
  renewal_date: null,
  quota_used: 0,
  quota_limit: 5000,
  remaining: 5000,
  pct_used: 0,
  overage_calls: 0,
  overage_allowed: true,
  credit_balance_usd: 0,
  action_required: false,
  action_reason: null,
}

describe('BillingStatusBanner', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('is hidden when no billing action is required', async () => {
    vi.mocked(getBillingStatus).mockResolvedValue(baseStatus)
    render(<BillingStatusBanner />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(getBillingStatus).toHaveBeenCalled()
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows a past-due warning', async () => {
    vi.mocked(getBillingStatus).mockResolvedValue({
      ...baseStatus,
      subscription_status: 'past_due',
      action_required: true,
      action_reason: 'past_due',
    })
    render(<BillingStatusBanner />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText(/payment failed/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: /manage billing/i })).toHaveAttribute(
      'href',
      '/app/settings#billing',
    )
  })

  it('shows a cancellation notice', async () => {
    vi.mocked(getBillingStatus).mockResolvedValue({
      ...baseStatus,
      cancel_at_period_end: true,
      current_period_end: '2026-07-15T00:00:00Z',
    })
    render(<BillingStatusBanner />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText(/subscription ends/i)).toBeInTheDocument()
    })
  })
})
