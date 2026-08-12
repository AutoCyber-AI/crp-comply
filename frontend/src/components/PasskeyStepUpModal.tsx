import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Fingerprint, X, Loader2, ShieldAlert } from 'lucide-react'
import { useAuth } from '@clerk/react'
import { stepUpPasskey } from '../lib/passkey'
import { Button } from '../design/primitives'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { useToast } from './toast/ToastProvider'

interface PasskeyStepUpModalProps {
  open: boolean
  actionName: string
  onClose: () => void
  onVerified: () => void
}

export function PasskeyStepUpModal({ open, actionName, onClose, onVerified }: PasskeyStepUpModalProps) {
  const { getToken } = useAuth()
  const toast = useToast()
  const ref = useFocusTrap<HTMLDivElement>({ active: open, onEscape: onClose })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  const verify = async () => {
    setLoading(true)
    setError(null)
    try {
      await stepUpPasskey(() => getToken({ template: 'crp-comply' }))
      toast.success('Identity confirmed', `You can now proceed with ${actionName}.`)
      onVerified()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Step-up failed'
      setError(msg)
      toast.error('Step-up failed', msg)
    } finally {
      setLoading(false)
    }
  }

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="step-up-title"
    >
      <div className="absolute inset-0 bg-ink/50 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div
        ref={ref}
        className="relative w-full max-w-md rounded-xl border border-hairline bg-surface shadow-crp-lg p-6 animate-scale-in"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-primary/10 grid place-items-center">
              <Fingerprint className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div>
              <h2 id="step-up-title" className="text-display text-lg font-bold text-ink">
                Confirm it&apos;s you
              </h2>
              <p className="text-xs text-ink-3">Passkey step-up required for {actionName}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="text-ink-4 hover:text-ink" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-4 rounded-lg border border-hairline bg-surface-2 p-4">
          <p className="text-sm text-ink-2">
            This is a sensitive action. Use your passkey to verify your identity before continuing.
          </p>
        </div>

        {error && (
          <div role="alert" data-testid="step-up-error" className="mt-4 flex items-start gap-2 rounded-lg border border-danger/20 bg-danger/5 p-3 text-sm text-danger">
            <ShieldAlert className="h-4 w-4 shrink-0 mt-0.5" aria-hidden="true" />
            {error}
          </div>
        )}

        <div className="mt-6 flex flex-col-reverse sm:flex-row sm:justify-end gap-3">
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant="primary"
            iconLeft={loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Fingerprint className="h-4 w-4" />}
            onClick={verify}
            disabled={loading}
            loading={loading}
          >
            Verify with passkey
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
