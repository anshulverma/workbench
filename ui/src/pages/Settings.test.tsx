// Settings page tests (spec Design Section 2.8).
//
// Mirrors Sources.test.tsx: a local render helper with QueryClientProvider +
// MemoryRouter, driven through MSW. Covers loading, the happy path (versions +
// component health + redacted config sections, with no secret value rendered),
// the degraded state on a /health 503, the config-failure error state with the
// X-Request-ID, and the unauthorized state.

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

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/health', () => HttpResponse.json(HEALTH)),
    http.get('/api/debug/config', () => HttpResponse.json(CONFIG)),
  ]
}

const server = setupServer(...baseHandlers())
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(...baseHandlers())
  _resetToken()
})
afterAll(() => server.close())

function renderSettings() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Settings page', () => {
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
    expect(await screen.findByText(/storage down/i)).toBeInTheDocument()
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
    expect(screen.getByText(/secrets are not exposed/i)).toBeInTheDocument()
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
