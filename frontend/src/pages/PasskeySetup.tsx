import { useEffect, useRef, useState } from 'react'
import { useAuth, useUser } from '@clerk/react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Shield, Fingerprint, Loader2, AlertTriangle, Check, KeyRound } from 'lucide-react'
import { checkPasskeyStatus, registerPasskey, verifyPasskey } from '../lib/passkey'

type SetupStatus = 'checking' | 'no_keys' | 'has_keys' | 'registered'

export default function PasskeySetup() {
  const { isLoaded, isSignedIn, getToken } = useAuth()
  const { user } = useUser()
  const navigate = useNavigate()
  const [status, setStatus] = useState<SetupStatus>('checking')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const busyRef = useRef(false)

  // Check whether the user already has an enrolled passkey, but do not
  // auto-trigger a WebAuthn ceremony on mount - browsers require a user
  // gesture and an unprompted ceremony often times out.
  useEffect(() => {
    document.title = 'Set up passkey - CRP Comply'
    if (!isLoaded || !isSignedIn) return

    const tokenGetter = () => getToken({ template: 'crp-comply' })

    async function checkStatus() {
      if (busyRef.current) return
      busyRef.current = true
      setLoading(true)
      setError(null)
      try {
        const result = await checkPasskeyStatus(tokenGetter)
        setStatus(result.has_passkeys ? 'has_keys' : 'no_keys')
      } catch (err) {
        console.error(err)
        setError(err instanceof Error ? err.message : String(err ?? 'Could not check passkey status'))
      } finally {
        busyRef.current = false
        setLoading(false)
      }
    }

    checkStatus()
  }, [isLoaded, isSignedIn, getToken])

  if (!isLoaded) {
    return (
      <div className="h-screen grid place-items-center bg-gray-50">
        <Loader2 className="h-6 w-6 animate-spin text-gray-600" />
      </div>
    )
  }

  if (!isSignedIn) {
    return <Navigate to="/sign-in?redirect_url=/passkeys/setup" replace />
  }

  async function onVerify() {
    if (busyRef.current) return
    busyRef.current = true
    setLoading(true)
    setError(null)
    try {
      const tokenGetter = () => getToken({ template: 'crp-comply' })
      await verifyPasskey(tokenGetter)
      navigate('/app', { replace: true })
    } catch (err) {
      if (!isCancellation(err)) {
        setError(err instanceof Error ? err.message : String(err ?? 'Could not verify passkey'))
      }
    } finally {
      busyRef.current = false
      setLoading(false)
    }
  }

  async function onRegister() {
    if (busyRef.current) return
    busyRef.current = true
    setLoading(true)
    setError(null)
    try {
      const tokenGetter = () => getToken({ template: 'crp-comply' })
      const result = await registerPasskey(
        tokenGetter,
        user?.primaryEmailAddress?.emailAddress || 'CRP Comply device',
        user?.fullName || user?.primaryEmailAddress?.emailAddress || 'CRP Comply user',
      )
      if (result.alreadyRegistered || result.registered) {
        setStatus('registered')
      }
      await verifyPasskey(tokenGetter)
      navigate('/app', { replace: true })
    } catch (err) {
      if (!isCancellation(err)) {
        setError(err instanceof Error ? err.message : String(err ?? 'Could not register passkey'))
      }
    } finally {
      busyRef.current = false
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center px-4">
      <div className="max-w-md w-full rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 rounded-xl bg-green-100 text-green-700">
            <Shield className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Set up passkey</h1>
            <p className="text-sm text-gray-500">Mandatory phishing-resistant MFA</p>
          </div>
        </div>

        <p className="text-sm text-gray-600 mb-6 leading-relaxed">
          CRP Comply requires a passkey as a second factor. Your private key never leaves your
          device - use your device's built-in authenticator (PIN, fingerprint, face recognition)
          or a hardware security key.
        </p>

        {error && (
          <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {status === 'registered' && (
          <div className="mb-6 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700 flex items-center gap-2">
            <Check className="w-4 h-4" />
            Passkey registered - verifying session…
          </div>
        )}

        {status === 'checking' ? (
          <div className="flex items-center justify-center gap-2 py-3 text-sm text-gray-600">
            <Loader2 className="w-4 h-4 animate-spin" />
            Checking for existing passkeys…
          </div>
        ) : status === 'has_keys' ? (
          <div className="space-y-3">
            <button
              type="button"
              onClick={onVerify}
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-gray-900 text-white font-semibold hover:bg-gray-800 disabled:opacity-50 transition"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Fingerprint className="w-4 h-4" />}
              {loading ? 'Verifying…' : 'Verify with passkey'}
            </button>
            <button
              type="button"
              onClick={() => setStatus('no_keys')}
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg border border-gray-200 text-gray-700 font-medium hover:bg-gray-50 disabled:opacity-50 transition"
            >
              <KeyRound className="w-4 h-4" />
              Register a different device
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <button
              type="button"
              onClick={onRegister}
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-gray-900 text-white font-semibold hover:bg-gray-800 disabled:opacity-50 transition"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Fingerprint className="w-4 h-4" />}
              {loading ? 'Working…' : status === 'registered' ? 'Passkey ready' : 'Create passkey'}
            </button>
            {status === 'no_keys' && (
              <p className="text-xs text-gray-500 text-center">
                You can register additional passkeys later from your workspace settings.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function isCancellation(err: unknown): boolean {
  if (err instanceof Error) {
    return /cancelled|abort|cancelling|timed out|not allowed/i.test(err.message)
  }
  return false
}
