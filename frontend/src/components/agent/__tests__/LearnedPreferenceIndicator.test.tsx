import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { LearnedPreferenceIndicator } from '../LearnedPreferenceIndicator'
import type { UserPreferenceProfile } from '../../../lib/api'

const prefs: UserPreferenceProfile = {
  tenant_id: 't_123',
  user_id: 'u_123',
  preferred_depth: 'thorough',
  preferred_format: 'markdown',
  preferred_audience: 'compliance officer',
  preferred_regulations: ['EU AI Act'],
  trusted_source_domains: [],
  satisfaction_criteria: [],
  preferred_autonomy: 'autonomous_with_checkpoints',
  feedback_summary: {},
  explicit_feedback_count: 2,
  implicit_signal_count: 5,
  updated_at: new Date().toISOString(),
}

describe('LearnedPreferenceIndicator', () => {
  it('displays current depth and autonomy', () => {
    render(<LearnedPreferenceIndicator preferences={prefs} onUpdate={vi.fn()} />)
    expect(screen.getByText(/Depth Thorough/i)).toBeInTheDocument()
    expect(screen.getByText('Auto+CP')).toBeInTheDocument()
    expect(screen.getByText('Learned')).toBeInTheDocument()
  })

  it('opens override popover and saves new autonomy', async () => {
    const onUpdate = vi.fn()
    render(<LearnedPreferenceIndicator preferences={prefs} onUpdate={onUpdate} />)
    await userEvent.click(screen.getByRole('button', { name: /depth thorough/i }))
    expect(screen.getByText(/your preferences/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Suggest' }))
    await userEvent.click(screen.getByRole('button', { name: /save default/i }))
    expect(onUpdate).toHaveBeenCalledWith({ preferred_autonomy: 'suggest' })
  })
})
