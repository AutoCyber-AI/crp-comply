import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Key, Plus, Trash2, Copy, Check } from 'lucide-react'
import { ConfirmDialog } from '@/design/ConfirmDialog'
import {
  createApiKey,
  listApiKeys,
  revokeApiKey,
  type APIKeyResponse,
} from '@/lib/api'
import { PasskeyStepUpModal } from '@/components/PasskeyStepUpModal'
import { useStepUp } from '@/hooks/useStepUp'

export function ApiKeysPanel() {
  const [name, setName] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [confirm, setConfirm] = useState<APIKeyResponse | null>(null)
  const stepUp = useStepUp({ actionName: 'API key changes' })
  const queryClient = useQueryClient()

  const keysQuery = useQuery({
    queryKey: ['apikeys'],
    queryFn: listApiKeys,
  })

  const createMutation = useMutation({
    mutationFn: createApiKey,
    onSuccess: (data) => {
      setNewKey(data.key)
      setName('')
      queryClient.invalidateQueries({ queryKey: ['apikeys'] })
    },
  })

  const revokeMutation = useMutation({
    mutationFn: revokeApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apikeys'] })
    },
  })

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    stepUp.requireStepUp(() => createMutation.mutate({ name }))
  }

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <Key className="h-5 w-5" /> API Keys
      </h2>

      {newKey && (
        <div className="mb-4 p-3 rounded-lg bg-green-50 border border-green-200" role="status">
          <p className="text-sm text-green-800 font-medium mb-1">
            Key created! Copy it to a secrets manager - it won&apos;t be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code className="text-xs bg-white px-2 py-1 rounded border flex-1 break-all">
              {newKey}
            </code>
            <button
              type="button"
              onClick={() => handleCopy(newKey)}
              aria-label={copied ? 'Copied' : 'Copy key'}
              className="btn-secondary text-xs py-1 px-2"
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
        </div>
      )}

      <form onSubmit={handleCreate} className="flex gap-2 mb-4">
        <label htmlFor="api-key-name" className="sr-only">Key name</label>
        <input
          id="api-key-name"
          type="text"
          className="input flex-1"
          placeholder="Key name (e.g. 'my-laptop', 'staging')"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        {/* Tier is inherited from the user's account; per-key tier override
            is not supported. The dropdown that previously appeared here
            implied otherwise and produced free-tier keys regardless of the
            selection. */}
        <button
          type="submit"
          disabled={createMutation.isPending}
          className="btn-primary flex items-center gap-1 disabled:opacity-50"
        >
          <Plus className="h-4 w-4" /> Create
        </button>
      </form>

      {keysQuery.isLoading && <p className="text-sm text-gray-600">Loading keys...</p>}
      {keysQuery.isError && (
        <p className="text-sm text-red-600">Failed to load keys (is the backend running?)</p>
      )}
      {keysQuery.data && keysQuery.data.length === 0 && (
        <p className="text-sm text-gray-600">No API keys created yet.</p>
      )}
      {keysQuery.data && keysQuery.data.length > 0 && (
        <div className="border rounded-lg overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[560px]">
            <caption className="sr-only">Your API keys</caption>
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-gray-700" scope="col">Name</th>
                <th className="text-left px-4 py-2 font-medium text-gray-700" scope="col">Tier</th>
                <th className="text-left px-4 py-2 font-medium text-gray-700" scope="col">Prefix</th>
                <th className="text-left px-4 py-2 font-medium text-gray-700" scope="col">Created</th>
                <th className="text-right px-4 py-2 font-medium text-gray-700" scope="col">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {keysQuery.data.map((k: APIKeyResponse) => (
                <tr key={k.id}>
                  <td className="px-4 py-2">{k.name}</td>
                  <td className="px-4 py-2">
                    <TierBadge tier={k.tier} />
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">{k.key_prefix}...</td>
                  <td className="px-4 py-2 text-gray-600">
                    {new Date(k.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => stepUp.requireStepUp(() => setConfirm(k))}
                      disabled={revokeMutation.isPending}
                      className="text-red-600 hover:text-red-800"
                      title="Revoke key"
                      aria-label={`Revoke key ${k.name}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={!!confirm}
        title="Revoke API key"
        description={`Revoke "${confirm?.name || ''}"? Any integrations using this key will stop working. This cannot be undone.`}
        variant="danger"
        confirmLabel="Revoke"
        onConfirm={() => {
          if (confirm) revokeMutation.mutate(confirm.id)
        }}
        onCancel={() => setConfirm(null)}
      />
      <PasskeyStepUpModal
        open={stepUp.open}
        actionName={stepUp.actionName}
        onClose={stepUp.close}
        onVerified={stepUp.onVerified}
      />
    </div>
  )
}

const TIER_DISPLAY: Record<string, string> = {
  free: 'Free',
  pro: 'Starter',
  team: 'Scale',
  scale: 'Scale',
  starter: 'Starter',
  enterprise: 'Enterprise',
  cloud: 'Cloud',
}

function TierBadge({ tier }: { tier: string }) {
  const key = tier.toLowerCase()
  const styles: Record<string, string> = {
    free: 'bg-gray-100 text-gray-700',
    pro: 'bg-blue-100 text-blue-700',
    team: 'bg-blue-100 text-blue-700',
    scale: 'bg-blue-100 text-blue-700',
    starter: 'bg-blue-100 text-blue-700',
    enterprise: 'bg-purple-100 text-purple-700',
    cloud: 'bg-amber-100 text-amber-700',
  }
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded ${styles[key] ?? 'bg-gray-100 text-gray-700'}`}>
      {TIER_DISPLAY[key] ?? tier.toUpperCase()}
    </span>
  )
}
