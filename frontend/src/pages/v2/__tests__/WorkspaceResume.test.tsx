import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import Workspace from '../Workspace'
import { useProfile } from '@/lib/profile'
import {
  listRecipes,
  tailorRecipe,
  listHumanInputs,
  runRecipeStream,
  createDraft,
  linkDraftReport,
  getPreferences,
  type DraftSession,
} from '@/lib/api'
import { ToastProvider } from '@/components/toast/ToastProvider'
import { installFakeIndexedDB, type FakeIDBDatabase } from '@/test/fakeIndexedDB'
import { setDraft } from '@/lib/idb'

vi.mock('@/lib/api', () => ({
  listRecipes: vi.fn(),
  tailorRecipe: vi.fn(),
  listHumanInputs: vi.fn(),
  runRecipeStream: vi.fn(),
  createDraft: vi.fn(),
  linkDraftReport: vi.fn(),
  getPreferences: vi.fn(),
}))

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
  required_inputs: ['system_name'],
  tags: [],
  actor: 'provider',
  tier: 'free' as const,
}

function Wrapper({ search = '?recipe=eu_ai_act_art_9' }: { search?: string }) {
  return (
    <ToastProvider>
      <MemoryRouter initialEntries={[`/app/workspace${search}`]}>
        <Routes>
          <Route path="/app/workspace" element={<Workspace />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>
  )
}

let fakeDB: FakeIDBDatabase

beforeEach(() => {
  fakeDB = installFakeIndexedDB()
  vi.mocked(useProfile).mockReturnValue({
    profile: {},
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
  vi.mocked(tailorRecipe).mockResolvedValue({
    recipe_id: recipe.recipe_id,
    should_produce: true,
    why: 'Matches profile',
    triggers: [],
    actors: [],
    applicable_sections: [],
    skipped_sections: [],
    profile_keys_used: [],
    pending_questions: [],
  })
  vi.mocked(listHumanInputs).mockResolvedValue([
    { key: 'system_name', prompt: 'System name', priority: 'high', source: 'recipe' },
  ])
  vi.mocked(runRecipeStream).mockReturnValue(
    (async function* () {
      yield {
        event: 'recipe.done' as const,
        data: {
          recipe_id: recipe.recipe_id,
          title: recipe.title,
          regulation: recipe.regulation,
          markdown: '',
          json_payload: {},
          section_citations: {},
          duration_ms: 0,
          warnings: [],
          pending_human_inputs: [],
          report_id: 'report_123',
        },
      }
    })(),
  )
  vi.mocked(createDraft).mockResolvedValue({
    session_id: 'draft_123',
    user_id: 'user_123',
    recipe_id: recipe.recipe_id,
    obligation_id: '',
    system_name: 'Test System',
    agent_session_id: '',
    report_id: 'report_123',
    state: 'linked',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  } as DraftSession)
  vi.mocked(linkDraftReport).mockResolvedValue({
    session_id: 'draft_123',
    user_id: 'user_123',
    recipe_id: recipe.recipe_id,
    obligation_id: '',
    system_name: 'Test System',
    agent_session_id: '',
    report_id: 'report_123',
    state: 'linked',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  } as DraftSession)
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

afterEach(() => {
  // @ts-expect-error remove fake
  delete window.indexedDB
})

describe('Workspace draft resume', () => {
  it('restores saved input from IndexedDB and shows the resume chip', async () => {
    await setDraft('crp-recipe-inputs:user_123:eu_ai_act_art_9', { system_name: 'Restored System' })

    render(<Wrapper />)

    await waitFor(() => {
      expect(screen.getByDisplayValue('Restored System')).toBeInTheDocument()
    })
    expect(screen.getByText(/resumed previous draft/i)).toBeInTheDocument()
  })

  it('does not show the resume chip when there is no saved draft', async () => {
    render(<Wrapper />)

    await waitFor(() => {
      expect(screen.getAllByDisplayValue('')[0]).toBeInTheDocument()
    })
    expect(screen.queryByText(/resumed previous draft/i)).not.toBeInTheDocument()
  })

  it('saves typed input to IndexedDB after the debounce', async () => {
    render(<Wrapper />)

    const input = await screen.findByRole('textbox')
    await userEvent.type(input, 'Acme AI')

    await waitFor(
      () => {
        expect(fakeDB.data.get('crp-recipe-inputs:user_123:eu_ai_act_art_9')).toEqual({
          system_name: 'Acme AI',
        })
      },
      { timeout: 1500 },
    )
  })
})
