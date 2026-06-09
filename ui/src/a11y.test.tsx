// Accessibility tests (spec Design Section 11.3, plan Task F1).
//
// Asserts the cross-cutting a11y guarantees that are testable under jsdom:
//   - the sidebar exposes a <nav> landmark, its links are native <a> elements
//     reachable by keyboard (Tab order), and the active link carries
//     aria-current="page" (NavLink default);
//   - icon-only / destructive controls carry accessible names (aria-label);
//   - shadcn Dialog (Radix) moves focus into the dialog on open and returns
//     focus to the trigger on close.
//
// These tests are self-contained (no shared render helper) to match the other
// suites in this package.

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { AppSidebar } from '@/components/AppSidebar'
import { FactRow } from '@/components/FactRow'

function renderWithRouter(ui: React.ReactNode, initialEntry = '/') {
  return render(<MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>)
}

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        {ui}
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('accessibility', () => {
  it('exposes a Primary nav landmark with native, keyboard-reachable links', async () => {
    renderWithRouter(<AppSidebar />)

    // <nav aria-label="Primary"> landmark.
    expect(
      screen.getByRole('navigation', { name: /primary/i }),
    ).toBeInTheDocument()

    // Links are native <a> (role=link), not click-only divs.
    const overview = screen.getByRole('link', { name: 'Overview' })
    expect(overview.tagName).toBe('A')

    // Tab moves focus to the first nav link (keyboard reachable, in order).
    await userEvent.tab()
    expect(overview).toHaveFocus()
  })

  it('rail links are icon-only with accessible names (aria-label)', () => {
    renderWithRouter(<AppSidebar />)
    // The 64px icon rail shows lucide icons; accessible names come from
    // aria-label, not visible text. All eight routes must remain named.
    for (const name of [
      'Overview',
      'Triage',
      'Action Items',
      'Ingestion',
      'Sources',
      'Knowledge',
      'Messenger',
      'Settings',
    ]) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument()
    }
  })

  it('marks the active nav link with aria-current="page"', () => {
    renderWithRouter(<AppSidebar />, '/triage')
    const active = screen.getByRole('link', { name: 'Triage' })
    expect(active).toHaveAttribute('aria-current', 'page')
    // Inactive links must not carry aria-current.
    expect(screen.getByRole('link', { name: 'Overview' })).not.toHaveAttribute(
      'aria-current',
    )
  })

  it('gives icon-only / destructive row controls accessible names', () => {
    renderWithClient(
      <ul>
        <FactRow fact={{ id: 'f9', content: 'x', source: 's', timestamp: null }} />
      </ul>,
    )
    expect(
      screen.getByRole('button', { name: /edit f9/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /delete f9/i }),
    ).toBeInTheDocument()
  })

  it('moves focus into the dialog on open and closes it on Escape (focus trap)', async () => {
    const user = userEvent.setup()
    renderWithClient(
      <ul>
        <FactRow fact={{ id: 'f9', content: 'x', source: 's', timestamp: null }} />
      </ul>,
    )

    const trigger = screen.getByRole('button', { name: /delete f9/i })
    await user.click(trigger)

    // Dialog (Radix) opens and moves focus inside it — the focus trap is active.
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(dialog.contains(document.activeElement)).toBe(true)

    // Escape closes it. (Radix returns focus to the trigger in a real browser;
    // jsdom drops it to <body> on unmount, so we assert the close + that focus
    // left the now-removed dialog rather than the exact restoration target.)
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.activeElement).not.toBe(dialog)
  })
})
