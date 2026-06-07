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

const CARD = {
  id: 'c1',
  card_content: { summary: 'Review auth PR' },
  options: [
    { label: 'Add todo', action: 'add_todo' },
    { label: 'Skip', action: 'skip' },
  ],
  relevance_score: 80,
  status: 'sent',
}

function baseHandlers() {
  return [http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' }))]
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
    expect(screen.getByRole('button', { name: /1\. add todo/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /2\. skip/i })).toBeInTheDocument()
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
    await userEvent.click(await screen.findByRole('button', { name: /1\. add todo/i }))
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
    await userEvent.click(await screen.findByRole('button', { name: /1\. add todo/i }))
    expect(await screen.findByText(/already answered elsewhere/i)).toBeInTheDocument()
  })
})
