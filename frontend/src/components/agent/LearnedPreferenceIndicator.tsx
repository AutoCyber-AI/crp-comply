import { useState } from 'react'
import { Sparkles, X, SlidersHorizontal } from 'lucide-react'
import type { AutonomyLevel, UserPreferenceProfile } from '../../lib/api'
import { Button, Chip } from '../../design/primitives'
import { AutonomyDial } from './AutonomyDial'

interface LearnedPreferenceIndicatorProps {
  preferences: UserPreferenceProfile
  onUpdate: (update: { preferred_autonomy: AutonomyLevel }) => void
}

const depthLabels: Record<string, string> = {
  brief: 'Brief',
  standard: 'Standard',
  thorough: 'Thorough',
}

const autonomyShort: Record<AutonomyLevel, string> = {
  suggest: 'Suggest',
  draft: 'Draft',
  autonomous_with_checkpoints: 'Auto+CP',
  full: 'Full',
}

export function LearnedPreferenceIndicator({ preferences, onUpdate }: LearnedPreferenceIndicatorProps) {
  const [open, setOpen] = useState(false)
  const [draftAutonomy, setDraftAutonomy] = useState(preferences.preferred_autonomy)

  const hasLearned =
    preferences.explicit_feedback_count > 0 || preferences.implicit_signal_count > 0

  return (
    <div className="relative inline-flex items-center gap-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-surface px-2.5 py-1 text-xs text-ink-2 hover:bg-surface-2 transition-colors"
        aria-expanded={open}
      >
        <Sparkles className={cn('h-3 w-3', hasLearned ? 'text-primary' : 'text-ink-4')} aria-hidden="true" />
        <span>Depth {depthLabels[preferences.preferred_depth] ?? preferences.preferred_depth}</span>
        <span className="text-hairline">·</span>
        <span>{autonomyShort[preferences.preferred_autonomy]}</span>
      </button>
      {hasLearned && (
        <Chip tone="primary" className="text-[10px]">
          Learned
        </Chip>
      )}
      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 rounded-xl border border-hairline bg-surface shadow-crp-lg p-4 animate-fade-in">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink-1">
              <SlidersHorizontal className="h-4 w-4 text-primary" aria-hidden="true" />
              Your preferences
            </div>
            <button type="button" onClick={() => setOpen(false)} className="text-ink-4 hover:text-ink" aria-label="Close">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-ink-3 mb-1.5">Default autonomy</label>
              <AutonomyDial value={draftAutonomy} onChange={setDraftAutonomy} />
            </div>
            <div className="flex items-center justify-between text-xs text-ink-3">
              <span>Explicit feedback</span>
              <span className="font-medium text-ink-1">{preferences.explicit_feedback_count}</span>
            </div>
            <div className="flex items-center justify-between text-xs text-ink-3">
              <span>Implicit signals</span>
              <span className="font-medium text-ink-1">{preferences.implicit_signal_count}</span>
            </div>
            <Button
              size="sm"
              variant="primary"
              className="w-full"
              onClick={() => {
                onUpdate({ preferred_autonomy: draftAutonomy })
                setOpen(false)
              }}
            >
              Save default
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function cn(...classes: (string | false | undefined)[]) {
  return classes.filter(Boolean).join(' ')
}
