import { useEffect, useRef, useCallback } from 'react'

const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable]',
].join(', ')

export interface FocusTrapOptions {
  /** Whether the trap is currently active. */
  active: boolean
  /** Element to return focus to when the trap is deactivated. */
  returnFocusTo?: HTMLElement | null
  /** Callback when Escape is pressed. */
  onEscape?: () => void
}

/**
 * Focus trap for modals, drawers, and dialogs.
 *
 * When active, focus is cycled inside the container and Escape can be handled.
 * Focus is restored to the trigger element when the trap deactivates.
 */
export function useFocusTrap<T extends HTMLElement>(options: FocusTrapOptions) {
  const { active, returnFocusTo, onEscape } = options
  const containerRef = useRef<T>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  const getFocusable = useCallback(() => {
    const container = containerRef.current
    if (!container) return []
    return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
  }, [])

  useEffect(() => {
    if (active) {
      previousFocusRef.current = document.activeElement as HTMLElement
      const focusable = getFocusable()
      if (focusable.length) {
        focusable[0].focus()
      }
    } else if (previousFocusRef.current) {
      const target = returnFocusTo ?? previousFocusRef.current
      if (target.isConnected) {
        target.focus()
      }
      previousFocusRef.current = null
    }
  }, [active, returnFocusTo, getFocusable])

  useEffect(() => {
    if (!active) return

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        onEscape?.()
        return
      }
      if (e.key !== 'Tab') return

      const focusable = getFocusable()
      if (focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [active, getFocusable, onEscape])

  return containerRef
}
