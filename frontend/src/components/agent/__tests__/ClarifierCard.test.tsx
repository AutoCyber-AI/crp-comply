import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ClarifierCard } from '../ClarifierCard'

describe('ClarifierCard', () => {
  it('renders children and a high-priority chip', () => {
    render(<ClarifierCard priority="high">What is the system name?</ClarifierCard>)
    expect(screen.getByText('High priority question')).toBeInTheDocument()
    expect(screen.getByText('What is the system name?')).toBeInTheDocument()
  })

  it('calls onSkip when the skip button is clicked', async () => {
    const onSkip = vi.fn()
    render(
      <ClarifierCard priority="medium" skippable onSkip={onSkip}>
        Optional question
      </ClarifierCard>,
    )
    const skip = screen.getByRole('button', { name: /skip/i })
    await userEvent.click(skip)
    expect(onSkip).toHaveBeenCalledTimes(1)
  })

  it('does not show skip when skippable is false', () => {
    render(<ClarifierCard priority="low">Required question</ClarifierCard>)
    expect(screen.queryByRole('button', { name: /skip/i })).not.toBeInTheDocument()
  })

  it('renders confirmation options and calls onOption', async () => {
    const onOption = vi.fn()
    render(
      <ClarifierCard
        action="confirm"
        options={["Yes, that's right", 'No, let me correct it']}
        onOption={onOption}
      >
        Does this look right?
      </ClarifierCard>,
    )
    expect(screen.getByText('Confirm')).toBeInTheDocument()
    const yes = screen.getByRole('button', { name: /yes, that's right/i })
    await userEvent.click(yes)
    expect(onOption).toHaveBeenCalledWith("Yes, that's right")
  })

  it('renders repair options and calls onOption', async () => {
    const onOption = vi.fn()
    render(
      <ClarifierCard
        action="repair"
        options={['Use the new value', 'Keep the original value']}
        onOption={onOption}
      >
        Which value is correct?
      </ClarifierCard>,
    )
    expect(screen.getByText('Repair')).toBeInTheDocument()
    const keep = screen.getByRole('button', { name: /keep the original value/i })
    await userEvent.click(keep)
    expect(onOption).toHaveBeenCalledWith('Keep the original value')
  })
})
