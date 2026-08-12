import { useId, forwardRef, type ReactNode, type InputHTMLAttributes, type TextareaHTMLAttributes, type SelectHTMLAttributes } from 'react'
import clsx from 'clsx'

interface FieldWrapperProps {
  label?: string
  hideLabel?: boolean
  hint?: string
  error?: string
  required?: boolean
  children: ReactNode
  className?: string
}

export function FormField({
  label,
  hideLabel,
  hint,
  error,
  required,
  children,
  className,
}: FieldWrapperProps) {
  const id = useId()
  const labelId = `${id}-label`
  const hintId = `${id}-hint`
  const errorId = `${id}-error`

  return (
    <div className={clsx('space-y-1.5', className)}>
      {label && (
        <label
          id={labelId}
          htmlFor={id}
          className={clsx(
            'block text-sm font-medium text-ink-2',
            hideLabel && 'sr-only',
          )}
        >
          {label}
          {required && <span className="text-danger ml-1" aria-hidden="true">*</span>}
        </label>
      )}
      {hint && (
        <p id={hintId} className="text-xs text-ink-4">
          {hint}
        </p>
      )}
      {children}
      {error && (
        <p id={errorId} className="text-xs text-danger flex items-center gap-1">
          {error}
        </p>
      )}
    </div>
  )
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={clsx('input', className)} {...rest} />
  },
)

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...rest }, ref) {
    return <textarea ref={ref} className={clsx('textarea', className)} {...rest} />
  },
)

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, ...rest }, ref) {
    return <select ref={ref} className={clsx('select', className)} {...rest} />
  },
)

/**
 * High-level labelled input with automatic aria-describedby wiring.
 */
export const LabelledInput = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement> & FieldWrapperProps
>(function LabelledInput({ label, hideLabel, hint, error, required, className, ...rest }, ref) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined

  return (
    <FormField label={label} hideLabel={hideLabel} hint={hint} error={error} required={required} className={className}>
      <Input
        ref={ref}
        id={id}
        aria-invalid={!!error}
        aria-describedby={describedBy}
        {...rest}
      />
    </FormField>
  )
})

/**
 * High-level labelled textarea with automatic aria-describedby wiring.
 */
export const LabelledTextarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement> & FieldWrapperProps
>(function LabelledTextarea({ label, hideLabel, hint, error, required, className, ...rest }, ref) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined

  return (
    <FormField label={label} hideLabel={hideLabel} hint={hint} error={error} required={required} className={className}>
      <Textarea
        ref={ref}
        id={id}
        aria-invalid={!!error}
        aria-describedby={describedBy}
        {...rest}
      />
    </FormField>
  )
})

/**
 * High-level labelled select with automatic aria-describedby wiring.
 */
export const LabelledSelect = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement> & FieldWrapperProps
>(function LabelledSelect({ label, hideLabel, hint, error, required, className, children, ...rest }, ref) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined

  return (
    <FormField label={label} hideLabel={hideLabel} hint={hint} error={error} required={required} className={className}>
      <Select
        ref={ref}
        id={id}
        aria-invalid={!!error}
        aria-describedby={describedBy}
        {...rest}
      >
        {children}
      </Select>
    </FormField>
  )
})
