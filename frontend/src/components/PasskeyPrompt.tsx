import { useState } from 'react'
import { useAuth } from '@clerk/react'
import { Fingerprint, Loader2, AlertTriangle, X } from 'lucide-react'
import { verifyPasskey } from '../lib/passkey'
import { useFocusTrap } from '../hooks/useFocusTrap'

interface PasskeyPromptProps {
  onVerified: () => void
  onCancel?: () => void
  reason?: string
}

export default function PasskeyPrompt({ onVerified, onCancel, reason }: PasskeyPromptProps) {
  const { getToken } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ref = useFocusTrap<HTMLDivElement>({
    active: true,
    onEscape: onCancel,
  })

  async function onVerify() {
    setLoading(true)
    setError(null)
    try {
      await verifyPasskey(() => getToken({ template: 'crp-comply' }))
      onVerified()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'We could not verify your passkey. Your account is still safe - you can try again or use another authentication method.',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50 backdrop-blur-sm px-4">
      <div
        ref={ref}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="passkey-title"
        aria-describedby="passkey-desc"
        className="max-w-sm w-full rounded-2xl border border-gray-200 bg-white p-6 relative shadow-lg"
      >
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
            aria-label="Cancel"
          >
            <X className="w-4 h-4" />
          </button>
        )}
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 rounded-lg bg-green-100 text-green-700">
            <Fingerprint className="w-5 h-5" />
          </div>
          <h2 id="passkey-title" className="text-lg font-semibold text-gray-900">Verify with passkey</h2>
        </div>
        <p id="passkey-desc" className="text-sm text-gray-600 mb-6">
          {reason ||
            'This action requires a fresh passkey verification for security.'}
        </p>

        {error && (
          <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        <button
          type="button"
          onClick={onVerify}
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-gray-900 text-white font-semibold hover:bg-gray-800 disabled:opacity-50 transition"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Fingerprint className="w-4 h-4" />}
          {loading ? 'Verifying…' : 'Use passkey'}
        </button>
      </div>
    </div>
  )
}
