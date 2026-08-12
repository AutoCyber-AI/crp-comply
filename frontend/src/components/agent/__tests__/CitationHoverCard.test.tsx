import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { CitationHoverCard } from '../CitationHoverCard'

describe('CitationHoverCard', () => {
  it('shows a static summary on hover', async () => {
    render(<CitationHoverCard citation="Art 6(2)" summary="High-risk systems must meet Chapter III requirements." />)
    const trigger = screen.getByRole('button', { name: 'Art 6(2)' })
    await userEvent.hover(trigger)
    await waitFor(() => {
      expect(screen.getByRole('tooltip')).toHaveTextContent('High-risk systems must meet Chapter III requirements.')
    })
  })

  it('loads a summary asynchronously on hover', async () => {
    const loader = vi.fn().mockResolvedValue('Async loaded summary.')
    render(<CitationHoverCard citation="Art 9" onLoadSummary={loader} />)
    const trigger = screen.getByRole('button', { name: 'Art 9' })
    await userEvent.hover(trigger)
    await waitFor(() => {
      expect(loader).toHaveBeenCalledWith('Art 9')
    })
    await waitFor(() => {
      expect(screen.getByRole('tooltip')).toHaveTextContent('Async loaded summary.')
    })
  })
})
