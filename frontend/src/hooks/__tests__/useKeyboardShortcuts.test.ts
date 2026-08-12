import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { useKeyboardShortcuts } from '../useKeyboardShortcuts'

describe('useKeyboardShortcuts', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  afterEach(() => {
    // Ensure no lingering document listeners bleed between tests.
    document.body.innerHTML = ''
  })

  it('opens palette on Cmd+K', () => {
    const openPalette = vi.fn()
    const openHelp = vi.fn()
    renderHook(() =>
      useKeyboardShortcuts({ onOpenPalette: openPalette, onOpenHelp: openHelp }),
    )

    document.dispatchEvent(new KeyboardEvent('keydown', { metaKey: true, key: 'k' }))

    expect(openPalette).toHaveBeenCalled()
    expect(openHelp).not.toHaveBeenCalled()
  })

  it('opens palette on Ctrl+K', () => {
    const openPalette = vi.fn()
    renderHook(() =>
      useKeyboardShortcuts({
        onOpenPalette: openPalette,
        onOpenHelp: vi.fn(),
      }),
    )

    document.dispatchEvent(new KeyboardEvent('keydown', { ctrlKey: true, key: 'k' }))
    expect(openPalette).toHaveBeenCalled()
  })

  it('opens help on ?', () => {
    const openHelp = vi.fn()
    renderHook(() =>
      useKeyboardShortcuts({
        onOpenPalette: vi.fn(),
        onOpenHelp: openHelp,
      }),
    )

    document.dispatchEvent(new KeyboardEvent('keydown', { key: '?' }))
    expect(openHelp).toHaveBeenCalled()
  })

  it('does not open help when typing in an input', () => {
    const openHelp = vi.fn()
    renderHook(() =>
      useKeyboardShortcuts({
        onOpenPalette: vi.fn(),
        onOpenHelp: openHelp,
      }),
    )

    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    input.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }))
    expect(openHelp).not.toHaveBeenCalled()

    document.body.removeChild(input)
  })
})
