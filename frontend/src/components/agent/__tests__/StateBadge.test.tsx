import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StateBadge } from '../StateBadge'

describe('StateBadge', () => {
  it.each([
    ['done', 'Done'],
    ['error', 'Error'],
    ['awaiting_clarification', 'Awaiting you'],
    ['running', 'Processing'],
    ['max_iters', 'Max iters'],
    ['unknown', 'unknown'],
  ])('renders %s as %s', (state, label) => {
    render(<StateBadge state={state} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })
})
