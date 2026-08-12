import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { CommandPalette } from '../CommandPalette'
import { searchAll } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  searchAll: vi.fn(),
}))

function LocationSpy() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname + location.search}</div>
}

function Wrapper({ open = true }: { open?: boolean }) {
  return (
    <MemoryRouter>
      <CommandPalette open={open} onClose={vi.fn()} onOpenHelp={vi.fn()} />
      <LocationSpy />
    </MemoryRouter>
  )
}

const mockResults = [
  {
    id: 'eu_ai_act_annex_iv',
    type: 'recipe' as const,
    title: 'Annex IV technical documentation',
    subtitle: 'EU AI Act',
    url: '/app/workspace?recipe=eu_ai_act_annex_iv',
    meta: { regulation: 'EU AI Act', tags: ['high-risk'] },
  },
  {
    id: 'rep_1',
    type: 'report' as const,
    title: 'CRM AI',
    subtitle: 'compliance_report',
    url: '/app/vault/rep_1',
    meta: { kind: 'compliance_report', risk_level: 'HIGH' },
  },
]

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(searchAll).mockResolvedValue({
    query: '',
    scopes: ['recipe', 'report'],
    results: mockResults,
  })
})

describe('CommandPalette', () => {
  it('shows pages and dynamic search results', async () => {
    render(<Wrapper />)

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument()
    })

    expect(screen.getByText('Annex IV technical documentation')).toBeInTheDocument()
    expect(screen.getByText('CRM AI')).toBeInTheDocument()
  })

  it('navigates when a page item is selected', async () => {
    render(<Wrapper />)

    await waitFor(() => {
      expect(screen.getByText('Vault')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByText('Vault'))

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/app/vault')
    })
  })

  it('calls searchAll with the typed query', async () => {
    render(<Wrapper />)

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument()
    })

    const input = screen.getByPlaceholderText(/search pages/i)
    await userEvent.type(input, 'annex')

    await waitFor(() => {
      expect(searchAll).toHaveBeenCalledWith('annex', 100)
    })
  })
})
