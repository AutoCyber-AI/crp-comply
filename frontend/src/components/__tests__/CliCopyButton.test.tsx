import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { CliCopyButton } from '../CliCopyButton'
import * as clipboard from '@/lib/clipboard'

vi.mock('@/lib/clipboard', () => ({
  copyToClipboard: vi.fn(),
}))

beforeEach(() => {
  vi.resetAllMocks()
})

describe('CliCopyButton', () => {
  it('copies the command when clicked', async () => {
    vi.mocked(clipboard.copyToClipboard).mockResolvedValue(true)
    render(<CliCopyButton command="crp-comply worker test" />)

    const button = screen.getByRole('button', { name: /copy cli command/i })
    await userEvent.click(button)

    await waitFor(() => {
      expect(clipboard.copyToClipboard).toHaveBeenCalledWith('crp-comply worker test')
    })
  })
})
