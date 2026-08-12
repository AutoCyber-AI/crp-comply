import '@testing-library/jest-dom/vitest'

// jsdom does not implement ResizeObserver, but cmdk and other UI primitives
// rely on it for layout measurements. Provide a no-op stub in tests.
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// cmdk scrolls the selected item into view; jsdom does not implement this.
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || function () {}
