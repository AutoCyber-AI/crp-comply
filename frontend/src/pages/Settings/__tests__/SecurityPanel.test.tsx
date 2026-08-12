import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { SecurityPanel } from '../SecurityPanel'
import { listSessions, revokeSession, revokeOtherSessions, createSession } from '@/lib/api'
import { ToastProvider } from '@/components/toast/ToastProvider'

vi.mock('@/lib/api', () => ({
  createSession: vi.fn(),
  listSessions: vi.fn(),
  revokeSession: vi.fn(),
  revokeOtherSessions: vi.fn(),
}))

function Wrapper() {
  return (
    <ToastProvider>
      <SecurityPanel />
    </ToastProvider>
  )
}

const sessionBase = {
  user_id: 'user_1',
  tenant_id: 'tenant_1',
  ip_hash: 'ip',
  ua_hash: 'ua',
  created_at: 1700000000,
}

describe('SecurityPanel', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(createSession).mockResolvedValue({ session_id: 'sess_new', created_at: 1700000000, expires_in_seconds: 86400 })
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        { ...sessionBase, session_id: 'sess_a', current: true, last_seen_at: 1700000100 },
        { ...sessionBase, session_id: 'sess_b', current: false, last_seen_at: 1700000000 },
      ],
      count: 2,
    })
    vi.mocked(revokeSession).mockResolvedValue({ status: 'revoked', session_id: 'sess_b' })
    vi.mocked(revokeOtherSessions).mockResolvedValue({ status: 'revoked', removed: 1 })
  })

  it('loads and renders active sessions', async () => {
    render(<Wrapper />)
    await waitFor(() => {
      expect(screen.getByText('This device')).toBeInTheDocument()
    })
    expect(screen.getByText(/sess_b/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Sign out all other devices/i })).toBeEnabled()
  })

  it('revokes a single session and removes it from the list', async () => {
    const user = userEvent.setup()
    render(<Wrapper />)
    await waitFor(() => expect(screen.getByText('This device')).toBeInTheDocument())

    const revokeButton = screen.getByRole('button', { name: /Revoke/i })
    await user.click(revokeButton)

    await waitFor(() => expect(revokeSession).toHaveBeenCalledWith('sess_b'))
    await waitFor(() => expect(screen.queryByText(/sess_b/)).not.toBeInTheDocument())
  })

  it('signs out all other devices and refreshes the list', async () => {
    const user = userEvent.setup()
    vi.mocked(listSessions)
      .mockResolvedValueOnce({
        sessions: [
          { ...sessionBase, session_id: 'sess_a', current: true, last_seen_at: 1700000100 },
          { ...sessionBase, session_id: 'sess_b', current: false, last_seen_at: 1700000000 },
        ],
        count: 2,
      })
      .mockResolvedValueOnce({
        sessions: [{ ...sessionBase, session_id: 'sess_a', current: true, last_seen_at: 1700000100 }],
        count: 1,
      })
    render(<Wrapper />)
    await waitFor(() => expect(screen.getByText('This device')).toBeInTheDocument())

    const signOutAll = screen.getByRole('button', { name: /Sign out all other devices/i })
    await user.click(signOutAll)

    await waitFor(() => expect(revokeOtherSessions).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByText(/sess_b/)).not.toBeInTheDocument())
  })

  it('shows a warning when no sessions are returned', async () => {
    vi.mocked(listSessions).mockResolvedValue({ sessions: [], count: 0 })
    render(<Wrapper />)
    await waitFor(() => {
      expect(screen.getByText(/No active server-side sessions found/i)).toBeInTheDocument()
    })
  })
})
