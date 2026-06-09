// Sources page tests (spec Design Section 2.5).
//
// Mirrors Ingestion.test.tsx: a local render helper with QueryClientProvider +
// MemoryRouter, driven through MSW. Covers the five UI states, the two-step
// add form (step1 -> step2 renders type-specific fields), create POST + success
// toast, 422 field-error mapping, optimistic enable/disable rollback, the
// per-row kebab (edit / poll-now / enable-disable / delete behind confirm), and
// optimistic delete with rollback.

import {
  describe,
  it,
  expect,
  beforeAll,
  afterAll,
  afterEach,
} from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { Sources } from './Sources'
import { _resetToken } from '@/lib/api'

const ADAPTER_TYPES = [
  {
    adapter_type: 'github',
    requires_connection: false,
    json_schema: {
      type: 'object',
      properties: { repos: { type: 'array', items: { type: 'string' } } },
    },
  },
  {
    adapter_type: 'email',
    requires_connection: true,
    json_schema: { type: 'object', properties: {} },
  },
]

const ROW = {
  id: 's1',
  adapter_type: 'github',
  enabled: true,
  schedule: '*/15 * * * *',
  last_run: null,
  items_stored: 0,
  raw_enqueued: 0,
  in_flight: 0,
  health_status: 'healthy',
  config: { repos: ['meta/workbench'] },
  relevance: null,
}

function baseHandlers(rows: unknown[] = []) {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/stats/sources', () => HttpResponse.json(rows)),
    http.get('/api/sources/adapter-types', () =>
      HttpResponse.json(ADAPTER_TYPES),
    ),
    http.get('/api/connections', () => HttpResponse.json([])),
  ]
}

const server = setupServer(...baseHandlers())
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(...baseHandlers())
  _resetToken()
})
afterAll(() => server.close())

function renderSources() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Sources />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Sources page', () => {
  it('renders the loading state while sources are pending', () => {
    server.use(http.get('/api/stats/sources', () => new Promise(() => {})))
    renderSources()
    expect(screen.getByTestId('sources-loading')).toBeInTheDocument()
  })

  it('renders the empty state with an add CTA', async () => {
    server.use(...baseHandlers([]))
    renderSources()
    expect(
      await screen.findByRole('button', { name: /add your first source/i }),
    ).toBeInTheDocument()
  })

  it('renders the error state with the X-Request-ID', async () => {
    server.use(
      http.get('/api/stats/sources', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-7' } },
        ),
      ),
    )
    renderSources()
    await waitFor(() => expect(screen.getByText(/req-7/)).toBeInTheDocument())
  })

  it('renders the unauthorized state when the token endpoint 401s', async () => {
    server.use(
      http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
    )
    renderSources()
    await waitFor(() =>
      expect(screen.getByText(/token unavailable/i)).toBeInTheDocument(),
    )
  })

  it('renders a card grid of real adapters from /api/stats/sources', async () => {
    server.use(...baseHandlers([ROW]))
    renderSources()
    expect(await screen.findByText('github')).toBeInTheDocument()
    expect(screen.getByText('s1')).toBeInTheDocument()
    expect(screen.getByText('healthy')).toBeInTheDocument()
    // human-readable schedule
    expect(screen.getByText('Every 15 minutes')).toBeInTheDocument()
  })

  it('never fabricates mockup integrations (Jira/Slack/PagerDuty/Linear)', async () => {
    server.use(...baseHandlers([ROW]))
    renderSources()
    await screen.findByText('github')
    expect(screen.queryByText(/jira/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/slack/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/pagerduty/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/linear/i)).not.toBeInTheDocument()
  })

  it('top stat cards compute active pipes / volume / errors', async () => {
    const rows = [
      { ...ROW, id: 's1', enabled: true, items_stored: 10, health_status: 'healthy' },
      {
        ...ROW,
        id: 's2',
        adapter_type: 'email',
        enabled: false,
        items_stored: 5,
        health_status: 'disabled',
      },
      {
        ...ROW,
        id: 's3',
        adapter_type: 'calendar',
        enabled: true,
        items_stored: 7,
        health_status: 'erroring',
      },
    ]
    server.use(...baseHandlers(rows))
    renderSources()
    // Active Pipes = enabled count (s1, s3) = 2
    const active = await screen.findByTestId('stat-active-pipes')
    expect(active).toHaveTextContent('2')
    // Ingestion Volume = 10 + 5 + 7 = 22
    expect(screen.getByTestId('stat-volume')).toHaveTextContent('22')
    // Errors = erroring-source count = 1
    expect(screen.getByTestId('stat-errors')).toHaveTextContent('1')
  })

  it('Connect New Source card opens the two-step wizard', async () => {
    server.use(...baseHandlers([ROW]))
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /connect new source/i }),
    )
    expect(await screen.findByText(/pick an adapter type/i)).toBeInTheDocument()
  })

  it('two-step add form: step1 pick github -> step2 renders type-specific fields', async () => {
    server.use(...baseHandlers([]))
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /add your first source/i }),
    )
    await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
    expect(
      await screen.findByText(/adapter_type: github \(immutable\)/i),
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/repos/i)).toBeInTheDocument()
  })

  it('email adapter is disabled in step 1 when no connection exists', async () => {
    server.use(...baseHandlers([]))
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /add your first source/i }),
    )
    const emailBtn = await screen.findByRole('button', { name: /^email$/i })
    expect(emailBtn).toBeDisabled()
  })

  it('create calls POST /api/sources and shows the success toast', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      ...baseHandlers([]),
      http.post('/api/sources', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'new', ...posted })
      }),
    )
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /add your first source/i }),
    )
    await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
    await userEvent.type(screen.getByLabelText(/repos/i), 'meta/workbench')
    await userEvent.click(screen.getByRole('button', { name: /create source/i }))
    await waitFor(() =>
      expect(posted).toMatchObject({
        adapter_type: 'github',
        config: { repos: ['meta/workbench'] },
      }),
    )
    expect(await screen.findByText(/source added/i)).toBeInTheDocument()
  })

  it('maps a 422 config field error onto the form', async () => {
    server.use(
      ...baseHandlers([]),
      http.post('/api/sources', () =>
        HttpResponse.json(
          { detail: { config_errors: [{ loc: ['repos'], msg: 'must be a list' }] } },
          { status: 422 },
        ),
      ),
    )
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /add your first source/i }),
    )
    await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
    await userEvent.type(screen.getByLabelText(/repos/i), 'x')
    await userEvent.click(screen.getByRole('button', { name: /create source/i }))
    expect(await screen.findByText(/must be a list/i)).toBeInTheDocument()
  })

  it('enable toggle calls PATCH and rolls back on failure', async () => {
    server.use(
      ...baseHandlers([ROW]),
      http.patch('/api/sources/s1', () =>
        HttpResponse.json({ detail: 'fail' }, { status: 500 }),
      ),
    )
    renderSources()
    const toggle = await screen.findByRole('switch', { name: /toggle s1/i })
    expect(toggle).toBeChecked()
    await userEvent.click(toggle)
    // optimistic off, then rollback to on
    await waitFor(() => expect(toggle).toBeChecked())
  })

  it('kebab poll-now calls POST /poll and toasts', async () => {
    let polled = false
    server.use(
      ...baseHandlers([ROW]),
      http.post('/api/sources/s1/poll', () => {
        polled = true
        return HttpResponse.json({ status: 'polled' })
      }),
    )
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /actions for s1/i }),
    )
    await userEvent.click(
      await screen.findByRole('menuitem', { name: /poll.?now/i }),
    )
    await waitFor(() => expect(polled).toBe(true))
    expect(await screen.findByText(/poll started/i)).toBeInTheDocument()
  })

  it('kebab enable/disable calls PATCH with enabled', async () => {
    let patched: Record<string, unknown> | null = null
    server.use(
      ...baseHandlers([ROW]),
      http.patch('/api/sources/s1', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 's1' })
      }),
    )
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /actions for s1/i }),
    )
    await userEvent.click(await screen.findByRole('menuitem', { name: /disable/i }))
    await waitFor(() => expect(patched).toMatchObject({ enabled: false }))
  })

  it('kebab edit opens the form in edit mode with adapter_type read-only', async () => {
    server.use(...baseHandlers([ROW]))
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /actions for s1/i }),
    )
    await userEvent.click(await screen.findByRole('menuitem', { name: /edit/i }))
    expect(
      await screen.findByText(/adapter_type: github \(immutable\)/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/pick an adapter type/i)).not.toBeInTheDocument()
  })

  it('delete behind confirm dialog optimistically removes the row', async () => {
    let deleted = false
    // After delete the server no longer lists the row; the post-settle refetch
    // must reflect that so the optimistic removal sticks.
    server.use(
      http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
      http.get('/api/stats/sources', () =>
        HttpResponse.json(deleted ? [] : [ROW]),
      ),
      http.get('/api/sources/adapter-types', () =>
        HttpResponse.json(ADAPTER_TYPES),
      ),
      http.get('/api/connections', () => HttpResponse.json([])),
      http.delete('/api/sources/s1', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /actions for s1/i }),
    )
    await userEvent.click(await screen.findByRole('menuitem', { name: /delete/i }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /^delete$/i }))
    await waitFor(() => expect(deleted).toBe(true))
    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: /actions for s1/i }),
      ).not.toBeInTheDocument(),
    )
  })

  it('delete rolls the row back when the server fails', async () => {
    server.use(
      ...baseHandlers([ROW]),
      http.delete('/api/sources/s1', () =>
        HttpResponse.json({ detail: 'nope' }, { status: 500 }),
      ),
    )
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /actions for s1/i }),
    )
    await userEvent.click(await screen.findByRole('menuitem', { name: /delete/i }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /^delete$/i }))
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /actions for s1/i }),
      ).toBeInTheDocument(),
    )
  })

  // --- Config Drawer: per-source relevance/noise thresholds (ADR0044) ---

  it('kebab Configure opens the drawer with inherited defaults when relevance is null', async () => {
    server.use(...baseHandlers([{ ...ROW, relevance: null }]))
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /actions for s1/i }),
    )
    await userEvent.click(
      await screen.findByRole('menuitem', { name: /configure/i }),
    )
    // null relevance => inherited global defaults 70 / 30 / 30
    const auto = await screen.findByRole('slider', {
      name: /auto.?include threshold/i,
    })
    const triage = screen.getByRole('slider', { name: /triage threshold/i })
    const drop = screen.getByRole('slider', { name: /drop below/i })
    expect(auto).toHaveValue('70')
    expect(triage).toHaveValue('30')
    expect(drop).toHaveValue('30')
    expect(screen.getByText(/inherited/i)).toBeInTheDocument()
  })

  it('drawer shows the source current relevance values when set', async () => {
    server.use(
      ...baseHandlers([
        {
          ...ROW,
          relevance: {
            auto_include_threshold: 80,
            triage_threshold: 40,
            drop_below: 20,
          },
        },
      ]),
    )
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /actions for s1/i }),
    )
    await userEvent.click(
      await screen.findByRole('menuitem', { name: /configure/i }),
    )
    expect(
      await screen.findByRole('slider', { name: /auto.?include threshold/i }),
    ).toHaveValue('80')
    expect(
      screen.getByRole('slider', { name: /triage threshold/i }),
    ).toHaveValue('40')
    expect(screen.getByRole('slider', { name: /drop below/i })).toHaveValue('20')
  })

  it('Save PATCHes /api/sources/{id} with the integer relevance object', async () => {
    let patched: Record<string, unknown> | null = null
    server.use(
      ...baseHandlers([{ ...ROW, relevance: null }]),
      http.patch('/api/sources/s1', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 's1' })
      }),
    )
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /actions for s1/i }),
    )
    await userEvent.click(
      await screen.findByRole('menuitem', { name: /configure/i }),
    )
    await screen.findByRole('slider', { name: /auto.?include threshold/i })
    await userEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() =>
      expect(patched).toEqual({
        relevance: {
          auto_include_threshold: 70,
          triage_threshold: 30,
          drop_below: 30,
        },
      }),
    )
  })

  it('surfaces an inverted-threshold 422 inline in the drawer', async () => {
    server.use(
      ...baseHandlers([{ ...ROW, relevance: null }]),
      http.patch('/api/sources/s1', () =>
        HttpResponse.json(
          {
            detail: [
              {
                loc: ['body', 'relevance'],
                msg: 'drop_below must be <= auto_include_threshold',
              },
            ],
          },
          { status: 422 },
        ),
      ),
    )
    renderSources()
    await userEvent.click(
      await screen.findByRole('button', { name: /actions for s1/i }),
    )
    await userEvent.click(
      await screen.findByRole('menuitem', { name: /configure/i }),
    )
    await screen.findByRole('slider', { name: /auto.?include threshold/i })
    await userEvent.click(screen.getByRole('button', { name: /save/i }))
    expect(
      await screen.findByText(/drop_below must be <= auto_include_threshold/i),
    ).toBeInTheDocument()
  })
})
