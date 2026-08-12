import type { ReactNode } from 'react'
import clsx from 'clsx'

type TrustTone = 'neutral' | 'success' | 'primary' | 'warning'

interface TrustBadgeProps {
  icon: ReactNode
  label: string
  tone?: TrustTone
  className?: string
}

export function TrustBadge({ icon, label, tone = 'neutral', className }: TrustBadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[11px] font-medium leading-none',
        tone === 'success' && 'border-success/30 bg-success/10 text-success',
        tone === 'primary' && 'border-primary/30 bg-primary/10 text-ink',
        tone === 'warning' && 'border-warning/30 bg-warning/10 text-warning',
        tone === 'neutral' && 'border-hairline bg-surface-2 text-ink-3',
        className,
      )}
    >
      <span className="shrink-0" aria-hidden="true">{icon}</span>
      {label}
    </span>
  )
}
