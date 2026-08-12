import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { IntentPreviewModal } from '../IntentPreviewModal'
import type { TailoringPlan } from '../../../lib/api'

const plan: TailoringPlan = {
  recipe_id: 'r_123',
  should_produce: true,
  why: 'Profile matches high-risk provider.',
  triggers: ['high-risk'],
  actors: ['provider'],
  applicable_sections: [{ id: 's1', title: 'Risk management', citations: [] }],
  skipped_sections: [{ section_id: 's2', title: 'GPAI transparency', reason: 'Not a GPAI' }],
  profile_keys_used: ['actor', 'is_high_risk'],
  pending_questions: [{ key: 'q1', question: 'Who is the responsible person?' }],
}

describe('IntentPreviewModal', () => {
  it('renders plan summary and disables approve when not applicable', () => {
    render(
      <IntentPreviewModal
        open
        plan={{ ...plan, should_produce: false }}
        autonomy="draft"
        onClose={vi.fn()}
        onApprove={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /approve and run/i })).toBeDisabled()
  })

  it('calls onApprove with the selected autonomy', async () => {
    const onApprove = vi.fn()
    render(<IntentPreviewModal open plan={plan} autonomy="draft" onClose={vi.fn()} onApprove={onApprove} />)
    await userEvent.click(screen.getByRole('button', { name: 'Full' }))
    await userEvent.click(screen.getByRole('button', { name: /approve and run/i }))
    expect(onApprove).toHaveBeenCalledWith('full')
  })

  it('calls onClose when cancel is clicked', async () => {
    const onClose = vi.fn()
    render(<IntentPreviewModal open plan={plan} autonomy="draft" onClose={onClose} onApprove={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onClose).toHaveBeenCalled()
  })
})
