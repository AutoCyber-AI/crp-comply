import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AutonomyDial } from '../AutonomyDial'

describe('AutonomyDial', () => {
  it('renders four autonomy levels', () => {
    render(<AutonomyDial value="draft" onChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Suggest' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Draft' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Autonomous with Checkpoints' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Full' })).toBeInTheDocument()
  })

  it('calls onChange when a level is selected', async () => {
    const onChange = vi.fn()
    render(<AutonomyDial value="draft" onChange={onChange} />)
    await userEvent.click(screen.getByRole('button', { name: 'Full' }))
    expect(onChange).toHaveBeenCalledWith('full')
  })

  it('does not respond when disabled', async () => {
    const onChange = vi.fn()
    render(<AutonomyDial value="draft" onChange={onChange} disabled />)
    await userEvent.click(screen.getByRole('button', { name: 'Full' }))
    expect(onChange).not.toHaveBeenCalled()
  })
})
