import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { PasskeyStepUpModal } from '../PasskeyStepUpModal'
import { stepUpPasskey } from '@/lib/passkey'
import { useAuth } from '@clerk/react'
import { ToastProvider } from '../toast/ToastProvider'

vi.mock('@clerk/react', () => ({
  useAuth: vi.fn(() => ({
    getToken: vi.fn(() => Promise.resolve('test-token')),
    isLoaded: true,
    isSignedIn: true,
  })),
}))

vi.mock('@/lib/passkey', () => ({
  stepUpPasskey: vi.fn(),
}))

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>
}

describe('PasskeyStepUpModal', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useAuth).mockReturnValue({
      getToken: vi.fn(() => Promise.resolve('test-token')),
      isLoaded: true,
      isSignedIn: true,
    } as unknown as ReturnType<typeof useAuth>)
  })

  it('does not render when closed', () => {
    render(
      <Wrapper>
        <PasskeyStepUpModal open={false} actionName="test action" onClose={() => {}} onVerified={() => {}} />
      </Wrapper>,
    )
    expect(screen.queryByText(/test action/i)).not.toBeInTheDocument()
  })

  it('calls stepUpPasskey and onVerified when approved', async () => {
    const user = userEvent.setup()
    const onVerified = vi.fn()
    vi.mocked(stepUpPasskey).mockResolvedValue({ status: 'ok', elevated_until: Date.now() / 1000 + 900, risk_score: 0, risk_factors: [] })

    render(
      <Wrapper>
        <PasskeyStepUpModal open actionName="test action" onClose={() => {}} onVerified={onVerified} />
      </Wrapper>,
    )

    expect(screen.getByText(/test action/i)).toBeInTheDocument()
    const verifyButton = screen.getByRole('button', { name: /Verify with passkey/i })
    await user.click(verifyButton)

    await waitFor(() => expect(stepUpPasskey).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(onVerified).toHaveBeenCalled())
  })

  it('shows an error when verification fails', async () => {
    const user = userEvent.setup()
    vi.mocked(stepUpPasskey).mockRejectedValue(new Error('Passkey verification was cancelled.'))

    render(
      <Wrapper>
        <PasskeyStepUpModal open actionName="test action" onClose={() => {}} onVerified={() => {}} />
      </Wrapper>,
    )

    const verifyButton = screen.getByRole('button', { name: /Verify with passkey/i })
    await user.click(verifyButton)

    await waitFor(() => {
      expect(screen.getByTestId('step-up-error')).toHaveTextContent(/Passkey verification was cancelled/i)
    })
  })
})
