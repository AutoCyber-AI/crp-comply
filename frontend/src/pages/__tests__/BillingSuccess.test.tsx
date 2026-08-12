import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import BillingSuccess from '../BillingSuccess'
import { getBillingStatus } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  getBillingStatus: vi.fn(),
}))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MemoryRouter initialEntries={['/billing/success?session_id=cs_123']}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route path="/billing/success" element={children} />
          <Route path="/app/settings" element={<div>Billing settings</div>} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>
  )
}

const activeStatus = {
  tier: 'pro',
  stripe_customer_id: 'cus_123',
  stripe_subscription_id: 'sub_123',
  subscription_status: 'active',
  cancel_at_period_end: false,
  current_period_end: null,
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

describe('BillingSuccess', () => {
  beforeEach(() => {
    queryClient.clear()
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  it('renders a confirming state while polling', async () => {
    vi.mocked(getBillingStatus).mockResolvedValue({
      ...activeStatus,
      subscription_status: 'incomplete',
      action_required: true,
    })
    render(<BillingSuccess />, { wrapper: Wrapper })
    expect(screen.getByText(/Confirming subscription/i)).toBeInTheDocument()
  })

  it('shows success and redirects once the subscription is active', async () => {
    vi.mocked(getBillingStatus).mockResolvedValue(activeStatus)
    render(<BillingSuccess />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText(/Subscription active/i)).toBeInTheDocument()
    })
    // Advance the 2.5s auto-redirect timer.
    vi.advanceTimersByTime(3_000)
    await waitFor(() => {
      expect(screen.getByText(/Billing settings/i)).toBeInTheDocument()
    })
  })
})
