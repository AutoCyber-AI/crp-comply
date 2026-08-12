/**
 * Toast Notification System for CRP Comply
 *
 * Provides immediate visual feedback for user actions across the app.
 * Uses the CRP design tokens for consistent branding.
 *
 * Accessibility:
 *   - aria-live="polite" region so screen readers announce toasts
 *   - aria-atomic="true" so each toast is read as a unit
 *   - role="status" for info/success, role="alert" for error/warning
 *   - Hover pauses auto-dismiss so users have time to read
 *   - Dismissible via click or keyboard (Escape clears all)
 *   - Respects prefers-reduced-motion via global CSS
 */
import { createContext, useContext, useState, useEffect, useCallback, useRef, type ReactNode } from 'react'
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Info,
  X,
  Loader2,
} from 'lucide-react'
import clsx from 'clsx'

export type ToastType = 'success' | 'error' | 'warning' | 'info' | 'loading'

export interface Toast {
  id: string
  type: ToastType
  title: string
  message?: string
  duration?: number
  action?: { label: string; onClick: () => void }
}

interface ToastContextValue {
  toast: (toast: Omit<Toast, 'id'>) => string
  dismiss: (id: string) => void
  dismissAll: () => void
  success: (title: string, message?: string) => string
  error: (title: string, message?: string) => string
  warning: (title: string, message?: string) => string
  info: (title: string, message?: string) => string
  loading: (title: string, message?: string) => string
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within a ToastProvider')
  return ctx
}

const ICONS: Record<ToastType, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
  loading: Loader2,
}

const STYLES: Record<ToastType, { bg: string; border: string; icon: string; title: string; text: string; role: 'status' | 'alert' }> = {
  success: {
    bg: 'bg-success-muted',
    border: 'border-success/30',
    icon: 'text-success',
    title: 'text-success',
    text: 'text-ink-2',
    role: 'status',
  },
  error: {
    bg: 'bg-danger-muted',
    border: 'border-danger/30',
    icon: 'text-danger',
    title: 'text-danger',
    text: 'text-ink-2',
    role: 'alert',
  },
  warning: {
    bg: 'bg-warning-muted',
    border: 'border-warning/30',
    icon: 'text-warning',
    title: 'text-warning',
    text: 'text-ink-2',
    role: 'alert',
  },
  info: {
    bg: 'bg-brand-100',
    border: 'border-brand-300',
    icon: 'text-brand-800',
    title: 'text-brand-900',
    text: 'text-ink-2',
    role: 'status',
  },
  loading: {
    bg: 'bg-surface-2',
    border: 'border-hairline',
    icon: 'text-ink-3',
    title: 'text-ink',
    text: 'text-ink-3',
    role: 'status',
  },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const paused = useRef<Set<string>>(new Set())

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) { clearTimeout(timer); timers.current.delete(id) }
    paused.current.delete(id)
  }, [])

  const dismissAll = useCallback(() => {
    timers.current.forEach((t) => clearTimeout(t))
    timers.current.clear()
    paused.current.clear()
    setToasts([])
  }, [])

  const toast = useCallback((t: Omit<Toast, 'id'>) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
    const newToast: Toast = { ...t, id, duration: t.duration ?? 5000 }
    setToasts((prev) => [...prev, newToast])
    if (newToast.type !== 'loading' && newToast.duration && newToast.duration > 0) {
      timers.current.set(id, setTimeout(() => dismiss(id), newToast.duration))
    }
    return id
  }, [dismiss])

  const success = useCallback((title: string, message?: string) => toast({ type: 'success', title, message }), [toast])
  const error = useCallback((title: string, message?: string) => toast({ type: 'error', title, message, duration: 8000 }), [toast])
  const warning = useCallback((title: string, message?: string) => toast({ type: 'warning', title, message, duration: 6000 }), [toast])
  const info = useCallback((title: string, message?: string) => toast({ type: 'info', title, message, duration: 5000 }), [toast])
  const loading = useCallback((title: string, message?: string) => toast({ type: 'loading', title, message, duration: 0 }), [toast])

  // Pause auto-dismiss on hover so users have time to read
  const onMouseEnter = (id: string) => {
    const timer = timers.current.get(id)
    if (timer) { clearTimeout(timer); timers.current.delete(id); paused.current.add(id) }
  }
  const onMouseLeave = (id: string, duration: number) => {
    if (paused.current.has(id)) {
      paused.current.delete(id)
      timers.current.set(id, setTimeout(() => dismiss(id), duration))
    }
  }

  // Keyboard: Escape clears all toasts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') dismissAll() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [dismissAll])

  return (
    <ToastContext.Provider value={{ toast, dismiss, dismissAll, success, error, warning, info, loading }}>
      {children}
      {/* Live region for screen readers */}
      <div
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {toasts.filter((t) => t.type === 'error' || t.type === 'warning').map((t) => (
          <span key={t.id}>{t.title}. {t.message}</span>
        ))}
      </div>
      {/* Toast container */}
      <div
        className="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-[22rem] max-w-[calc(100vw-2rem)] pointer-events-none"
        role="region"
        aria-label="Notifications"
      >
        {toasts.map((t) => {
          const Icon = ICONS[t.type]
          const style = STYLES[t.type]
          return (
            <div
              key={t.id}
              role={style.role}
              className={clsx(
                'pointer-events-auto rounded-xl border p-4 shadow-crp-lg animate-slide-in-right',
                style.bg,
                style.border,
              )}
              onMouseEnter={() => onMouseEnter(t.id)}
              onMouseLeave={() => onMouseLeave(t.id, t.duration ?? 5000)}
            >
              <div className="flex items-start gap-3">
                <div className="shrink-0 mt-0.5" aria-hidden="true">
                  <Icon className={clsx('h-5 w-5', t.type === 'loading' && 'animate-spin', style.icon)} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className={clsx('text-sm font-bold', style.title)}>{t.title}</div>
                  {t.message && <div className={clsx('text-xs mt-1 leading-relaxed', style.text)}>{t.message}</div>}
                  {t.action && (
                    <button
                      type="button"
                      onClick={() => { t.action!.onClick(); dismiss(t.id) }}
                      className="mt-2 text-xs font-semibold text-brand-800 hover:text-brand-900 underline underline-offset-2 transition-colors"
                    >
                      {t.action.label}
                    </button>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => dismiss(t.id)}
                  className="shrink-0 text-ink-3 hover:text-ink transition-colors h-6 w-6 grid place-items-center rounded hover:bg-black/5 focus:outline-none focus:ring-2 focus:ring-brand-300"
                  aria-label={`Dismiss ${t.title}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}
