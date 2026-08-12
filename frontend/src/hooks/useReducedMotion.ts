import { useSyncExternalStore } from 'react'

function subscribe(callback: () => void) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {}
  const query = window.matchMedia('(prefers-reduced-motion: reduce)')
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

function getSnapshot() {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function getServerSnapshot() {
  return false
}

/**
 * Returns true when the user has requested reduced motion.
 * Use this to switch `scrollTo`/`scrollIntoView` behavior from smooth to auto
 * and to skip non-essential animations.
 */
export function useReducedMotion() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
