/**
 * Single source of truth for CRP Comply light/dark theme.
 *
 * - ``resolveInitialTheme()`` reads localStorage + system preference.
 * - ``applyTheme(dark)`` writes the correct ``dark`` / ``light`` classes
 *   to ``<html>``.
 * - ``toggleTheme(dark)`` returns the opposite mode and persists it.
 *
 * All theme-aware code (main.tsx, AppShell, PublicHeader) should use
 * these helpers so the initial paint, React state, and localStorage can
 * never drift out of sync.
 */

export const THEME_KEY = 'crp_comply_theme'

export function resolveInitialTheme(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const stored = window.localStorage.getItem(THEME_KEY)
    if (stored === 'dark') return true
    if (stored === 'light') return false
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  } catch {
    return false
  }
}

export function applyTheme(dark: boolean): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.toggle('dark', dark)
  root.classList.toggle('light', !dark)
}

export function persistTheme(dark: boolean): void {
  try {
    window.localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light')
  } catch {
    /* storage unavailable - non-fatal */
  }
}

export function toggleTheme(currentDark: boolean): boolean {
  const next = !currentDark
  applyTheme(next)
  persistTheme(next)
  return next
}
