import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../Workspace', () => ({
  default: () => <div data-testid="workspace">Workspace</div>,
}))

vi.mock('../AgentChat', () => ({
  default: () => <div data-testid="chat">AgentChat</div>,
}))

import Draft from '../Draft'

function Wrapper({ initialSearch = '' }: { initialSearch?: string }) {
  return (
    <MemoryRouter initialEntries={[`/app/draft${initialSearch}`]}>
      <Routes>
        <Route path="/app/draft" element={<Draft />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('Draft', () => {
  it('defaults to workspace tab', () => {
    render(<Wrapper />)
    expect(screen.getByTestId('workspace')).toBeInTheDocument()
    expect(screen.queryByTestId('chat')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /recipe runner/i })).toHaveAttribute('aria-current', 'page')
  })

  it('switches to chat tab from query param', () => {
    render(<Wrapper initialSearch="?mode=chat" />)
    expect(screen.getByTestId('chat')).toBeInTheDocument()
    expect(screen.queryByTestId('workspace')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^assistant chat/i })).toHaveAttribute('aria-current', 'page')
  })
})
