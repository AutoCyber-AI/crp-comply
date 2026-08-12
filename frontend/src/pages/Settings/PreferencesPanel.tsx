import { useEffect, useState } from 'react'
import { SlidersHorizontal, Loader2 } from 'lucide-react'
import { Card, Button, Chip } from '../../design/primitives'
import { AutonomyDial } from '../../components/agent'
import { getPreferences, updatePreferences, ApiError, type AutonomyLevel, type UserPreferenceProfile } from '../../lib/api'
import { useToast } from '../../components/toast/ToastProvider'

export function PreferencesPanel() {
  const toast = useToast()
  const [prefs, setPrefs] = useState<UserPreferenceProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [draftAutonomy, setDraftAutonomy] = useState<AutonomyLevel>('draft')

  useEffect(() => {
    getPreferences()
      .then((p) => {
        setPrefs(p)
        setDraftAutonomy(p.preferred_autonomy)
      })
      .catch((err) => {
        const msg = err instanceof ApiError ? err.message : String(err)
        toast.error('Could not load preferences', msg)
      })
      .finally(() => setLoading(false))
  }, [toast])

  const save = async () => {
    setSaving(true)
    try {
      const p = await updatePreferences({ preferred_autonomy: draftAutonomy })
      setPrefs(p)
      toast.success('Preferences saved', 'Your default autonomy level has been updated.')
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err)
      toast.error('Save failed', msg)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <Card className="!p-8 flex items-center justify-center gap-2 text-sm text-ink-3">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Loading preferences…
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-bold text-ink flex items-center gap-2">
          <SlidersHorizontal className="h-5 w-5 text-primary" aria-hidden="true" />
          Preferences
        </h2>
        <p className="mt-1 text-sm text-ink-3">
          Tune your default autonomy, depth, and other learned preferences.
        </p>
      </div>

      <Card className="!p-6 space-y-4">
        <div className="flex items-center justify-between">
          <label className="text-sm font-semibold text-ink-1">Default autonomy level</label>
          {prefs && (
            <Chip tone="primary">
              Learned from {prefs.explicit_feedback_count + prefs.implicit_signal_count} signal
              {prefs.explicit_feedback_count + prefs.implicit_signal_count === 1 ? '' : 's'}
            </Chip>
          )}
        </div>
        <AutonomyDial value={draftAutonomy} onChange={setDraftAutonomy} />
        <p className="text-xs text-ink-3">
          This controls how independently the agent acts when running recipes or answering follow-ups.
          You can always override it for an individual run.
        </p>
        <div className="flex justify-end pt-2">
          <Button variant="primary" onClick={save} loading={saving} disabled={draftAutonomy === prefs?.preferred_autonomy}>
            Save default
          </Button>
        </div>
      </Card>
    </div>
  )
}
