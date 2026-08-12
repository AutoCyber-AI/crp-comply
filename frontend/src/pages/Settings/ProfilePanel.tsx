import { useEffect, useRef, useState } from 'react'
import { Building2, Loader2 } from 'lucide-react'
import { useProfile, type OrgProfile, type Actor } from '@/lib/profile'
import { patchOrgProfile } from '@/lib/api'
import { useToast } from '@/components/toast/ToastProvider'
import { InfoTooltip } from '@/design/primitives'

const ACTOR_OPTIONS: { value: Actor | ''; label: string }[] = [
  { value: '', label: 'Select role…' },
  { value: 'provider', label: 'Provider' },
  { value: 'deployer', label: 'Deployer' },
  { value: 'importer', label: 'Importer' },
  { value: 'distributor', label: 'Distributor' },
  { value: 'authorised_representative', label: 'Authorised representative' },
  { value: 'gpai_provider', label: 'GPAI provider' },
]

const SAVE_DEBOUNCE_MS = 600

export function ProfilePanel() {
  const { profile, loading } = useProfile()
  const toast = useToast()
  const [draft, setDraft] = useState<OrgProfile>({})
  const [saving, setSaving] = useState(false)
  const touched = useRef(false)
  const timer = useRef<number | null>(null)

  // Sync from the server profile until the user starts editing.
  useEffect(() => {
    if (!loading && !touched.current) {
      setDraft(profile)
    }
  }, [profile, loading])

  // Flush any pending save when the panel unmounts.
  useEffect(() => {
    return () => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current)
        timer.current = null
      }
    }
  }, [])

  const flush = async (next: OrgProfile) => {
    setSaving(true)
    try {
      await patchOrgProfile(next as Record<string, unknown>)
      toast.success('Profile saved')
    } catch (err) {
      toast.error(
        'Failed to save profile',
        err instanceof Error ? err.message : 'Something went wrong',
      )
    } finally {
      setSaving(false)
    }
  }

  const patch = (changes: Partial<OrgProfile>) => {
    touched.current = true
    setDraft((prev) => {
      const next = { ...prev, ...changes }
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => flush(next), SAVE_DEBOUNCE_MS)
      return next
    })
  }

  const jurisdictionsValue = draft.jurisdictions?.join(', ') ?? ''

  return (
    <div className="card">
      <div className="flex items-start justify-between mb-1 gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Building2 className="h-5 w-5" />
            Organisation profile
          </h2>
          <p className="mt-1 text-sm text-gray-600">
            The facts you enter here drive recipe tailoring and the questions the compliance agent asks.
          </p>
        </div>
        {saving && (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-3">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving
          </span>
        )}
      </div>

      {loading && Object.keys(draft).length === 0 ? (
        <p className="mt-5 text-sm text-gray-600">Loading profile…</p>
      ) : (
        <div className="mt-5 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="md:col-span-2">
              <label htmlFor="profile-org-name" className="label">
                Organisation name
              </label>
              <input
                id="profile-org-name"
                type="text"
                className="input"
                value={draft.org_name ?? ''}
                onChange={(e) => patch({ org_name: e.target.value })}
                placeholder="Acme AI Ltd"
              />
            </div>

            <div>
              <label htmlFor="profile-actor" className="label">
                Your role under the AI Act
              </label>
              <select
                id="profile-actor"
                className="select"
                value={draft.actor ?? ''}
                onChange={(e) => {
                  const value = e.target.value as Actor | ''
                  patch({ actor: value === '' ? undefined : value })
                }}
              >
                {ACTOR_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="profile-jurisdictions" className="label">
                Jurisdictions (comma-separated)
              </label>
              <input
                id="profile-jurisdictions"
                type="text"
                className="input"
                value={jurisdictionsValue}
                onChange={(e) =>
                  patch({
                    jurisdictions: e.target.value
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="EU, UK, US"
              />
            </div>

            <div className="md:col-span-2">
              <label htmlFor="profile-system-category" className="label">
                System category
              </label>
              <input
                id="profile-system-category"
                type="text"
                className="input"
                value={draft.system_category ?? ''}
                onChange={(e) => patch({ system_category: e.target.value })}
                placeholder="e.g. CV screening, credit scoring"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <Checkbox
              label="High-risk system"
              info="Annex III of the EU AI Act lists high-risk use cases like recruitment, credit scoring, and biometric ID."
              checked={!!draft.is_high_risk}
              onChange={(v) => patch({ is_high_risk: v })}
            />
            <Checkbox
              label="GPAI provider"
              info="General-purpose AI provider - models that can be used for many different tasks (e.g. GPT-4, Llama)."
              checked={!!draft.is_gpai}
              onChange={(v) => patch({ is_gpai: v })}
            />
            <Checkbox
              label="Special-category data"
              info="Sensitive personal data such as health, biometrics, racial or ethnic origin, religion, or trade-union membership."
              checked={!!draft.special_categories}
              onChange={(v) => patch({ special_categories: v })}
            />
            <Checkbox
              label="Processes personal data"
              checked={!!draft.processes_personal_data}
              onChange={(v) => patch({ processes_personal_data: v })}
            />
            <Checkbox
              label="Biometric data"
              checked={!!draft.biometric}
              onChange={(v) => patch({ biometric: v })}
            />
            <Checkbox
              label="Synthetic content"
              info="Outputs that are generated rather than real (e.g. deepfakes, AI-generated images or text)."
              checked={!!draft.synthetic_content}
              onChange={(v) => patch({ synthetic_content: v })}
            />
            <Checkbox
              label="Deepfake capable"
              info="Your system can create or manipulate media that appears to show real people doing or saying things they did not."
              checked={!!draft.deepfake}
              onChange={(v) => patch({ deepfake: v })}
            />
            <Checkbox
              label="Automated decision-making"
              info="Decisions that produce legal or similarly significant effects on people without meaningful human involvement."
              checked={!!draft.automated_decision_making}
              onChange={(v) => patch({ automated_decision_making: v })}
            />
            <Checkbox
              label="Children users"
              checked={!!draft.children_users}
              onChange={(v) => patch({ children_users: v })}
            />
            <Checkbox
              label="ISO/IEC 42001 certified"
              checked={!!draft.iso_42001_certified}
              onChange={(v) => patch({ iso_42001_certified: v })}
            />
            <Checkbox
              label="ISO/IEC 27001 certified"
              checked={!!draft.iso_27001_certified}
              onChange={(v) => patch({ iso_27001_certified: v })}
            />
            <Checkbox
              label="SOC 2 certified"
              checked={!!draft.soc2_certified}
              onChange={(v) => patch({ soc2_certified: v })}
            />
          </div>
        </div>
      )}
    </div>
  )
}

function Checkbox({
  label,
  info,
  checked,
  onChange,
}: {
  label: string
  info?: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <label className="flex items-center gap-2.5 rounded-lg border border-hairline bg-surface p-3 cursor-pointer hover:border-ink-3 transition-colors">
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-hairline text-primary focus:ring-primary shrink-0"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="flex items-center gap-1.5 text-sm text-ink-2">
        {label}
        {info && <InfoTooltip label={info} />}
      </span>
    </label>
  )
}
