import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import RecipeLibrary from '../RecipeLibrary'
import { useProfile } from '@/lib/profile'
import { listRecipes, recommendRecipes } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  listRecipes: vi.fn(),
  recommendRecipes: vi.fn(),
}))

vi.mock('@/lib/profile', async () => {
  const actual = await vi.importActual<typeof import('@/lib/profile')>('@/lib/profile')
  return {
    ...actual,
    useProfile: vi.fn(),
  }
})

const recipes = [
  {
    recipe_id: 'eu_ai_act_art_9',
    title: 'Risk management system',
    regulation: 'EU AI Act',
    description: 'High-risk AI system risk management file.',
    required_inputs: [],
    tags: ['high-risk'],
    actor: 'provider',
    tier: 'free' as const,
  },
  {
    recipe_id: 'gdpr_dpia',
    title: 'GDPR DPIA',
    regulation: 'GDPR',
    description: 'Data protection impact assessment.',
    required_inputs: [],
    tags: [],
    actor: 'deployer',
    tier: 'pro' as const,
  },
  {
    recipe_id: 'iso_42001_soa',
    title: 'ISO 42001 Statement of Applicability',
    regulation: 'ISO/IEC 42001',
    description: 'AI management system SoA.',
    required_inputs: [],
    tags: [],
    actor: 'provider',
    tier: 'enterprise' as const,
  },
]

const recommendations = recipes.map((r) => ({
  recipe_id: r.recipe_id,
  should_produce: true,
  why: 'Matches profile',
  triggers: [],
  actors: [],
  applicable_sections: [],
  skipped_sections: [],
  profile_keys_used: [],
  pending_questions: [],
}))

function Wrapper() {
  return (
    <MemoryRouter>
      <RecipeLibrary />
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.mocked(useProfile).mockReturnValue({
    profile: {},
    loading: false,
    error: null,
    updateProfile: vi.fn(),
    saveProfile: vi.fn(),
    resetProfile: vi.fn(),
    isOnboarded: true,
    userId: 'user_123',
    tier: 'pro' as const,
  })
  vi.mocked(listRecipes).mockResolvedValue(recipes)
  vi.mocked(recommendRecipes).mockResolvedValue(recommendations)
})

describe('RecipeLibrary', () => {
  it('renders the full catalogue and tier lock badges', async () => {
    render(<Wrapper />)
    await waitFor(() => {
      expect(screen.getByText('Risk management system')).toBeInTheDocument()
    })
    expect(screen.getByText('GDPR DPIA')).toBeInTheDocument()
    expect(screen.getByText('ISO 42001 Statement of Applicability')).toBeInTheDocument()
    expect(screen.getByText('ENTERPRISE')).toBeInTheDocument()
  })

  it('filters by framework', async () => {
    render(<Wrapper />)
    await waitFor(() => {
      expect(screen.getByText('Risk management system')).toBeInTheDocument()
    })

    const frameworkSelect = screen.getByLabelText(/framework/i)
    await userEvent.selectOptions(frameworkSelect, 'GDPR')

    expect(screen.queryByText('Risk management system')).not.toBeInTheDocument()
    expect(screen.queryByText('ISO 42001 Statement of Applicability')).not.toBeInTheDocument()
    expect(screen.getByText('GDPR DPIA')).toBeInTheDocument()
  })

  it('disables Run and Interview for recipes above the user tier', async () => {
    render(<Wrapper />)
    await waitFor(() => {
      expect(screen.getByText('ISO 42001 Statement of Applicability')).toBeInTheDocument()
    })

    const enterpriseCard = screen.getByText('ISO 42001 Statement of Applicability').closest('div[class*="card"]')
      ?? screen.getByText('ISO 42001 Statement of Applicability').closest('div')
    const freeCard = screen.getByText('Risk management system').closest('div[class*="card"]')
      ?? screen.getByText('Risk management system').closest('div')

    expect(enterpriseCard).toBeTruthy()
    expect(freeCard).toBeTruthy()

    expect(enterpriseCard!.querySelector('button')?.disabled).toBe(true)
    const freeButtons = freeCard!.querySelectorAll('button')
    expect(Array.from(freeButtons).some((b) => !b.disabled)).toBe(true)
  })
})
