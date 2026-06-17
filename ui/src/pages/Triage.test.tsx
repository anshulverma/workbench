// Triage page tests (spec Design Section 2.2, plan Task E6).
//
// Local render helper (QueryClientProvider + MemoryRouter + Toaster) driven via
// MSW, mirroring Messenger.test.tsx. Covers: loading / empty ("Inbox zero") /
// error (w/ X-Request-ID) / unauthorized states, numbered respond (MSW hit on
// POST /respond with the chosen choice), free-text respond, the
// awaiting_confirmation -> confirm dialog -> POST /confirm flow (MSW hit), and
// the 409 friendly toast.

import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { Triage } from './Triage'
import { _resetToken } from '@/lib/api'

const NOW = Date.now()
const iso = (msAgo: number) => new Date(NOW - msAgo).toISOString()
const HOUR = 3_600_000
const DAY = 24 * HOUR

const CARD = {
  id: 'c1',
  card_content: { summary: 'Review auth PR', source_type: 'github' },
  options: [
    { label: 'Add todo', action: 'add_todo' },
    { label: 'Skip', action: 'skip' },
  ],
  relevance_score: 80,
  status: 'sent',
  created_at: iso(10 * 60_000), // 10m ago
}

// A second card from a different source / priority / age, used to exercise the
// left filter rail (sources + priority + time window).
const CARD2 = {
  id: 'c2',
  card_content: {
    summary: 'Unread email from ops',
    source_type: 'email',
    priority: 'P3',
  },
  options: [{ label: 'Archive', action: 'archive' }],
  relevance_score: 30,
  status: 'sent',
  created_at: iso(3 * DAY), // 3 days ago
}

// Card whose options carry real per-option suggestion_reason → LLM Insight backed.
const CARD_BACKED = {
  id: 'c3',
  card_content: { summary: 'Risky migration diff', source_type: 'github', priority: 'P0' },
  options: [
    {
      label: 'Approve',
      action: 'approve',
      suggested: true,
      suggestion_reason: 'Low blast radius; tests green',
    },
    { label: 'Skip', action: 'skip' },
  ],
  relevance_score: 95,
  confidence_score: 88,
  status: 'sent',
  created_at: iso(5 * 60_000),
}

// A task card carrying source identity (source_ref + source_url) — exercises
// the source-type badge and the "open in source" link.
const CARD_LINKED = {
  id: 'c4',
  card_content: {
    summary: 'Triage incoming task',
    source_type: 'meta_tasks',
    source_ref: 'T123456',
    source_url: 'https://www.internalfb.com/tasks/?t=123456',
  },
  options: [{ label: 'Add todo', action: 'add_todo' }],
  relevance_score: 70,
  status: 'sent',
  created_at: iso(60_000),
}

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/stats/timeseries', () =>
      HttpResponse.json([
        { bucket: iso(2 * HOUR), count: 3 },
        { bucket: iso(1 * HOUR), count: 5 },
      ]),
    ),
    http.get('/api/stats/overview', () =>
      HttpResponse.json({
        metrics: { auto_resolved_pct: 0.42, avg_triage_seconds: 90 },
      }),
    ),
  ]
}

const server = setupServer(...baseHandlers())
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(...baseHandlers())
  _resetToken()
})
afterAll(() => server.close())

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Triage />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Triage page', () => {
  it('renders the loading state while the query is pending', () => {
    server.use(http.get('/api/triage/pending', () => new Promise(() => {})))
    renderPage()
    expect(screen.getByTestId('triage-loading')).toBeInTheDocument()
  })

  it('renders the empty "Inbox zero" state when there are no cards', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([])))
    renderPage()
    expect(await screen.findByText(/Inbox zero/i)).toBeInTheDocument()
  })

  it('renders the error state with the X-Request-ID on failure', async () => {
    server.use(
      http.get('/api/triage/pending', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-6' } },
        ),
      ),
    )
    renderPage()
    expect(await screen.findByText(/req-6/)).toBeInTheDocument()
  })

  it('renders the unauthorized state when the token endpoint returns 401', async () => {
    server.use(
      http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/triage/pending', () => HttpResponse.json([CARD])),
    )
    renderPage()
    expect(await screen.findByText(/token unavailable/i)).toBeInTheDocument()
  })

  it('renders a pending card with its summary and numbered options', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD])))
    renderPage()
    expect(await screen.findByText('Review auth PR')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /\[1\] add todo/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /\[2\] skip/i })).toBeInTheDocument()
    expect(screen.getByText(/relevance 80/i)).toBeInTheDocument()
  })

  it('clicking a numbered option POSTs /respond with that choice', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      http.get('/api/triage/pending', () => HttpResponse.json([CARD])),
      http.post('/api/triage/respond', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'recorded', action: 'add_todo' })
      }),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /\[1\] add todo/i }))
    await waitFor(() => expect(posted).toMatchObject({ card_id: 'c1', choice: 1 }))
  })

  it('free-text submit POSTs /respond with raw_text', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      http.get('/api/triage/pending', () => HttpResponse.json([CARD])),
      http.post('/api/triage/respond', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'interpreted', action: 'free_text' })
      }),
    )
    renderPage()
    await userEvent.type(
      await screen.findByLabelText(/free.?text/i),
      'add this to my list',
    )
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() =>
      expect(posted).toMatchObject({ card_id: 'c1', raw_text: 'add this to my list' }),
    )
  })

  it('an awaiting_confirmation response opens the dialog and confirm POSTs /confirm', async () => {
    let confirmed: Record<string, unknown> | null = null
    server.use(
      http.get('/api/triage/pending', () => HttpResponse.json([CARD])),
      http.post('/api/triage/respond', () =>
        HttpResponse.json({
          status: 'awaiting_confirmation',
          explanation: 'This will skip and mute the pattern',
          card_id: 'c1',
        }),
      ),
      http.post('/api/triage/confirm', async ({ request }) => {
        confirmed = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'responded' })
      }),
    )
    renderPage()
    await userEvent.type(await screen.findByLabelText(/free.?text/i), 'drop this')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText(/will skip and mute/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
    await waitFor(() =>
      expect(confirmed).toMatchObject({ card_id: 'c1', confirm: true }),
    )
  })

  it('cancelling the confirm dialog POSTs /confirm with confirm:false', async () => {
    let confirmed: Record<string, unknown> | null = null
    server.use(
      http.get('/api/triage/pending', () => HttpResponse.json([CARD])),
      http.post('/api/triage/respond', () =>
        HttpResponse.json({
          status: 'awaiting_confirmation',
          explanation: 'about to mute pattern',
          card_id: 'c1',
        }),
      ),
      http.post('/api/triage/confirm', async ({ request }) => {
        confirmed = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'queued' })
      }),
    )
    renderPage()
    await userEvent.type(await screen.findByLabelText(/free.?text/i), 'drop this')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByText(/about to mute pattern/i)
    await userEvent.click(screen.getByRole('button', { name: /^cancel$/i }))
    await waitFor(() =>
      expect(confirmed).toMatchObject({ card_id: 'c1', confirm: false }),
    )
  })

  it('surfaces a friendly toast when /respond returns 409 (already answered)', async () => {
    server.use(
      http.get('/api/triage/pending', () => HttpResponse.json([CARD])),
      http.post('/api/triage/respond', () =>
        HttpResponse.json({ detail: 'Card already responded' }, { status: 409 }),
      ),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /\[1\] add todo/i }))
    expect(await screen.findByText(/already answered elsewhere/i)).toBeInTheDocument()
  })

  // --- P2: 3-column shell + filters + analytics (ADR0043) ---

  it('renders a source filter (with counts) and narrows the feed when toggled', async () => {
    server.use(
      http.get('/api/triage/pending', () => HttpResponse.json([CARD, CARD2])),
    )
    renderPage()
    // both cards visible initially
    expect(await screen.findByText('Review auth PR')).toBeInTheDocument()
    expect(screen.getByText('Unread email from ops')).toBeInTheDocument()

    // a source checkbox per derived source_type, labeled w/ a count
    const githubBox = screen.getByRole('checkbox', { name: /github/i })
    const emailBox = screen.getByRole('checkbox', { name: /email/i })
    expect(githubBox).toBeInTheDocument()
    expect(emailBox).toBeInTheDocument()

    // unchecking email hides the email card, keeps github
    await userEvent.click(emailBox)
    await waitFor(() =>
      expect(screen.queryByText('Unread email from ops')).not.toBeInTheDocument(),
    )
    expect(screen.getByText('Review auth PR')).toBeInTheDocument()
  })

  it('filters the feed by time window using created_at', async () => {
    server.use(
      http.get('/api/triage/pending', () => HttpResponse.json([CARD, CARD2])),
    )
    renderPage()
    expect(await screen.findByText('Review auth PR')).toBeInTheDocument()
    expect(screen.getByText('Unread email from ops')).toBeInTheDocument()

    // 24H window: the 3-day-old email card drops, the 10m-old card stays
    await userEvent.click(screen.getByRole('button', { name: /^24H$/i }))
    await waitFor(() =>
      expect(screen.queryByText('Unread email from ops')).not.toBeInTheDocument(),
    )
    expect(screen.getByText('Review auth PR')).toBeInTheDocument()
  })

  it('shows the "no cards match filters" empty state (distinct from Inbox zero)', async () => {
    server.use(
      http.get('/api/triage/pending', () => HttpResponse.json([CARD2])),
    )
    renderPage()
    expect(await screen.findByText('Unread email from ops')).toBeInTheDocument()
    // narrow to 1H — the only card is 3 days old, so the filtered set is empty
    await userEvent.click(screen.getByRole('button', { name: /^1H$/i }))
    expect(await screen.findByText(/no cards match/i)).toBeInTheDocument()
    // and it is NOT the inbox-zero copy
    expect(screen.queryByText(/inbox zero|system harmony/i)).not.toBeInTheDocument()
    // clearing filters restores the card
    await userEvent.click(screen.getByRole('button', { name: /clear filters/i }))
    expect(await screen.findByText('Unread email from ops')).toBeInTheDocument()
  })

  it('renders the "Inbox zero / System Harmony" empty state when there are no cards', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([])))
    renderPage()
    expect(await screen.findByText(/system harmony|inbox zero/i)).toBeInTheDocument()
  })

  it('renders Throughput chart and Automation Stats in the analytics column', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD])))
    renderPage()
    await screen.findByText('Review auth PR')
    expect(await screen.findByText(/throughput/i)).toBeInTheDocument()
    expect(screen.getByText(/automation/i)).toBeInTheDocument()
    // auto_resolved_pct 0.42 → 42%
    expect(await screen.findByText(/42%/)).toBeInTheDocument()
  })

  it('renders "n/a" for Automation Stats when the metrics are null', async () => {
    server.use(
      http.get('/api/triage/pending', () => HttpResponse.json([CARD])),
      http.get('/api/stats/overview', () =>
        HttpResponse.json({
          metrics: { auto_resolved_pct: null, avg_triage_seconds: null },
        }),
      ),
    )
    renderPage()
    await screen.findByText('Review auth PR')
    expect(await screen.findAllByText(/n\/a/i)).toBeTruthy()
  })

  it('omits the LLM Insight panel when no option carries a suggestion_reason', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD])))
    renderPage()
    await screen.findByText('Review auth PR')
    expect(screen.queryByText(/llm insight/i)).not.toBeInTheDocument()
  })

  it('renders the LLM Insight panel when an option carries a real suggestion_reason', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD_BACKED])))
    renderPage()
    expect(await screen.findByText('Risky migration diff')).toBeInTheDocument()
    expect(await screen.findByText(/llm insight/i)).toBeInTheDocument()
    expect(screen.getByText(/low blast radius/i)).toBeInTheDocument()
  })

  it('J/K keyboard navigation moves the active card', async () => {
    server.use(
      http.get('/api/triage/pending', () => HttpResponse.json([CARD, CARD_BACKED])),
    )
    renderPage()
    await screen.findByText('Review auth PR')
    // first card active by default
    const cards = screen.getAllByTestId('triage-card')
    expect(cards[0]).toHaveAttribute('data-active', 'true')
    // J moves down
    await userEvent.keyboard('j')
    await waitFor(() =>
      expect(screen.getAllByTestId('triage-card')[1]).toHaveAttribute(
        'data-active',
        'true',
      ),
    )
    // K moves back up
    await userEvent.keyboard('k')
    await waitFor(() =>
      expect(screen.getAllByTestId('triage-card')[0]).toHaveAttribute(
        'data-active',
        'true',
      ),
    )
  })

  // --- P3: Slice 10 features (est priority, theme filter, card click-through, throughput chart) ---

  it('renders estimated priority badges with "est" prefix', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD_BACKED])))
    renderPage()
    await screen.findByText('Risky migration diff')
    // The priority badge should include "est" prefix text
    const estSpan = screen.getByText('est')
    expect(estSpan).toBeInTheDocument()
  })

  it('shows explanatory subtitle about estimated priorities', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD])))
    renderPage()
    await screen.findByText('Review auth PR')
    expect(screen.getByTestId('est-subtitle')).toBeInTheDocument()
    expect(screen.getByText(/estimated/i)).toBeInTheDocument()
    expect(screen.getByText(/not user-set/i)).toBeInTheDocument()
  })

  it('renders "Focus by theme" section in the filter rail', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD])))
    renderPage()
    await screen.findByText('Review auth PR')
    expect(screen.getByText(/focus by theme/i)).toBeInTheDocument()
    expect(screen.getAllByTestId('theme-card').length).toBeGreaterThan(0)
  })

  // --- Source-type badge + "open in source" link ---

  it('renders a source-type badge that labels the card kind', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD_LINKED])))
    renderPage()
    await screen.findByText('Triage incoming task')
    // meta_tasks → friendly "task" label on the badge
    const badge = screen.getByTestId('source-type-badge')
    expect(badge).toHaveTextContent(/task/i)
  })

  it('renders the source ref as an external link to source_url', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD_LINKED])))
    renderPage()
    await screen.findByText('Triage incoming task')
    const link = screen.getByRole('link', { name: /T123456/ })
    expect(link).toHaveAttribute('href', 'https://www.internalfb.com/tasks/?t=123456')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('shows the source-type badge but no link when source_url is absent', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD])))
    renderPage()
    await screen.findByText('Review auth PR')
    // github card has no source_url → badge present, but no source link
    expect(screen.getByTestId('source-type-badge')).toHaveTextContent(/github/i)
    expect(screen.queryByTestId('source-link')).not.toBeInTheDocument()
  })

  it('card summary is a clickable button that opens ItemFunnelDialog', async () => {
    server.use(http.get('/api/triage/pending', () => HttpResponse.json([CARD])))
    renderPage()
    await screen.findByText('Review auth PR')
    // Summary should be a button (not plain text)
    const summaryBtn = screen.getByTestId('card-summary-btn')
    expect(summaryBtn).toBeInTheDocument()
    expect(summaryBtn.tagName).toBe('BUTTON')
    // Clicking opens the funnel dialog
    await userEvent.click(summaryBtn)
    expect(await screen.findByTestId('funnel-dialog')).toBeInTheDocument()
  })
})
