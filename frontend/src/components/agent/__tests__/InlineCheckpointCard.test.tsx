import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { InlineCheckpointCard } from '../InlineCheckpointCard'
import type { Checkpoint } from '../../../lib/api'

const checkpoint: Checkpoint = {
  checkpoint_id: 'cp_123',
  session_id: 'sess_123',
  tool_name: 'send_email',
  tool_args: { to: 'auditor@example.com' },
  reason: 'This will email an external auditor.',
  created_at: Date.now() / 1000,
  timeout_seconds: 300,
  tenant_id: 't_123',
}

describe('InlineCheckpointCard', () => {
  it('renders the checkpoint reason and tool name', () => {
    render(<InlineCheckpointCard checkpoint={checkpoint} onResolve={vi.fn()} />)
    expect(screen.getByText(/email an external auditor/i)).toBeInTheDocument()
    expect(screen.getByText('send_email')).toBeInTheDocument()
  })

  it('approves with an optional note', async () => {
    const onResolve = vi.fn()
    render(<InlineCheckpointCard checkpoint={checkpoint} onResolve={onResolve} />)
    await userEvent.type(screen.getByPlaceholderText('Add a note (optional)'), 'Approved by compliance lead')
    await userEvent.click(screen.getByRole('button', { name: /approve/i }))
    expect(onResolve).toHaveBeenCalledWith('cp_123', 'approve', 'Approved by compliance lead')
  })

  it('rejects with an optional note', async () => {
    const onResolve = vi.fn()
    render(<InlineCheckpointCard checkpoint={checkpoint} onResolve={onResolve} />)
    await userEvent.click(screen.getByRole('button', { name: /reject/i }))
    expect(onResolve).toHaveBeenCalledWith('cp_123', 'reject', '')
  })
})
