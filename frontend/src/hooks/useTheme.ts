import { useCallback, useEffect, useState } from 'react'
import { applyTheme, resolveInitialTheme, toggleTheme as toggleThemeImpl } from '../lib/theme'

/**
 * React-aware theme hook.
 *
 * Returns the current dark-mode flag and a toggle function. The hook
 * initialises itself from ``resolveInitialTheme()`` and mirrors any
 * changes to ``<html>`` immediately.
 */
export function useTheme(): { dark: boolean; toggle: () => void } {
  const [dark, setDark] = useState(() => resolveInitialTheme())

  useEffect(() => {
    applyTheme(dark)
  }, [dark])

  const handleToggle = useCallback(() => {
    setDark((prev) => toggleThemeImpl(prev))
  }, [])

  return { dark, toggle: handleToggle }
}
