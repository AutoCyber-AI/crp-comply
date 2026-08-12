import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RecipePicker } from '../RecipePicker'
import type { RecipeSummary } from '../../../lib/api'

const recipes: RecipeSummary[] = [
  { recipe_id: 'r1', title: 'DPIA', regulation: 'GDPR', description: '', required_inputs: [], tags: [] },
  { recipe_id: 'r2', title: 'FRIA', regulation: 'EU AI Act', description: '', required_inputs: [], tags: [] },
]

describe('RecipePicker', () => {
  it('shows the current recipe when selected', () => {
    render(<RecipePicker recipes={recipes} value="r1" onChange={vi.fn()} />)
    expect(screen.getByRole('button')).toHaveTextContent('DPIA')
  })

  it('opens the dropdown and filters recipes', async () => {
    render(<RecipePicker recipes={recipes} value="" onChange={vi.fn()} />)
    await userEvent.click(screen.getByRole('button'))
    expect(screen.getByText('DPIA')).toBeInTheDocument()
    expect(screen.getByText('FRIA')).toBeInTheDocument()

    const search = screen.getByPlaceholderText('Search 2 recipes…')
    await userEvent.type(search, 'FRIA')
    expect(screen.queryByText('DPIA')).not.toBeInTheDocument()
    expect(screen.getByText('FRIA')).toBeInTheDocument()
  })

  it('calls onChange when a recipe is selected', async () => {
    const onChange = vi.fn()
    render(<RecipePicker recipes={recipes} value="" onChange={onChange} />)
    await userEvent.click(screen.getByRole('button'))
    await userEvent.click(screen.getByText('FRIA'))
    expect(onChange).toHaveBeenCalledWith('r2')
  })
})
