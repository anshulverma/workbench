import '@testing-library/jest-dom/vitest'

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
