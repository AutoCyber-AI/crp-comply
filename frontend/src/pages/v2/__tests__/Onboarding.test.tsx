import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import Onboarding from '../Onboarding'
import { classifyOnboarding, putContactProfile } from '@/lib/api'
import { useProfile } from '@/lib/profile'

vi.mock('@/lib/api', () => ({
  classifyOnboarding: vi.fn(),
  putContactProfile: vi.fn(),
  formatErrorDetail: vi.fn((d) => String(d)),
  ApiError: class extends Error {
    constructor(message: string, public status: number) {
      super(message)
    }
  },
}))

vi.mock('@/lib/profile', () => ({
  useProfile: vi.fn(),
}))

function LocationSpy() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

const mockSaveProfile = vi.fn()

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(useProfile).mockReturnValue({
    profile: {},
    saveProfile: mockSaveProfile,
    updateProfile: vi.fn(),
    resetProfile: vi.fn(),
    loading: false,
    error: null,
    isOnboarded: false,
    userId: 'user_1',
    tier: 'free',
  } as unknown as ReturnType<typeof useProfile>)

  vi.mocked(classifyOnboarding).mockResolvedValue({
    profile: {
      actor: 'provider',
      jurisdictions: ['EU'],
      established_in_eu: true,
      is_high_risk: true,
      system_category: 'high-risk AI system',
      is_onboarded: false,
    },
    classification: 'Provider in EU building a high-risk AI system',
    recommended_recipes: [
      {
        recipe_id: 'eu_ai_act_annex_iv_tech_docs',
        title: 'Annex IV technical documentation',
        should_produce: true,
        why: 'Required for high-risk providers under EU AI Act.',
      },
    ],
    checklist: [
      'Review your recommended deliverables below',
      'Prepare Annex IV technical documentation',
      'Complete your organisation profile in Settings',
      'Generate your first compliance report',
    ],
  })

  vi.mocked(putContactProfile).mockResolvedValue({})

  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList)
})

describe('Onboarding microsurvey', () => {
  it('renders the 3-question microsurvey and progress checklist', () => {
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    )

    expect(screen.getByText(/What is your role/i)).toBeInTheDocument()
    expect(screen.getByText(/Where do you operate/i)).toBeInTheDocument()
    expect(screen.getByText(/What kind of system/i)).toBeInTheDocument()
    expect(screen.getByText('Account created')).toBeInTheDocument()
  })

  it('classifies answers and shows the celebration screen', async () => {
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByText('We build or market it'))
    await userEvent.click(screen.getByText('EU'))
    await userEvent.click(screen.getByText('High-risk system'))

    await userEvent.click(screen.getByText('See my compliance plan'))

    await waitFor(() => {
      expect(screen.getByText('Your compliance plan is ready')).toBeInTheDocument()
    })

    expect(screen.getByText(/Provider in EU/i)).toBeInTheDocument()
    expect(screen.getByText('Annex IV technical documentation')).toBeInTheDocument()
  })

  it('saves the profile and navigates to the dashboard on finish', async () => {
    render(
      <MemoryRouter>
        <Onboarding />
        <LocationSpy />
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByText('We build or market it'))
    await userEvent.click(screen.getByText('EU'))
    await userEvent.click(screen.getByText('High-risk system'))
    await userEvent.click(screen.getByText('See my compliance plan'))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /finish onboarding/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /finish onboarding/i }))

    await waitFor(() => {
      expect(mockSaveProfile).toHaveBeenCalled()
      expect(screen.getByTestId('location')).toHaveTextContent('/app')
    })
  })
})
