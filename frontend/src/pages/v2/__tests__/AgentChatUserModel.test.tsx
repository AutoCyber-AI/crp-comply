import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AgentChatProfileSummary } from '../AgentChat'
import { useProfile } from '@/lib/profile'

vi.mock('@/lib/profile', async () => {
  const actual = await vi.importActual<typeof import('@/lib/profile')>('@/lib/profile')
  return {
    ...actual,
    useProfile: vi.fn(),
  }
})

describe('AgentChatProfileSummary', () => {
  it('renders actor, jurisdictions and positive flags as chips', () => {
    vi.mocked(useProfile).mockReturnValue({
      profile: {
        actor: 'deployer',
        jurisdictions: ['EU', 'UK'],
        is_high_risk: true,
        is_gpai: true,
        iso_42001_certified: true,
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
    render(<AgentChatProfileSummary />)
    expect(screen.getByText('Deployer')).toBeInTheDocument()
    expect(screen.getByText('EU, UK')).toBeInTheDocument()
    expect(screen.getByText('High risk')).toBeInTheDocument()
    expect(screen.getByText('GPAI')).toBeInTheDocument()
    expect(screen.getByText('ISO 42001')).toBeInTheDocument()
  })

  it('hides the panel when no profile is loaded', () => {
    vi.mocked(useProfile).mockReturnValue({
      profile: {},
      loading: false,
      error: null,
      updateProfile: vi.fn(),
      saveProfile: vi.fn(),
      resetProfile: vi.fn(),
      isOnboarded: false,
      userId: null,
      tier: 'free',
    })
    const { container } = render(<AgentChatProfileSummary />)
    expect(container.firstChild).toBeNull()
  })
})
