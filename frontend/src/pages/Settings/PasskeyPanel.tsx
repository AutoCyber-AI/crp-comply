import { useCallback } from 'react'
import { useAuth } from '@clerk/react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Fingerprint, Loader2, Trash2, AlertTriangle, Check, Shield, Plus } from 'lucide-react'
import { listPasskeys, deletePasskey, registerPasskey } from '@/lib/passkey'
import { useOptimisticMutation } from '@/lib/mutations'
import { PasskeyStepUpModal } from '@/components/PasskeyStepUpModal'
import { useStepUp } from '@/hooks/useStepUp'

interface PasskeyCredential {
  credential_id: string
  device_name?: string
  created_at?: number
  last_used_at?: number | null
  revoked?: boolean
}

export function PasskeyPanel() {
  const { getToken } = useAuth()
  const tokenGetter = useCallback(() => getToken({ template: 'crp-comply' }), [getToken])
  const stepUp = useStepUp({ actionName: 'Delete passkey' })

  const credentialsQuery = useQuery({
    queryKey: ['passkeys'],
    queryFn: async () => {
      const result = (await listPasskeys(tokenGetter)) as { credentials: PasskeyCredential[] }
      return result.credentials || []
    },
  })

  const deleteMut = useOptimisticMutation<PasskeyCredential[], string, string>({
    mutationFn: async (credentialId: string) => {
      await deletePasskey(tokenGetter, credentialId)
      return credentialId
    },
    queryKey: ['passkeys'],
    updateFn: (old, id) => (old ?? []).filter((c) => c.credential_id !== id),
  })

  const registerMut = useMutation({
    mutationFn: () => registerPasskey(tokenGetter),
    onSuccess: () => credentialsQuery.refetch(),
  })

  const credentials = credentialsQuery.data ?? []
  const loading = credentialsQuery.isLoading
  const error = credentialsQuery.error
    ? credentialsQuery.error instanceof Error
      ? credentialsQuery.error.message
      : 'Could not load passkeys'
    : null
  const success = registerMut.data?.registered ? 'New passkey registered' : null

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-ink flex items-center gap-2">
            <Fingerprint className="w-5 h-5" />
            Passkeys
          </h2>
          <p className="mt-1 text-sm text-ink-3">
            Manage the phishing-resistant passkeys used to secure your CRP Comply account.
          </p>
        </div>
        <button
          type="button"
          onClick={() => registerMut.mutate()}
          disabled={registerMut.isPending}
          className="inline-flex items-center gap-1.5 rounded-lg bg-ink px-3 py-2 text-sm font-medium text-surface hover:bg-ink/90 disabled:opacity-50 transition"
        >
          {registerMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
          Register new passkey
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {success && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700 flex items-start gap-2">
          <Check className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{success}</span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-ink-3">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading passkeys…
        </div>
      ) : credentials.length === 0 ? (
        <div className="rounded-xl border border-hairline bg-surface-2 p-6 text-center">
          <Shield className="w-8 h-8 mx-auto text-ink-3 mb-3" />
          <p className="text-sm text-ink font-medium">No passkeys registered</p>
          <p className="text-xs text-ink-3 mt-1">
            Add a passkey to protect your account with phishing-resistant MFA.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-hairline overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 text-left text-xs uppercase tracking-wide text-ink-3">
              <tr>
                <th className="px-4 py-3 font-medium">Device</th>
                <th className="px-4 py-3 font-medium">Registered</th>
                <th className="px-4 py-3 font-medium">Last used</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {credentials.map((cred) => (
                <tr key={cred.credential_id} className="bg-surface">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Fingerprint className="w-4 h-4 text-ink-3" />
                      <span className="font-medium text-ink">
                        {cred.device_name || 'Passkey'}
                      </span>
                    </div>
                    <code className="text-[10px] text-ink-3 block mt-0.5 truncate max-w-[200px]">
                      {cred.credential_id}
                    </code>
                  </td>
                  <td className="px-4 py-3 text-ink-3">
                    {cred.created_at ? formatDate(cred.created_at) : '-'}
                  </td>
                  <td className="px-4 py-3 text-ink-3">
                    {cred.last_used_at ? formatDate(cred.last_used_at) : 'Never'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() =>
                        stepUp.requireStepUp(() => deleteMut.mutate(cred.credential_id))
                      }
                      className="inline-flex items-center gap-1 text-red-600 hover:text-red-700 text-xs font-medium"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <PasskeyStepUpModal
        open={stepUp.open}
        actionName={stepUp.actionName}
        onClose={stepUp.close}
        onVerified={stepUp.onVerified}
      />
    </div>
  )
}

function formatDate(ts: number): string {
  try {
    return new Date(ts * 1000).toLocaleString()
  } catch {
    return String(ts)
  }
}
