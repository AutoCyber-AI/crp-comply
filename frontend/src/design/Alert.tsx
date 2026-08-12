import type { ReactNode } from 'react'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle, Info, XCircle, X } from 'lucide-react'

type AlertTone = 'info' | 'success' | 'warning' | 'danger'

export interface AlertProps {
  tone?: AlertTone
  title?: string
  children: ReactNode
  onDismiss?: () => void
  className?: string
  role?: 'alert' | 'status'
}

const ICONS: Record<AlertTone, typeof Info> = {
  info: Info,
  success: CheckCircle,
  warning: AlertTriangle,
  danger: XCircle,
}

export function Alert({
  tone = 'info',
  title,
  children,
  onDismiss,
  className,
  role = tone === 'danger' ? 'alert' : 'status',
}: AlertProps) {
  const Icon = ICONS[tone]
  return (
    <div
      role={role}
      aria-live={tone === 'danger' ? 'assertive' : 'polite'}
      className={clsx(
        'rounded-lg border p-4 flex items-start gap-3',
        tone === 'info' && 'bg-surface-2 border-hairline text-ink',
        tone === 'success' && 'bg-success-muted border-success/20 text-ink',
        tone === 'warning' && 'bg-warning-muted border-warning/20 text-ink',
        tone === 'danger' && 'bg-danger-muted border-danger/20 text-ink',
        className,
      )}
    >
      <Icon
        className={clsx(
          'shrink-0 h-5 w-5 mt-0.5',
          tone === 'info' && 'text-ink-3',
          tone === 'success' && 'text-success',
          tone === 'warning' && 'text-warning',
          tone === 'danger' && 'text-danger',
        )}
        aria-hidden="true"
      />
      <div className="flex-1 min-w-0">
        {title && <h4 className="text-sm font-semibold">{title}</h4>}
        <div className={clsx('text-sm', tone === 'info' ? 'text-ink-2' : 'text-ink-3')}>{children}</div>
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-ink-4 hover:text-ink"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}
