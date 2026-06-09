import type { ReactNode } from 'react'
import { AppSidebar } from './AppSidebar'
import { TopBar } from './TopBar'

/**
 * AppShell — CSS-grid mission-control shell (spec §3, ADR0036).
 *
 * `grid-cols-[64px_1fr] grid-rows-[auto_1fr]`: the icon rail spans both rows
 * (full height, `z-30`), the sticky TopBar sits in row1/col2 (`z-20`), and a
 * single scrollable `<main>` owns row2/col2. Pages render inside `<main>`,
 * which is the one scroll container for the app.
 *
 * The ⌘K command palette (S1) mounts here later and passes its open handler to
 * the TopBar's command trigger via `onOpenCommandPalette`.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen grid-cols-[64px_1fr] grid-rows-[auto_1fr] bg-background text-foreground">
      <AppSidebar className="row-span-2 z-30" />
      <TopBar />
      <main className="overflow-y-auto p-6">{children}</main>
    </div>
  )
}
