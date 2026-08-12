import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { HardDrive, Cloud, Lock, Check } from 'lucide-react'
import {
  getMe,
  getStoragePreference,
  setStoragePreference,
} from '@/lib/api'
import { TrustBadge } from '@/components/TrustBadge'

/**
 * StoragePanel - let users choose where the artefacts CRP Comply
 * generates (binders, DPIAs, evidence bundles) actually live.
 *
 * Free tier is locked to ``local`` (browser/device only). Paid tiers
 * may opt into the hosted Railway volume, which gets nightly encrypted
 * backups (see ``docs/VOLUME_PERSISTENCE.md`` and ``railway.toml``).
 *
 * Hosted-mode availability is determined server-side via
 * ``StoragePreference.cloud_available`` (the backend gates on the
 * caller's tier + ``CRP_COMPLY_CLOUD_DATA_DIR``), so the UI does not
 * have to keep its own copy of the entitlement matrix.
 */
export function StoragePanel() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['storage-preference'],
    queryFn: getStoragePreference,
  })
  const me = useQuery({ queryKey: ['me'], queryFn: getMe })
  const [error, setError] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: (mode: 'local' | 'cloud') => setStoragePreference(mode),
    onSuccess: () => {
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['storage-preference'] })
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : 'Failed to update storage preference')
    },
  })

  const tier = me.data?.tier?.toLowerCase()
  const cloudAvailable = !!data?.cloud_available
  const currentMode = data?.storage_mode ?? 'local'
  const onFree = tier === 'free'

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-start justify-between mb-1 gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <HardDrive className="h-4 w-4" />
            Where your deliverables are stored
          </h2>
          <div className="mt-2">
            <TrustBadge icon={<Lock className="h-3 w-3" />} label="AES-256 at rest" tone="success" />
          </div>
          <p className="mt-1 text-sm text-gray-600">
            Choose whether artefacts CRP Comply generates - binders, DPIAs, evidence
            bundles - live on your device or on our hosted volume.
          </p>
        </div>
        <NavLink
          to="/pricing"
          className="hidden sm:inline-flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-900 whitespace-nowrap"
        >
          Compare tiers <ExternalLinkIcon />
        </NavLink>
      </div>

      {isLoading && (
        <div className="mt-5 text-sm text-gray-600">Loading your storage settings…</div>
      )}
      {isError && (
        <div className="mt-5 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
          Couldn't load storage preference.{' '}
          <button type="button" onClick={() => refetch()} className="underline">Retry</button>
        </div>
      )}

      {data && (
        <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-3">
          <StorageOption
            icon={HardDrive}
            label="Your device (local)"
            description="Artefacts download to your browser. Nothing about your deliverables is retained on our infrastructure beyond the active session."
            badge="Available on every plan"
            selected={currentMode === 'local'}
            disabled={mutation.isPending}
            onSelect={() => mutation.mutate('local')}
          />
          <StorageOption
            icon={Cloud}
            label="Hosted volume (cloud)"
            description="Tenant-isolated directory on our Railway volume, replicated nightly to Cloudflare R2 for off-region disaster recovery. Search across your full history from any device."
            badge={
              onFree
                ? 'Upgrade to Starter to unlock'
                : cloudAvailable
                  ? 'Available on your plan'
                  : 'Hosted storage not configured'
            }
            selected={currentMode === 'cloud'}
            disabled={mutation.isPending || !cloudAvailable}
            locked={!cloudAvailable}
            onSelect={() => mutation.mutate('cloud')}
          />
        </div>
      )}

      {data && (
        <div className="mt-5 rounded-lg bg-gray-50 p-4 text-xs text-gray-600 leading-relaxed">
          <div className="flex items-start gap-2">
            <Lock className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <div>
              <strong className="text-gray-900">Effective directory:</strong>{' '}
              <code className="font-mono text-gray-800">
                {currentMode === 'cloud' && data.cloud_data_dir
                  ? data.cloud_data_dir
                  : data.local_data_dir}
              </code>
              <br />
              {currentMode === 'cloud' ? (
                <>
                  Hosted artefacts are scoped to your tenant. A nightly job tars
                  the volume at 03:00 UTC and uploads the archive to our private
                  Cloudflare R2 bucket (<code className="font-mono">crp-comply-backups</code>)
                  for off-region disaster recovery - see{' '}
                  <NavLink to="/docs" className="underline">our volume-persistence guide</NavLink>.
                </>
              ) : (
                <>
                  Local mode means you control your evidence trail end-to-end. We can't
                  back it up for you, so make sure the device storing these files is part
                  of your own backup routine.
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
          {error}
        </div>
      )}
    </div>
  )
}

interface StorageOptionProps {
  icon: React.ComponentType<{ className?: string }>
  label: string
  description: string
  badge: string
  selected: boolean
  disabled: boolean
  locked?: boolean
  onSelect: () => void
}

function StorageOption({
  icon: Icon,
  label,
  description,
  badge,
  selected,
  disabled,
  locked,
  onSelect,
}: StorageOptionProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      className={[
        'text-left rounded-xl border p-4 transition-all',
        selected
          ? 'border-gray-900 bg-gray-50 ring-2 ring-gray-900/10'
          : 'border-gray-200 bg-white hover:border-gray-300',
        disabled && !selected ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer',
      ].join(' ')}
    >
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 shrink-0 rounded-lg bg-gray-900/5 flex items-center justify-center">
          <Icon className="h-4 w-4 text-gray-900" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-gray-900">{label}</h3>
            {selected && (
              <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5">
                <Check className="h-3 w-3" /> Selected
              </span>
            )}
            {locked && !selected && (
              <span className="inline-flex items-center gap-1 text-xs font-medium text-gray-600 bg-gray-100 border border-gray-200 rounded-full px-2 py-0.5">
                <Lock className="h-3 w-3" /> Locked
              </span>
            )}
          </div>
          <p className="mt-1.5 text-xs text-gray-600 leading-relaxed">{description}</p>
          <p className="mt-2 text-xs font-medium uppercase tracking-wide text-gray-600">
            {badge}
          </p>
        </div>
      </div>
    </button>
  )
}

function ExternalLinkIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="inline"
    >
      <path d="M15 3h6v6" />
      <path d="M10 14 21 3" />
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    </svg>
  )
}
