import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { AlertTriangle, X } from 'lucide-react'
import { Button } from './primitives'
import { useFocusTrap } from '../hooks/useFocusTrap'

export interface ConfirmDialogProps {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'warning' | 'primary'
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'danger',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useFocusTrap<HTMLDivElement>({ active: open, onEscape: onCancel })

  useEffect(() => {
    if (!open) return
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      aria-describedby="confirm-desc"
    >
      <div
        className="absolute inset-0 bg-ink/50 backdrop-blur-sm"
        onClick={onCancel}
        aria-hidden="true"
      />
      <div
        ref={ref}
        className="relative w-full max-w-md rounded-xl border border-hairline bg-surface shadow-crp-lg p-6 animate-scale-in"
      >
        <div className="flex items-start gap-4">
          <div
            className={clsx(
              'shrink-0 h-10 w-10 rounded-full grid place-items-center',
              variant === 'danger' && 'bg-danger-muted text-danger',
              variant === 'warning' && 'bg-warning-muted text-warning',
              variant === 'primary' && 'bg-primary-muted text-ink',
            )}
          >
            <AlertTriangle className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 id="confirm-title" className="text-base font-semibold text-ink">
              {title}
            </h3>
            <p id="confirm-desc" className="mt-1 text-sm text-ink-3">
              {description}
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="shrink-0 text-ink-4 hover:text-ink"
            aria-label="Cancel"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="mt-6 flex flex-col-reverse sm:flex-row sm:justify-end gap-3">
          <Button variant="ghost" onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button
            variant={variant === 'primary' ? 'primary' : 'danger'}
            onClick={() => {
              onConfirm()
              onCancel()
            }}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
