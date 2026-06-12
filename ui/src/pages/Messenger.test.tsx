// Messenger page tests (spec Design Section 2.6, plan Task E4).
//
// Local render helper with QueryClientProvider + MemoryRouter + Toaster, driven
// through MSW (mirrors Sources.test.tsx). Covers the five UI states
// (loading / error w/ X-Request-ID / unauthorized / degraded / normal), the
// read view rendering type + allowlisted config + reachability HealthBadge,
// the guarantee that no secret field is ever rendered, and the edit form
// submitting a PATCH with a success toast.

import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { Messenger } from './Messenger'
import { _resetToken } from '@/lib/api'

const CONFIGURED = {
  configured: true,
  type: 'google_chat',
  class: 'GoogleChatMessenger',
  config: { space_id: 'spaces/AAA', timeout_seconds: 5 },
  reachable: true,
  checked_at: '2026-06-05T00:00:00Z',
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
        <Messenger />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Messenger page — embedded prop', () => {
  it('hides the h1 when embedded is true', async () => {
    server.use(http.get('/api/messenger', () => HttpResponse.json(CONFIGURED)))
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, refetchInterval: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Messenger embedded />
          <Toaster />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await screen.findByText('GoogleChatMessenger')
    const h1s = screen.queryAllByRole('heading', { level: 1 })
    const messengerH1 = h1s.filter((h) =>
      /^messenger$/i.test(h.textContent ?? ''),
    )
    expect(messengerH1).toHaveLength(0)
  })

  it('shows the h1 when embedded is not set', async () => {
    server.use(http.get('/api/messenger', () => HttpResponse.json(CONFIGURED)))
    renderPage()
    await screen.findByText('GoogleChatMessenger')
    const h1s = screen.queryAllByRole('heading', { level: 1 })
    const messengerH1 = h1s.filter((h) =>
      /^messenger$/i.test(h.textContent ?? ''),
    )
    expect(messengerH1).toHaveLength(1)
  })
})

describe('Messenger page', () => {
  it('renders the loading state while the query is pending', () => {
    server.use(http.get('/api/messenger', () => new Promise(() => {})))
    renderPage()
    expect(screen.getByTestId('messenger-loading')).toBeInTheDocument()
  })

  it('read view renders type, allowlisted config and reachability badge', async () => {
    server.use(http.get('/api/messenger', () => HttpResponse.json(CONFIGURED)))
    renderPage()
    expect(await screen.findByText('GoogleChatMessenger')).toBeInTheDocument()
    expect(screen.getByText('google_chat')).toBeInTheDocument()
    // allowlisted config values are shown
    expect(screen.getByText('spaces/AAA')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
    // reachability surfaces (healthy badge + label)
    expect(screen.getByText('reachable')).toBeInTheDocument()
    expect(screen.getByText('healthy')).toBeInTheDocument()
  })

  it('restyle: config values render with the mono token', async () => {
    server.use(http.get('/api/messenger', () => HttpResponse.json(CONFIGURED)))
    renderPage()
    // space_id and timeout_seconds are <Mono> values (font-mono) per spec §2/§12.
    const spaceId = await screen.findByText('spaces/AAA')
    expect(spaceId).toHaveClass('font-mono')
    expect(screen.getByText('5')).toHaveClass('font-mono')
  })

  it('restyle: degraded info state surfaces the no-messenger notice (role=status)', async () => {
    server.use(
      http.get('/api/messenger', () =>
        HttpResponse.json({ configured: false, type: null, class: null, config: {} }),
      ),
      http.get('/api/triage/pending', () => HttpResponse.json([{ id: 'c1' }])),
    )
    renderPage()
    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/no messenger configured/i)
    // count resolves from the pending query after the info banner mounts
    await waitFor(() => expect(status).toHaveTextContent(/1/))
  })

  it('never renders the service_account_key_path secret', async () => {
    // Even if a misbehaving backend leaked the secret, the page must not show it.
    server.use(
      http.get('/api/messenger', () =>
        HttpResponse.json({
          ...CONFIGURED,
          config: {
            ...CONFIGURED.config,
            service_account_key_path: '/secrets/sa.json',
          },
        }),
      ),
    )
    renderPage()
    await screen.findByText('GoogleChatMessenger')
    expect(screen.queryByText(/service_account_key_path/i)).not.toBeInTheDocument()
    expect(screen.queryByText('/secrets/sa.json')).not.toBeInTheDocument()
    // and there is no input that could capture a secret
    expect(screen.queryByLabelText(/service_account_key_path/i)).not.toBeInTheDocument()
  })

  it('edit form submits a PATCH with the new config and toasts on success', async () => {
    let patched: Record<string, unknown> | null = null
    server.use(
      http.get('/api/messenger', () => HttpResponse.json(CONFIGURED)),
      http.patch('/api/messenger', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'updated' })
      }),
    )
    renderPage()
    const input = await screen.findByLabelText('space_id')
    await userEvent.clear(input)
    await userEvent.type(input, 'spaces/BBB')
    await userEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() =>
      expect(patched).toMatchObject({ space_id: 'spaces/BBB', timeout_seconds: 5 }),
    )
    expect(await screen.findByText(/messenger updated/i)).toBeInTheDocument()
  })

  it('degraded state shows the pending triage count when not configured', async () => {
    server.use(
      http.get('/api/messenger', () =>
        HttpResponse.json({ configured: false, type: null, class: null, config: {} }),
      ),
      http.get('/api/triage/pending', () =>
        HttpResponse.json([{ id: 'c1' }, { id: 'c2' }, { id: 'c3' }]),
      ),
    )
    renderPage()
    expect(await screen.findByText(/no messenger configured/i)).toBeInTheDocument()
    expect(await screen.findByText('3')).toBeInTheDocument()
  })

  it('renders the error state with the X-Request-ID on failure', async () => {
    server.use(
      http.get('/api/messenger', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-2' } },
        ),
      ),
    )
    renderPage()
    expect(await screen.findByText(/req-2/)).toBeInTheDocument()
  })

  it('renders the unauthorized state when the token endpoint returns 401', async () => {
    server.use(
      http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/messenger', () => HttpResponse.json(CONFIGURED)),
    )
    renderPage()
    expect(await screen.findByText(/token unavailable/i)).toBeInTheDocument()
  })
})
