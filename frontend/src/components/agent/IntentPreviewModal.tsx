import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Play, AlertTriangle, CheckCircle2, HelpCircle } from 'lucide-react'
import type { AutonomyLevel, TailoringPlan } from '../../lib/api'
import { Button, Chip } from '../../design/primitives'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import { AutonomyDial } from './AutonomyDial'
import { qualitativeConfidence, confidenceTone } from '../../lib/confidence'
import clsx from 'clsx'

export interface IntentPreviewModalProps {
  open: boolean
  plan: TailoringPlan
  autonomy: AutonomyLevel
  onClose: () => void
  onApprove: (autonomy: AutonomyLevel) => void
  estimate?: { tokens?: number; usd?: number }
}

export function IntentPreviewModal({
  open,
  plan,
  autonomy,
  onClose,
  onApprove,
  estimate,
}: IntentPreviewModalProps) {
  const [runAutonomy, setRunAutonomy] = useState(autonomy)
  const ref = useFocusTrap<HTMLDivElement>({ active: open, onEscape: onClose })

  useEffect(() => {
    if (open) setRunAutonomy(autonomy)
  }, [open, autonomy])

  useEffect(() => {
    if (!open) return
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  if (!open) return null

  const confidenceLabel = qualitativeConfidence(
    plan.should_produce === true ? 0.9 : plan.should_produce === 'uncertain' ? 0.5 : 0.2,
  )
  const pendingCount = plan.pending_questions.length
  const willCheckpoint = runAutonomy === 'autonomous_with_checkpoints' && pendingCount > 0

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="intent-title"
    >
      <div className="absolute inset-0 bg-ink/50 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div
        ref={ref}
        className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-xl border border-hairline bg-surface shadow-crp-lg p-6 animate-scale-in"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-wider text-ink-3 mb-1">Intent preview</div>
            <h2 id="intent-title" className="text-display text-xl font-bold text-ink">
              {plan.should_produce === true ? 'Ready to generate' : plan.should_produce === 'uncertain' ? 'Generation is uncertain' : 'Not applicable'}
            </h2>
          </div>
          <button type="button" onClick={onClose} className="text-ink-4 hover:text-ink" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>

        <p className="mt-2 text-sm text-ink-2">{plan.why}</p>

        <div className="mt-5 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat label="Sections" value={String(plan.applicable_sections.length)} />
          <Stat label="Skipped" value={String(plan.skipped_sections.length)} />
          <Stat label="Confidence">
            <Chip tone={confidenceTone(confidenceLabel)}>{confidenceLabel}</Chip>
          </Stat>
          <Stat label="Est. tokens" value={estimate?.tokens ? `${estimate.tokens.toLocaleString()}` : '—'} />
        </div>

        {plan.applicable_sections.length > 0 && (
          <div className="mt-5">
            <h3 className="text-sm font-semibold text-ink-1 mb-2">Will generate</h3>
            <ul className="space-y-1.5">
              {plan.applicable_sections.slice(0, 6).map((s) => (
                <li key={s.id} className="flex items-start gap-2 text-sm text-ink-2">
                  <CheckCircle2 className="h-4 w-4 text-success shrink-0 mt-0.5" aria-hidden="true" />
                  {s.title}
                </li>
              ))}
              {plan.applicable_sections.length > 6 && (
                <li className="text-xs text-ink-3 pl-6">
                  +{plan.applicable_sections.length - 6} more
                </li>
              )}
            </ul>
          </div>
        )}

        {plan.skipped_sections.length > 0 && (
          <div className="mt-4 rounded-lg border border-hairline bg-surface-2 p-3">
            <h3 className="text-sm font-semibold text-ink-1 mb-1 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-warning" aria-hidden="true" />
              Skipped sections
            </h3>
            <ul className="space-y-1">
              {plan.skipped_sections.slice(0, 4).map((s) => (
                <li key={s.section_id} className="text-xs text-ink-3">
                  <span className="font-medium text-ink-2">{s.title}:</span> {s.reason}
                </li>
              ))}
            </ul>
          </div>
        )}

        {pendingCount > 0 && (
          <div className="mt-4 rounded-lg border border-hairline bg-surface-2 p-3">
            <h3 className="text-sm font-semibold text-ink-1 mb-1 flex items-center gap-2">
              <HelpCircle className="h-4 w-4 text-primary" aria-hidden="true" />
              {pendingCount} pending question{pendingCount > 1 ? 's' : ''}
            </h3>
            <ul className="space-y-1">
              {plan.pending_questions.slice(0, 3).map((q) => (
                <li key={q.key} className="text-xs text-ink-3">{q.question}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-6 border-t border-hairline pt-5">
          <label className="block text-sm font-semibold text-ink-1 mb-2">Autonomy level</label>
          <AutonomyDial value={runAutonomy} onChange={setRunAutonomy} />
          <p className="mt-2 text-xs text-ink-3">
            Choose how much oversight you want for this run. Your default can be changed in Settings.
          </p>
        </div>

        {willCheckpoint && (
          <div className="mt-4 text-xs text-ink-3 bg-warning/10 border border-warning/20 rounded-lg p-3">
            This run will pause for your approval at {pendingCount} checkpoint{pendingCount > 1 ? 's' : ''} because autonomy is set to Autonomous.
          </div>
        )}

        <div className="mt-6 flex flex-col-reverse sm:flex-row sm:justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            iconLeft={<Play className="h-4 w-4" />}
            onClick={() => onApprove(runAutonomy)}
            disabled={plan.should_produce === false}
          >
            Approve and run
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function Stat({ label, value, children }: { label: string; value?: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface-2 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-ink-3">{label}</div>
      <div className={clsx('text-sm font-medium text-ink-1', !children && 'mt-0.5')}>
        {children ?? value}
      </div>
    </div>
  )
}
