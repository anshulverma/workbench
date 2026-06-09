// Work Mode / Terminal Focus — a client-only visual-focus preference (ADR 0042).
//
// Persists a single boolean in localStorage and syncs it across tabs via the
// `storage` event. It is purely a view preference: it never mutates server
// state and never mutes notifications (ADR 0042). Consumers use it to collapse
// the UI to the top active P0 "vector" and dim/hide non-critical chrome.
//
// Render-loop safety: the initial value is read ONCE in a useState initializer
// (no effect+setState), and the cross-tab listener is registered in an effect
// with EMPTY deps + cleanup. No freshly-computed objects flow into any effect.

import { useCallback, useEffect, useState } from 'react'

export const WORK_MODE_KEY = 'workbench.workMode'

function readWorkMode(): boolean {
  try {
    return localStorage.getItem(WORK_MODE_KEY) === 'true'
  } catch {
    return false
  }
}

export function useWorkMode() {
  const [workMode, setWorkModeState] = useState<boolean>(readWorkMode)

  const setWorkMode = useCallback((next: boolean) => {
    setWorkModeState(next)
    try {
      localStorage.setItem(WORK_MODE_KEY, String(next))
    } catch {
      // localStorage unavailable (private mode / SSR): keep in-memory state.
    }
  }, [])

  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key !== WORK_MODE_KEY) return
      setWorkModeState(e.newValue === 'true')
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  return { workMode, setWorkMode }
}
