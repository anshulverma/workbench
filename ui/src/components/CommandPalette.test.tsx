// CommandPalette tests (spec §4, ADR0037, plan Task 15).
//
// Drives the ⌘K palette through MSW with a local QueryClientProvider + Router
// render helper (matching the other suites — no shared render helper). Covers:
//   - empty/short query shows the local nav Commands (route jumps + toggle theme)
//   - typing >=2 chars (debounced) queries GET /api/search and renders grouped hits
//   - selecting a nav Command navigates (route change reflected by useLocation)
//   - selecting a search hit navigates to its server-supplied route + closes
//   - facts group omitted (degraded) -> no Facts section, not an error
//   - Esc closes the palette
//   - combobox + listbox roles are exposed (a11y)

import {
  describe,
  it,
  expect,
  beforeAll,
  afterEach,
  afterAll,
  vi,
} from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { ThemeProvider } from 'next-themes'
import { CommandPalette } from './CommandPalette'
import { _resetToken } from '@/lib/api'

const SEARCH_ENVELOPE = {
  q: 'rds',
  truncated: false,
  groups: {
    items: [
      {
        id: 'WRK-1',
        kind: 'item',
        label: 'RDS alert',
        sublabel: 'github · P0',
        route: '/triage',
      },
    ],
    actions: [
      {
        id: 'ACT-1',
        kind: 'action',
        label: 'Patch RDS instance',
        sublabel: 'manual · P1',
        route: '/actions',
      },
    ],
    sources: [],
    facts: [
      { id: 'F-1', kind: 'fact', label: 'prefers RDS over Aurora', route: '/knowledge' },
    ],
  },
}

const handlers = [
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/search', () => HttpResponse.json(SEARCH_ENVELOPE)),
]
const server = setupServer(...handlers)
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers(...handlers)
  _resetToken()
})
afterAll(() => server.close())

function LocationProbe() {
  const { pathname } = useLocation()
  return <div data-testid="location">{pathname}</div>
}

function renderPalette(props?: {
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/']}>
          <LocationProbe />
          <CommandPalette
            open={props?.open ?? true}
            onOpenChange={props?.onOpenChange ?? (() => {})}
          />
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  )
}

describe('CommandPalette', () => {
  it('shows nav Commands when the query is empty', async () => {
    renderPalette()
    expect(await screen.findByText('Overview')).toBeInTheDocument()
    expect(screen.getByText(/toggle theme/i)).toBeInTheDocument()
  })

  it('exposes combobox + listbox roles (a11y)', async () => {
    renderPalette()
    expect(await screen.findByRole('combobox')).toBeInTheDocument()
    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  it('queries /api/search and groups hits (debounced, min 2 chars)', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'rds')
    expect(await screen.findByText('RDS alert')).toBeInTheDocument()
    expect(screen.getByText('Patch RDS instance')).toBeInTheDocument()
    // Grouped section headings render.
    expect(screen.getByText(/^items$/i)).toBeInTheDocument()
    expect(screen.getByText(/^actions$/i)).toBeInTheDocument()
  })

  it('does not query for a single character (min 2 chars)', async () => {
    const user = userEvent.setup()
    let searchCalls = 0
    server.use(
      http.get('/api/search', () => {
        searchCalls += 1
        return HttpResponse.json(SEARCH_ENVELOPE)
      }),
    )
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'r')
    // Give the 200ms debounce time to (not) fire.
    await new Promise((r) => setTimeout(r, 400))
    expect(searchCalls).toBe(0)
    // Local Commands remain visible for a short query.
    expect(screen.getByText('Overview')).toBeInTheDocument()
  })

  it('navigates to a hit route and closes when a hit is selected', async () => {
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    renderPalette({ onOpenChange })
    await user.type(screen.getByRole('combobox'), 'rds')
    const hit = await screen.findByText('RDS alert')
    await user.click(hit)
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/triage'),
    )
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('navigates via a local nav Command', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.click(await screen.findByText('Action Items'))
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/actions'),
    )
  })

  it('omits the Facts section when the group is absent (degraded)', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('/api/search', () =>
        HttpResponse.json({
          q: 'rds',
          truncated: false,
          groups: {
            items: SEARCH_ENVELOPE.groups.items,
            actions: [],
            sources: [],
            // facts intentionally omitted: memory degraded
          },
        }),
      ),
    )
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'rds')
    expect(await screen.findByText('RDS alert')).toBeInTheDocument()
    expect(screen.queryByText(/^facts$/i)).not.toBeInTheDocument()
  })

  it('renders the Facts section when the group is present', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'rds')
    expect(await screen.findByText('prefers RDS over Aurora')).toBeInTheDocument()
    expect(screen.getByText(/^facts$/i)).toBeInTheDocument()
  })

  it('shows an empty state when search returns no hits', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('/api/search', () =>
        HttpResponse.json({
          q: 'zzz',
          truncated: false,
          groups: { items: [], actions: [], sources: [], facts: [] },
        }),
      ),
    )
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'zzz')
    expect(await screen.findByText(/no results/i)).toBeInTheDocument()
  })

  it('surfaces an error with the request id', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('/api/search', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-xyz' } },
        ),
      ),
    )
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'rds')
    expect(await screen.findByText(/req-xyz/i)).toBeInTheDocument()
  })

  it('surfaces an unauthorized state on 401', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('/api/search', () =>
        HttpResponse.json({ detail: 'nope' }, { status: 401 }),
      ),
    )
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'rds')
    expect(await screen.findByText(/unauthorized/i)).toBeInTheDocument()
  })

  it('shows a truncated hint when results are truncated', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('/api/search', () =>
        HttpResponse.json({ ...SEARCH_ENVELOPE, truncated: true }),
      ),
    )
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'rds')
    expect(await screen.findByText(/truncated/i)).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    renderPalette({ onOpenChange })
    await screen.findByRole('combobox')
    await user.keyboard('{Escape}')
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })
})
