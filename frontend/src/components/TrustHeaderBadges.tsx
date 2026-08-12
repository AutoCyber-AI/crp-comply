import { useEffect, useState } from 'react'
import { ShieldCheck, Lock, Fingerprint } from 'lucide-react'
import { getPasskeyStatus, getProviderStatus, type ProviderStatusResponse } from '../lib/api'
import { TrustBadge } from './TrustBadge'

const LOCAL_PROVIDERS = new Set(['local_worker', 'ollama', 'llamacpp'])

export function TrustHeaderBadges() {
  const [provider, setProvider] = useState<ProviderStatusResponse | null>(null)
  const [passkey, setPasskey] = useState<{ has_passkeys: boolean; mandatory: boolean } | null>(null)

  useEffect(() => {
    getProviderStatus().then(setProvider).catch(() => {})
    getPasskeyStatus().then(setPasskey).catch(() => {})
  }, [])

  const isLocal = provider?.configured && provider.provider && LOCAL_PROVIDERS.has(provider.provider)

  return (
    <div className="hidden lg:flex items-center gap-2">
      {passkey?.has_passkeys && (
        <TrustBadge icon={<Fingerprint className="h-3 w-3" />} label="Passkey verified" tone="success" />
      )}
      {isLocal && (
        <TrustBadge icon={<Lock className="h-3 w-3" />} label="0 bytes leave your network" tone="primary" />
      )}
      <TrustBadge icon={<ShieldCheck className="h-3 w-3" />} label="TLS 1.3" tone="neutral" />
    </div>
  )
}
