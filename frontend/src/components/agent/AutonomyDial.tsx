import clsx from 'clsx'
import { Lightbulb, FileText, ShieldCheck, Zap } from 'lucide-react'
import type { AutonomyLevel } from '../../lib/api'

const LEVELS: { value: AutonomyLevel; label: string; description: string; icon: React.ReactNode }[] = [
  {
    value: 'suggest',
    label: 'Suggest',
    description: 'Recommend only — you draft final outputs.',
    icon: <Lightbulb className="h-4 w-4" />,
  },
  {
    value: 'draft',
    label: 'Draft',
    description: 'Generate a draft for you to edit and approve.',
    icon: <FileText className="h-4 w-4" />,
  },
  {
    value: 'autonomous_with_checkpoints',
    label: 'Autonomous with Checkpoints',
    description: 'Runs independently but pauses at sensitive actions.',
    icon: <ShieldCheck className="h-4 w-4" />,
  },
  {
    value: 'full',
    label: 'Full',
    description: 'Execute end-to-end with only logs for review.',
    icon: <Zap className="h-4 w-4" />,
  },
]

interface AutonomyDialProps {
  value: AutonomyLevel
  onChange: (value: AutonomyLevel) => void
  disabled?: boolean
}

export function AutonomyDial({ value, onChange, disabled = false }: AutonomyDialProps) {
  const idx = LEVELS.findIndex((l) => l.value === value)
  return (
    <div className={clsx('space-y-2', disabled && 'opacity-70 pointer-events-none')}>
      <div className="relative h-2 rounded-full bg-surface-3">
        <div
          className="absolute top-0 left-0 h-2 rounded-full bg-gradient-to-r from-primary to-accent transition-all"
          style={{ width: `${(idx / (LEVELS.length - 1)) * 100}%` }}
        />
        <div className="absolute inset-0 flex justify-between items-center">
          {LEVELS.map((l, i) => (
            <button
              key={l.value}
              type="button"
              disabled={disabled}
              onClick={() => onChange(l.value)}
              className={clsx(
                'h-4 w-4 -ml-2 rounded-full border-2 transition-colors',
                i <= idx ? 'border-primary bg-primary' : 'border-hairline bg-surface',
                disabled && 'cursor-not-allowed opacity-60',
              )}
              aria-label={l.label}
            />
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {LEVELS.map((l) => {
          const active = l.value === value
          return (
            <button
              key={l.value}
              type="button"
              disabled={disabled}
              onClick={() => onChange(l.value)}
              className={clsx(
                'flex items-start gap-3 rounded-lg border p-3 text-left transition-colors',
                active
                  ? 'border-primary bg-primary/5 text-ink-1'
                  : 'border-hairline bg-surface hover:bg-surface-2 text-ink-2',
                disabled && 'cursor-not-allowed opacity-60',
              )}
            >
              <div
                className={clsx(
                  'mt-0.5 shrink-0',
                  active ? 'text-primary' : 'text-ink-4',
                )}
              >
                {l.icon}
              </div>
              <div>
                <div className="text-sm font-semibold">{l.label}</div>
                <div className="text-xs text-ink-3 mt-0.5">{l.description}</div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
