import { CheckCircle2, SkipForward, Wrench } from 'lucide-react'
import { Chip, Tooltip } from '../../design/primitives'

export interface ClarifierCardProps {
  priority?: 'high' | 'medium' | 'low'
  skippable?: boolean
  onSkip?: () => void
  onOption?: (option: string) => void
  action?: 'probe' | 'confirm' | 'repair'
  options?: string[]
  loading?: boolean
  children: React.ReactNode
}

export function ClarifierCard({
  priority,
  skippable,
  onSkip,
  onOption,
  action = 'probe',
  options,
  loading,
  children,
}: ClarifierCardProps) {
  const isConfirm = action === 'confirm'
  const isRepair = action === 'repair'

  return (
    <>
      <div className="mb-2 flex items-center gap-2">
        {priority === 'high' && (
          <Chip tone="warning" className="!text-xs !font-bold">
            High priority question
          </Chip>
        )}
        {isConfirm && (
          <Chip tone="success" className="!text-xs !font-bold">
            <span className="flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" /> Confirm
            </span>
          </Chip>
        )}
        {isRepair && (
          <Chip tone="warning" className="!text-xs !font-bold">
            <span className="flex items-center gap-1">
              <Wrench className="h-3 w-3" /> Repair
            </span>
          </Chip>
        )}
      </div>
      <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{children}</div>
      {options && options.length > 0 && onOption && (
        <div className="mt-3 flex flex-wrap gap-2">
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => onOption(opt)}
              disabled={loading}
              className={`
                px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-50
                ${
                  isConfirm
                    ? 'border-success/40 bg-success/10 text-success hover:bg-success/20'
                    : isRepair
                    ? 'border-warning/40 bg-warning/10 text-warning hover:bg-warning/20'
                    : 'border-hairline bg-surface-2 text-ink-2 hover:bg-surface-3'
                }
              `}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
      {skippable && onSkip && (
        <div className="mt-2">
          <Tooltip label="Record as 'unknown' and let the agent continue with an explicit assumption" side="top">
            <button
              type="button"
              onClick={onSkip}
              disabled={loading}
              className="text-xs text-ink-3 hover:text-ink underline underline-offset-2 disabled:opacity-50 flex items-center gap-1"
            >
              <SkipForward className="h-3 w-3" /> Skip
            </button>
          </Tooltip>
        </div>
      )}
    </>
  )
}
