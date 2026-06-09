import '@testing-library/jest-dom/vitest'

// jsdom lacks ResizeObserver; cmdk (the ⌘K command palette) constructs one on
// mount. Provide a no-op stub so palette tests can render.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

// jsdom lacks Element.scrollIntoView; cmdk calls it when it auto-selects the
// active palette item. Stub it as a no-op.
if (
  typeof Element !== 'undefined' &&
  typeof Element.prototype.scrollIntoView !== 'function'
) {
  Element.prototype.scrollIntoView = () => {}
}

// jsdom lacks matchMedia; sonner's <Toaster> reads it on mount. Stub it so
// tests that assert toast text can render the Toaster.
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList
}
