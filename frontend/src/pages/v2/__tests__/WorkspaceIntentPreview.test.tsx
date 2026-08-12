import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import Workspace from '../Workspace'
import { useProfile } from '@/lib/profile'
import {
  listRecipes,
  tailorRecipe,
  listHumanInputs,
  getPreferences,
  runRecipeStream,
  type TailoringPlan,
  type RecipeRunResponse,
} from '@/lib/api'
import { ToastProvider } from '@/components/toast/ToastProvider'

vi.mock('@/lib/api', () => ({
  listRecipes: vi.fn(),
  tailorRecipe: vi.fn(),
  listHumanInputs: vi.fn(),
  runRecipeStream: vi.fn(),
  createDraft: vi.fn(),
  linkDraftReport: vi.fn(),
  getPreferences: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(message: string, public status: number) {
      super(message)
      this.name = 'ApiError'
    }
  },
  formatErrorDetail: (detail: unknown) => (typeof detail === 'string' ? detail : String(detail)),
}))

const doneResponse: RecipeRunResponse = {
  recipe_id: 'eu_ai_act_art_9',
  title: 'Risk management system',
  regulation: 'EU AI Act',
  markdown: '# Risk management system\n\nDraft.',
  json_payload: {},
  section_citations: {},
  duration_ms: 0,
  warnings: [],
  pending_human_inputs: [],
  report_id: null,
}

vi.mock('@/lib/profile', async () => {
  const actual = await vi.importActual<typeof import('@/lib/profile')>('@/lib/profile')
  return {
    ...actual,
    useProfile: vi.fn(),
  }
})

const recipe = {
  recipe_id: 'eu_ai_act_art_9',
  title: 'Risk management system',
  regulation: 'EU AI Act',
  description: 'High-risk AI system risk management file.',
  required_inputs: [],
  tags: [],
  actor: 'provider',
  tier: 'free' as const,
}

const plan: TailoringPlan = {
  recipe_id: recipe.recipe_id,
  should_produce: true,
  why: 'High-risk provider profile triggers this recipe.',
  triggers: ['high-risk'],
  actors: ['provider'],
  applicable_sections: [{ id: 's1', title: 'Risk management system', citations: [] }],
  skipped_sections: [],
  profile_keys_used: ['is_high_risk'],
  pending_questions: [],
}

function Wrapper() {
  return (
    <ToastProvider>
      <MemoryRouter initialEntries={['/app/workspace?recipe=eu_ai_act_art_9']}>
        <Routes>
          <Route path="/app/workspace" element={<Workspace />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>
  )
}

beforeEach(() => {
  vi.mocked(useProfile).mockReturnValue({
    profile: { is_high_risk: true },
    loading: false,
    error: null,
    updateProfile: vi.fn(),
    saveProfile: vi.fn(),
    resetProfile: vi.fn(),
    isOnboarded: true,
    userId: 'user_123',
    tier: 'free' as const,
  })
  vi.mocked(listRecipes).mockResolvedValue([recipe])
  vi.mocked(tailorRecipe).mockResolvedValue(plan)
  vi.mocked(listHumanInputs).mockResolvedValue([])
  vi.mocked(getPreferences).mockResolvedValue({
    tenant_id: 't_123',
    user_id: 'user_123',
    preferred_depth: 'standard',
    preferred_format: 'markdown',
    preferred_audience: 'compliance officer',
    preferred_regulations: [],
    trusted_source_domains: [],
    satisfaction_criteria: [],
    preferred_autonomy: 'draft',
    feedback_summary: {},
    explicit_feedback_count: 0,
    implicit_signal_count: 0,
    updated_at: new Date().toISOString(),
  })
})

describe('Workspace intent preview', () => {
  it('opens the intent preview modal when Run recipe is clicked', async () => {
    render(<Wrapper />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /run recipe/i })).toBeEnabled()
    })
    await userEvent.click(screen.getByRole('button', { name: /run recipe/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /ready to generate/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /approve and run/i })).toBeInTheDocument()
  })

  it('forwards the selected autonomy to the recipe stream request', async () => {
    vi.mocked(runRecipeStream).mockImplementation(async function* () {
      yield { event: 'recipe.done', data: doneResponse }
    })

    render(<Wrapper />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /run recipe/i })).toBeEnabled()
    })
    await userEvent.click(screen.getByRole('button', { name: /run recipe/i }))
    await userEvent.click(screen.getByRole('button', { name: /approve and run/i }))

    await waitFor(() => {
      expect(runRecipeStream).toHaveBeenCalledWith(
        'eu_ai_act_art_9',
        expect.objectContaining({ autonomy: 'draft' }),
        expect.any(AbortSignal),
      )
    })
  })
})
