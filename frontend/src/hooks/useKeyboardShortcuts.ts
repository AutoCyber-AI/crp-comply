import { useEffect } from 'react'

export interface KeyboardShortcutOptions {
  onOpenPalette: () => void
  onOpenHelp: () => void
  /** When true, the palette itself disables single-key navigation shortcuts. */
  modalOpen?: boolean
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (target.isContentEditable) return true
  return false
}

/**
 * Global keyboard shortcut dispatcher.
 *
 *   Cmd/Ctrl + K    → open command palette
 *   ?               → open keyboard-shortcut help (when not typing)
 *   Shift + ?       → open help
 *
 * The listener is attached at the document level but short-circuits when
 * focus is inside a form control so normal typing is never hijacked.
 */
export function useKeyboardShortcuts({
  onOpenPalette,
  onOpenHelp,
  modalOpen = false,
}: KeyboardShortcutOptions) {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase()

      // Palette is the highest priority shortcut and works everywhere.
      if ((e.metaKey || e.ctrlKey) && k === 'k') {
        e.preventDefault()
        if (modalOpen) {
          // If the palette is already open, treat Cmd/Ctrl+K as close.
          // Actual close is handled by the dialog; this avoids double open.
          return
        }
        onOpenPalette()
        return
      }

      // Help shortcut — suppress when typing in inputs or inside an open modal.
      if (!e.metaKey && !e.ctrlKey && !e.altKey && k === '?') {
        if (modalOpen || isEditable(e.target)) return
        e.preventDefault()
        onOpenHelp()
        return
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onOpenPalette, onOpenHelp, modalOpen])
}
