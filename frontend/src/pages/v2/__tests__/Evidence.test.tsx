import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Evidence from '../Evidence'
import { getDashboardStats, getAuditLog } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  getDashboardStats: vi.fn(),
  getAuditLog: vi.fn(),
}))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

function Wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

const events = [
  {
    event_id: 'evt_1',
    event_type: 'report_generated',
    timestamp: new Date().toISOString(),
    description: 'DPIA report generated',
    source: 'recipe',
    signature: 'signed_blob_1',
  },
  {
    event_id: 'evt_2',
    event_type: 'artefact_uploaded',
    timestamp: new Date().toISOString(),
    description: 'Model card uploaded',
    source: 'artefacts',
    signature: null,
  },
]

beforeEach(() => {
  queryClient.clear()
  vi.mocked(getDashboardStats).mockResolvedValue({
    user_id: 'user_123',
    tier: 'pro',
    total_requests: 1205,
    pii_detections: 3,
    injection_attempts: 0,
    compliance_rate: 99.7,
    models_used: {},
    risk_distribution: {},
    quality_distribution: {},
    consent_coverage: 0,
    retention_tracked: 0,
    lineage_tracked: 0,
  })
  vi.mocked(getAuditLog).mockResolvedValue({ events })
})

describe('Evidence audit timeline', () => {
  it('renders audit-log events with a verified indicator', async () => {
    render(<Evidence />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('DPIA report generated')).toBeInTheDocument()
    })
    expect(screen.getByText('Model card uploaded')).toBeInTheDocument()
    expect(screen.getByText('recipe')).toBeInTheDocument()
    expect(screen.getByText('artefacts')).toBeInTheDocument()
    expect(screen.getByText(/Verified/i)).toBeInTheDocument()
  })
})
