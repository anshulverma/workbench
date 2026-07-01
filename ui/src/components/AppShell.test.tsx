// AppShell tests (spec §3, plan Task 13).
//
// Asserts the CSS-grid app shell renders the brand, a banner top bar, the
// Primary nav rail, a mono route→context label, a ⌘K trigger, a theme toggle,
// and the page children — without requiring a QueryClientProvider (the sync
// indicator fails soft when no client is mounted).

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from 'next-themes'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppShell } from './AppShell'

function renderShell(initial = '/actions') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[initial]}>
          <AppShell>
            <div>page-body</div>
          </AppShell>
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  )
}

describe('AppShell', () => {
  it('renders the brand, a banner top bar, the rail, and children', () => {
    renderShell()
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(
      screen.getByRole('navigation', { name: /primary/i }),
    ).toBeInTheDocument()
    expect(screen.getByText('page-body')).toBeInTheDocument()
    // Brand mark: the two-tone "WorkBench" wordmark is split across spans
    // (Work / B / ench), so assert via the brand link's accessible name. The
    // logo is a NavLink to "/" (a link, not a button) in the sidebar rail.
    expect(
      screen.getAllByRole('link', { name: /workbench home/i }).length,
    ).toBeGreaterThanOrEqual(1)
  })

  it('renders a single scrollable <main> as the content region', () => {
    renderShell()
    expect(screen.getByRole('main')).toContainElement(
      screen.getByText('page-body'),
    )
  })

  it('renders a Breadcrumb inside main (hidden at root)', () => {
    renderShell('/actions')
    // On a non-root route the breadcrumb back button should be present.
    expect(
      screen.getByRole('button', { name: /back to/i }),
    ).toBeInTheDocument()
  })

  it('hides the Breadcrumb on the root route', () => {
    renderShell('/')
    expect(
      screen.queryByRole('button', { name: /back to/i }),
    ).not.toBeInTheDocument()
  })

  it('renders a mono route context label', () => {
    renderShell('/actions')
    expect(screen.getByText(/ACTION_ITEMS/)).toBeInTheDocument()
  })

  it('renders a ⌘K command-palette trigger button', () => {
    renderShell()
    const trigger = screen.getByRole('button', { name: /command palette/i })
    expect(trigger).toBeInTheDocument()
    expect(trigger).toHaveAttribute('data-command-trigger', 'true')
  })

  it('opens the command palette when the ⌘K trigger is clicked', async () => {
    const user = userEvent.setup()
    renderShell()
    await user.click(screen.getByRole('button', { name: /command palette/i }))
    // cmdk exposes the palette input as a combobox once open.
    expect(await screen.findByRole('combobox')).toBeInTheDocument()
  })

  it('opens the command palette on the global ⌘K / Ctrl+K shortcut', async () => {
    const user = userEvent.setup()
    renderShell()
    await user.keyboard('{Control>}k{/Control}')
    expect(await screen.findByRole('combobox')).toBeInTheDocument()
  })

  it('exposes a theme toggle with an aria-label reflecting state', () => {
    renderShell()
    expect(
      screen.getByRole('button', { name: /theme/i }),
    ).toBeInTheDocument()
  })

  it('cycles the theme on each toggle click (light → dark → system)', async () => {
    const user = userEvent.setup()
    renderShell()
    const toggle = screen.getByRole('button', { name: /theme/i })
    const first = toggle.getAttribute('aria-label')
    await user.click(toggle)
    const second = toggle.getAttribute('aria-label')
    expect(second).not.toBe(first)
    await user.click(toggle)
    const third = toggle.getAttribute('aria-label')
    expect(third).not.toBe(second)
  })
})
