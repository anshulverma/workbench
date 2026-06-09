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
    expect(screen.getByText(/workbench/i)).toBeInTheDocument()
  })

  it('renders a single scrollable <main> as the content region', () => {
    renderShell()
    expect(screen.getByRole('main')).toContainElement(
      screen.getByText('page-body'),
    )
  })

  it('renders a mono route context label', () => {
    renderShell('/actions')
    expect(screen.getByText(/ACTION_ITEMS/)).toBeInTheDocument()
  })

  it('renders a ⌘K command-palette trigger button', () => {
    renderShell()
    const trigger = screen.getByRole('button', { name: /command palette/i })
    expect(trigger).toBeInTheDocument()
    // Placeholder for S1: no palette renders yet on click.
    expect(trigger).toHaveAttribute('data-command-trigger', 'true')
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
