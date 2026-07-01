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

// jsdom exposes no Storage on an opaque origin, so `localStorage` is undefined
// here; tests that clear/read it (e.g. ActionItems) would throw. Provide a
// minimal in-memory Storage stub so those tests run.
if (typeof globalThis.localStorage === 'undefined') {
  const makeStorage = (): Storage => {
    const store = new Map<string, string>()
    return {
      get length() {
        return store.size
      },
      clear: () => store.clear(),
      getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
      key: (index: number) => Array.from(store.keys())[index] ?? null,
      removeItem: (key: string) => void store.delete(key),
      setItem: (key: string, value: string) => void store.set(key, String(value)),
    } as Storage
  }
  Object.defineProperty(globalThis, 'localStorage', {
    value: makeStorage(),
    configurable: true,
  })
  Object.defineProperty(globalThis, 'sessionStorage', {
    value: makeStorage(),
    configurable: true,
  })
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
