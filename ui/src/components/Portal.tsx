import { type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/**
 * Portal — renders children into `document.body` via `ReactDOM.createPortal`.
 * Used for modals, dialogs, and overlays that need to escape the stacking
 * context of their parent tree.
 */
export function Portal({ children }: { children: ReactNode }) {
  return createPortal(children, document.body)
}
