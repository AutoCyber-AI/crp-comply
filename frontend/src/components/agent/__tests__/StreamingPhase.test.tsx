import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StreamingPhase } from '../StreamingPhase'
import type { LoopEvent } from '../../../lib/loopEvents'

describe('StreamingPhase', () => {
  it('shows a thinking chip when streaming with no events', () => {
    render(<StreamingPhase events={[]} streaming />)
    expect(screen.getByText('Thinking')).toBeInTheDocument()
  })

  it('maps loop.phase.complete to a friendly label', () => {
    const events: LoopEvent[] = [
      { event: 'loop.phase.complete', phase: 'retrieve', ts: 1, run_id: 'r1' } as LoopEvent,
    ]
    render(<StreamingPhase events={events} streaming />)
    expect(screen.getByText('Retrieving context')).toBeInTheDocument()
  })

  it('renders recent tool invocation chips', () => {
    const events: LoopEvent[] = [
      { event: 'loop.tool.call', tool: 'consult_regulation_expert', step_id: 's1', args: {}, ts: 1, run_id: 'r1' } as unknown as LoopEvent,
      { event: 'loop.tool.result', tool: 'consult_regulation_expert', step_id: 's1', ts: 2, run_id: 'r1' } as unknown as LoopEvent,
    ]
    render(<StreamingPhase events={events} />)
    expect(screen.getByText('consult_regulation_expert')).toBeInTheDocument()
  })

  it('marks a failed tool result as danger', () => {
    const events: LoopEvent[] = [
      { event: 'loop.tool.call', tool: 'web_search', step_id: 's1', args: {}, ts: 1, run_id: 'r1' } as unknown as LoopEvent,
      { event: 'loop.tool.result', tool: 'web_search', step_id: 's1', error: 'timeout', ts: 2, run_id: 'r1' } as unknown as LoopEvent,
    ]
    const { container } = render(<StreamingPhase events={events} />)
    const chip = container.querySelector('.chip-danger')
    expect(chip).toBeTruthy()
  })
})
