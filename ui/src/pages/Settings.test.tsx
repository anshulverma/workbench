// Settings page tests (spec Design Section 2.8) — updated for the sub-tab
// refactor (Slice 8).
//
// Tests cover: tab navigation (System/Sources/Messenger), that the correct
// sub-panel renders for each tab, ARIA attributes on the tab bar, and all the
// original System-tab tests (loading, happy path, degraded, error, secrets,
// backup download, vanity block dropped).

import {
  describe,
  it,
  expect,
  beforeAll,
  afterAll,
  afterEach,
  vi,
} from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Settings } from './Settings'
import { _resetToken } from '@/lib/api'

const HEALTH = {
  status: 'healthy',
  version: '0.1.0',
  components: {
    storage: { status: 'healthy' },
    connections: { google_chat: { status: 'healthy' } },
  },
  queue: {},
}

const CONFIG = {
  config: {
    version: '0.4.0',
    pipeline: { include_threshold: 70 },
    scheduler: { poll_interval: 900 },
    retention: { days: 30 },
    alerting: { enabled: false },
    server: { api_token: '[REDACTED]' },
  },
}

const MESSENGER_CONFIGURED = {
  configured: true,
  type: 'google_chat',
  class: 'GoogleChatMessenger',
  config: { space_id: 'spaces/AAA', timeout_seconds: 5 },
  reachable: true,
  checked_at: '2026-06-05T00:00:00Z',
}

const SOURCE_ROW = {
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

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/health', () => HttpResponse.json(HEALTH)),
    http.get('/api/debug/config', () => HttpResponse.json(CONFIG)),
    http.get('/api/messenger', () => HttpResponse.json(MESSENGER_CONFIGURED)),
    http.get('/api/stats/sources', () => HttpResponse.json([SOURCE_ROW])),
    http.get('/api/sources/adapter-types', () => HttpResponse.json([])),
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

function renderSettings(initialRoute = '/settings') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Settings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Settings page — tab container', () => {
  it('renders all three tab triggers with correct labels', async () => {
    renderSettings()
    // The tabs render synchronously
    expect(screen.getByRole('tab', { name: /system/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /sources/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /messenger/i })).toBeInTheDocument()
  })

  it('has a tablist ARIA container', () => {
    renderSettings()
    expect(screen.getByRole('tablist')).toBeInTheDocument()
  })

  it('defaults to the System tab and shows a tabpanel', async () => {
    renderSettings()
    const systemTab = screen.getByRole('tab', { name: /system/i })
    expect(systemTab).toHaveAttribute('aria-selected', 'true')
    // System tab content renders (versions section appears)
    expect(await screen.findByText(/0\.1\.0/)).toBeInTheDocument()
    expect(screen.getByRole('tabpanel')).toBeInTheDocument()
  })

  it('clicking Sources tab renders Sources content', async () => {
    renderSettings()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /sources/i }))
    // Sources tab becomes active
    expect(screen.getByRole('tab', { name: /sources/i })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    // Sources content should appear (github source card)
    expect(await screen.findByText('github')).toBeInTheDocument()
  })

  it('clicking Messenger tab renders Messenger content', async () => {
    renderSettings()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /messenger/i }))
    expect(screen.getByRole('tab', { name: /messenger/i })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(await screen.findByText('GoogleChatMessenger')).toBeInTheDocument()
  })

  it('renders the page h1 "Settings" always (not duplicated by sub-tabs)', async () => {
    renderSettings()
    const h1s = screen.getAllByRole('heading', { level: 1 })
    // Only one h1 with "Settings" — sub-tabs should not add their own
    const settingsH1 = h1s.filter((h) => /settings/i.test(h.textContent ?? ''))
    expect(settingsH1).toHaveLength(1)
  })

  it('Sources sub-tab does not show a duplicate h1', async () => {
    renderSettings('/settings/sources')
    await screen.findByText('github')
    // No "Sources" h1 — only the parent "Settings" h1
    const h1s = screen.getAllByRole('heading', { level: 1 })
    const sourcesH1 = h1s.filter((h) => /^sources$/i.test(h.textContent ?? ''))
    expect(sourcesH1).toHaveLength(0)
  })

  it('Messenger sub-tab does not show a duplicate h1', async () => {
    renderSettings('/settings/messenger')
    await screen.findByText('GoogleChatMessenger')
    const h1s = screen.getAllByRole('heading', { level: 1 })
    const messengerH1 = h1s.filter((h) =>
      /^messenger$/i.test(h.textContent ?? ''),
    )
    expect(messengerH1).toHaveLength(0)
  })
})

describe('Settings page — System tab content', () => {
  it('renders the loading state while data is pending', () => {
    server.use(http.get('/health', () => new Promise(() => {})))
    renderSettings()
    expect(screen.getByTestId('settings-loading')).toBeInTheDocument()
  })

  it('shows versions, component health, and redacted config sections', async () => {
    renderSettings()
    // app version + config version
    expect(await screen.findByText(/0\.1\.0/)).toBeInTheDocument()
    expect(screen.getByText(/0\.4\.0/)).toBeInTheDocument()
    // redacted config section content
    expect(screen.getByText(/include_threshold/)).toBeInTheDocument()
    // component health
    expect(screen.getByText('storage')).toBeInTheDocument()
    expect(screen.getByText('google_chat')).toBeInTheDocument()
    // no obvious secret value leaks (the redacted token is the only hint)
    expect(screen.queryByText(/dev-token/)).not.toBeInTheDocument()
    expect(screen.queryByText(/sk-/)).not.toBeInTheDocument()
  })

  it('renders the degraded state on a /health 503', async () => {
    server.use(
      http.get('/health', () =>
        HttpResponse.json(
          {
            status: 'unhealthy',
            version: '0.1.0',
            components: { storage: { status: 'unhealthy' }, connections: {} },
          },
          { status: 503 },
        ),
      ),
    )
    renderSettings()
    expect(await screen.findByText(/zep_memory connection degraded/i)).toBeInTheDocument()
  })

  it('renders the error state when /api/debug/config fails', async () => {
    server.use(
      http.get('/api/debug/config', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-8' } },
        ),
      ),
    )
    renderSettings()
    await waitFor(() => expect(screen.getByText(/req-8/)).toBeInTheDocument())
  })

  it('renders the unauthorized state when the token endpoint 401s', async () => {
    server.use(
      http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
    )
    renderSettings()
    await waitFor(() =>
      expect(screen.getByText(/token unavailable/i)).toBeInTheDocument(),
    )
  })

  it('tokenizes a config section via the JSON highlighter (no raw HTML)', async () => {
    const { container } = renderSettings()
    await screen.findByText(/include_threshold/)
    // The highlighter emits token spans, never raw HTML injection.
    expect(container.querySelector('.tok-key')).not.toBeNull()
    expect(container.querySelector('.tok-number')).not.toBeNull()
    expect(container.querySelector('[dangerouslySetInnerHTML]')).toBeNull()
  })

  it('shows a locked secrets vault panel and never renders secret values', async () => {
    renderSettings()
    await screen.findByText(/include_threshold/)
    expect(screen.getByTestId('secrets-vault')).toBeInTheDocument()
    expect(screen.getByText(/never exposed/i)).toBeInTheDocument()
    // The redacted token marker may appear, but never a real secret value.
    expect(screen.queryByText(/dev-token/)).not.toBeInTheDocument()
    expect(screen.queryByText(/api_token/)).not.toBeInTheDocument()
  })

  it('downloads a backup blob of the redacted config', async () => {
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:mock')
    const revokeObjectURL = vi.fn((_url: string) => {})
    // jsdom lacks these; stub them on the URL object.
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {})

    const user = userEvent.setup()
    renderSettings()
    const btn = await screen.findByRole('button', { name: /download backup/i })
    await user.click(btn)

    expect(createObjectURL).toHaveBeenCalledTimes(1)
    const blob = createObjectURL.mock.calls[0][0]
    expect(blob).toBeInstanceOf(Blob)
    expect(blob.type).toContain('application/json')
    expect(clickSpy).toHaveBeenCalled()
    clickSpy.mockRestore()
  })

  it('drops the vanity Runtime Metadata block', async () => {
    renderSettings()
    await screen.findByText(/app version/i)
    for (const m of [/kernel/i, /\barch\b/i, /memory usage/i, /network latency/i]) {
      expect(screen.queryByText(m)).toBeNull()
    }
  })
})
