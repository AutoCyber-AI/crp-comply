import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ConfidenceLabel } from '../ConfidenceLabel'

describe('ConfidenceLabel', () => {
  it.each([
    [0.95, 'Very high confidence'],
    [0.8, 'High confidence'],
    [0.6, 'Moderate confidence'],
    [0.3, 'Low confidence'],
    [undefined, 'Uncertain'],
  ])('renders %s as %s', (score, expected) => {
    render(<ConfidenceLabel score={score} />)
    expect(screen.getByText(expected)).toBeInTheDocument()
  })
})
