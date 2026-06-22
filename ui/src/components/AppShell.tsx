import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { AppSidebar } from './AppSidebar'
import { Breadcrumb } from './Breadcrumb'
import { TopBar } from './TopBar'
import { CommandPalette } from './CommandPalette'

/**
 * AppShell — CSS-grid mission-control shell (spec §3, ADR0036, ADR0037).
 *
 * `grid-cols-[64px_1fr] grid-rows-[auto_1fr]`: the icon rail spans both rows
 * (full height, `z-30`), the sticky TopBar sits in row1/col2 (`z-20`), and a
 * single scrollable `<main>` owns row2/col2. Pages render inside `<main>`,
 * which is the one scroll container for the app.
 *
 * The ⌘K command palette (S1) mounts here: a global `(meta|ctrl)+k` keydown
 * listener opens it (preventDefault), and the TopBar's ⌘K trigger is wired to
 * the same open handler via `onOpenCommandPalette`. Radix Dialog owns Esc-close
 * and focus restoration to the trigger.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [paletteOpen, setPaletteOpen] = useState(false)
  const openPalette = useCallback(() => setPaletteOpen(true), [])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((prev) => !prev)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  return (
    <div className="grid h-screen overflow-hidden grid-cols-[64px_1fr] grid-rows-[auto_1fr] bg-background text-foreground">
      <AppSidebar className="row-span-2 z-30" />
      <TopBar onOpenCommandPalette={openPalette} />
      <main className="overflow-y-auto p-6">
        <Breadcrumb />
        {children}
      </main>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  )
}
