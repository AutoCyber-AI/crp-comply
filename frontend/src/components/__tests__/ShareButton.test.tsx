import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ShareButton } from '../ShareButton'
import * as api from '@/lib/api'
import * as clipboard from '@/lib/clipboard'
import { ToastProvider } from '../toast/ToastProvider'

vi.mock('@/lib/api', () => ({
  createShare: vi.fn(),
  listShares: vi.fn(),
  revokeShare: vi.fn(),
}))

vi.mock('@/lib/clipboard', () => ({
  copyToClipboard: vi.fn(),
}))

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>
}

beforeEach(() => {
  vi.resetAllMocks()
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { origin: 'https://test.example' },
  })
  vi.mocked(api.listShares).mockResolvedValue({ shares: [] })
})

describe('ShareButton', () => {
  it('opens the share dialog when clicked', async () => {
    render(<ShareButton resourceType="report" resourceId="report-123" />, { wrapper: Wrapper })

    const button = screen.getByRole('button', { name: /share/i })
    await userEvent.click(button)

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/share report/i)).toBeInTheDocument()
  })

  it('creates a share and copies the public URL', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createShare).mockResolvedValue({
      share_id: 'share-abc',
      tenant_id: 'tenant-1',
      created_by: 'user-1',
      resource_type: 'report',
      resource_id: 'report-123',
      recipient_email: null,
      created_at: '2026-01-01T00:00:00Z',
      expires_at: '2026-01-08T00:00:00Z',
    })
    vi.mocked(clipboard.copyToClipboard).mockResolvedValue(true)

    render(<ShareButton resourceType="report" resourceId="report-123" />, { wrapper: Wrapper })

    await user.click(screen.getByRole('button', { name: /share/i }))
    await user.click(screen.getByRole('button', { name: /create share link/i }))

    await waitFor(() => expect(api.createShare).toHaveBeenCalledTimes(1))
    expect(api.createShare).toHaveBeenCalledWith({
      report_id: 'report-123',
      recipient_email: undefined,
      expires_in_days: 7,
    })
    await waitFor(() =>
      expect(clipboard.copyToClipboard).toHaveBeenCalledWith(
        'https://test.example/api/v1/shares/share-abc/public',
      ),
    )
  })

  it('lists existing shares for the resource', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listShares).mockResolvedValue({
      shares: [
        {
          share_id: 'share-existing',
          tenant_id: 'tenant-1',
          created_by: 'user-1',
          resource_type: 'report',
          resource_id: 'report-123',
          recipient_email: 'auditor@example.com',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: '2026-01-08T00:00:00Z',
        },
      ],
    })

    render(<ShareButton resourceType="report" resourceId="report-123" />, { wrapper: Wrapper })

    await user.click(screen.getByRole('button', { name: /share/i }))

    await waitFor(() => {
      expect(screen.getByText(/auditor@example.com/i)).toBeInTheDocument()
    })
  })

  it('revokes a share when the trash button is clicked', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listShares).mockResolvedValue({
      shares: [
        {
          share_id: 'share-to-revoke',
          tenant_id: 'tenant-1',
          created_by: 'user-1',
          resource_type: 'report',
          resource_id: 'report-123',
          recipient_email: null,
          created_at: '2026-01-01T00:00:00Z',
          expires_at: '2026-01-08T00:00:00Z',
        },
      ],
    })
    vi.mocked(api.revokeShare).mockResolvedValue({ revoked: true, share_id: 'share-to-revoke' })

    render(<ShareButton resourceType="report" resourceId="report-123" />, { wrapper: Wrapper })

    await user.click(screen.getByRole('button', { name: /share/i }))
    const revokeButton = await screen.findByRole('button', { name: /revoke share/i })
    await user.click(revokeButton)

    await waitFor(() => expect(api.revokeShare).toHaveBeenCalledWith('share-to-revoke'))
  })
})
