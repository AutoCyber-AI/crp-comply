import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ProfilePanel } from '../ProfilePanel'
import { useProfile } from '@/lib/profile'
import { patchOrgProfile } from '@/lib/api'
import { ToastProvider } from '@/components/toast/ToastProvider'

vi.mock('@/lib/api', () => ({
  patchOrgProfile: vi.fn(),
}))

vi.mock('@/lib/profile', async () => {
  const actual = await vi.importActual<typeof import('@/lib/profile')>('@/lib/profile')
  return {
    ...actual,
    useProfile: vi.fn(),
  }
})

function Wrapper() {
  return (
    <ToastProvider>
      <ProfilePanel />
    </ToastProvider>
  )
}

describe('ProfilePanel', () => {
  beforeEach(() => {
    vi.mocked(useProfile).mockReturnValue({
      profile: {
        org_name: 'Acme',
        actor: 'provider',
        jurisdictions: ['EU'],
        is_high_risk: true,
      },
      loading: false,
      error: null,
      updateProfile: vi.fn(),
      saveProfile: vi.fn(),
      resetProfile: vi.fn(),
      isOnboarded: true,
      userId: 'user_123',
      tier: 'pro',
    })
    vi.mocked(patchOrgProfile).mockResolvedValue({ is_onboarded: true })
  })

  it('renders profile fields from useProfile', () => {
    render(<Wrapper />)
    expect(screen.getByLabelText(/organisation name/i)).toHaveValue('Acme')
    expect(screen.getByLabelText(/role under the ai act/i)).toHaveValue('provider')
    expect(screen.getByLabelText(/jurisdictions/i)).toHaveValue('EU')
  })

  it('calls patchOrgProfile with partial changes after debounce', async () => {
    render(<Wrapper />)
    const input = screen.getByLabelText(/organisation name/i)
    fireEvent.change(input, { target: { value: 'Acme AI' } })
    await waitFor(
      () => {
        expect(patchOrgProfile).toHaveBeenCalledTimes(1)
        expect(patchOrgProfile).toHaveBeenCalledWith(expect.objectContaining({ org_name: 'Acme AI' }))
      },
      { timeout: 2000 },
    )
  })
})
