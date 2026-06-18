// SystemStatus page tests (v4 system status diagram).
//
// Covers: loading/error/unauthorized states, node rendering, legend display,
// node click opens log viewer, log search filtering, log level tabs, and stat
// card counts.

import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { SystemStatus } from './SystemStatus'
import { _resetToken } from '@/lib/api'

// MSW handlers

function healthyHandler() {
  return http.get('/health', () =>
    HttpResponse.json({
      status: 'ok',
      version: '0.4.0',
      components: {
        storage: { status: 'healthy' },
        connections: {},
      },
      queue: { ingestion_depth: 0, triage_pending: 0, dead_letters: 0 },
    }),
  )
}

// ---- LLM API fixtures + handlers ---- //

const LLM_CALLS = [
  {
    id: 'llm_101',
    ts: '2026-06-16T09:00:00Z',
    origin: 'fr_31',
    purpose: 'classify · drop-confidence',
    stage: 'filter',
    model: 'claude-haiku-4-2',
    temperature: 0.2,
    status: 'ok',
    batch: 1,
    items: ['D12871'],
    tokens_in: 420,
    tokens_out: 88,
    latency_ms: 120,
  },
  {
    id: 'llm_102',
    ts: '2026-06-16T09:01:00Z',
    origin: 'en_github',
    purpose: 'enrich · summarize diff',
    stage: 'enricher',
    model: 'claude-opus-4-8',
    temperature: 0,
    status: 'ok',
    batch: 3,
    items: ['D12863', 'D12864', 'D12865'],
    tokens_in: 1800,
    tokens_out: 240,
    latency_ms: 540,
  },
  {
    id: 'llm_103',
    ts: '2026-06-16T09:02:00Z',
    origin: 'triage',
    purpose: 'score · relevance + priority',
    stage: 'triage',
    model: 'claude-opus-4-8',
    temperature: 0.2,
    status: 'error',
    batch: 1,
    items: ['eml_5521'],
    tokens_in: 600,
    tokens_out: null,
    latency_ms: null,
  },
]

const LLM_DETAIL = {
  sysPrompt: 'You are a noise filter. Return whether the rule fires.',
  subcalls: [
    {
      item: 'D12871',
      prompt: '[item D12871] classify · drop-confidence',
      completion: '{"fires": false, "confidence": 88}',
      structured: { fires: false, confidence: 88 },
      tokens_in: 420,
      tokens_out: 88,
    },
  ],
}

const LLM_DETAIL_BATCHED = {
  sysPrompt: 'You enrich an item with structured metadata.',
  subcalls: [
    {
      item: '5.1',
      prompt: '[item D12863] enrich · summarize diff',
      completion: '{"summary": "one"}',
      structured: { summary: 'one' },
      tokens_in: 600,
      tokens_out: 80,
    },
    {
      item: 'relevance batch',
      prompt: '[item D12864] enrich · summarize diff',
      completion: '{"summary": "two"}',
      structured: { summary: 'two' },
      tokens_in: 600,
      tokens_out: 80,
    },
    {
      item: 'D12865',
      prompt: '[item D12865] enrich · summarize diff',
      completion: '{"summary": "three"}',
      structured: { summary: 'three' },
      tokens_in: 600,
      tokens_out: 80,
    },
  ],
}

const LLM_METRICS = {
  calls_24h: 3008,
  avg_latency_ms: 330,
  error_rate: 0.04,
  batched_pct: 0.33,
  window_hours: 24,
  as_of: '2026-06-16T09:05:00Z',
}

function llmHandlers() {
  return [
    http.get('/api/llm/calls', () => HttpResponse.json(LLM_CALLS)),
    http.get('/api/llm/calls/:id', ({ params }) =>
      HttpResponse.json(params.id === 'llm_102' ? LLM_DETAIL_BATCHED : LLM_DETAIL),
    ),
    http.get('/api/llm/metrics', () => HttpResponse.json(LLM_METRICS)),
  ]
}

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    healthyHandler(),
    ...llmHandlers(),
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
        <SystemStatus />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SystemStatus page', () => {
  it('renders the loading state while the health query is pending', () => {
    server.use(http.get('/health', () => new Promise(() => {})))
    renderPage()
    expect(screen.getByTestId('system-loading')).toBeInTheDocument()
  })

  it('renders the error state when health returns 500', async () => {
    server.use(
      http.get('/health', () =>
        HttpResponse.json(
          { detail: 'internal error' },
          { status: 500, headers: { 'X-Request-ID': 'req-sys-500' } },
        ),
      ),
    )
    renderPage()
    expect(await screen.findByTestId('system-error')).toBeInTheDocument()
    expect(screen.getByText(/req-sys-500/)).toBeInTheDocument()
  })

  it('renders the unauthorized state on 401', async () => {
    server.use(
      http.get('/api/auth/token', () =>
        new HttpResponse(null, { status: 401 }),
      ),
    )
    renderPage()
    await waitFor(() =>
      expect(screen.getByText(/token unavailable/i)).toBeInTheDocument(),
    )
  })

  it('renders all nodes from default mock data', async () => {
    renderPage()
    // Wait for the page to load
    expect(await screen.findByTestId('system-status-page')).toBeInTheDocument()
    // Check that key nodes are rendered
    expect(screen.getByTestId('system-node-phabricator')).toBeInTheDocument()
    expect(screen.getByTestId('system-node-gchat')).toBeInTheDocument()
    expect(screen.getByTestId('system-node-github')).toBeInTheDocument()
    expect(screen.getByTestId('system-node-workbench')).toBeInTheDocument()
    expect(screen.getByTestId('system-node-postgres')).toBeInTheDocument()
    expect(screen.getByTestId('system-node-memory')).toBeInTheDocument()
    expect(screen.getByTestId('system-node-llm')).toBeInTheDocument()
    expect(screen.getByTestId('system-node-disk')).toBeInTheDocument()
    // Check total: 12 nodes
    const diagram = screen.getByTestId('system-diagram')
    const nodeEls = diagram.querySelectorAll('[data-testid^="system-node-"]')
    expect(nodeEls.length).toBe(12)
  })

  it('legend shows role colors and planned indicator', async () => {
    renderPage()
    expect(await screen.findByTestId('diagram-legend')).toBeInTheDocument()
    expect(screen.getByTestId('legend-connector')).toBeInTheDocument()
    expect(screen.getByTestId('legend-service')).toBeInTheDocument()
    expect(screen.getByTestId('legend-core')).toBeInTheDocument()
    expect(screen.getByTestId('legend-storage')).toBeInTheDocument()
    expect(screen.getByTestId('legend-planned')).toBeInTheDocument()
    // Check role colors
    expect(screen.getByTestId('legend-connector')).toHaveStyle({ background: '#71d2ff' })
    expect(screen.getByTestId('legend-service')).toHaveStyle({ background: '#b79cf7' })
    expect(screen.getByTestId('legend-core')).toHaveStyle({ background: '#f5a623' })
    expect(screen.getByTestId('legend-storage')).toHaveStyle({ background: '#9ad08a' })
  })

  it('node click opens log viewer', async () => {
    renderPage()
    expect(await screen.findByTestId('system-status-page')).toBeInTheDocument()
    // Click on the phabricator node
    await userEvent.click(screen.getByTestId('system-node-phabricator'))
    // Log viewer should appear
    expect(await screen.findByRole('dialog', { name: /Phabricator logs/i })).toBeInTheDocument()
    // Should show log lines
    const logLines = screen.getAllByTestId('log-line')
    expect(logLines.length).toBeGreaterThan(0)
  })

  it('log viewer search filters lines', async () => {
    renderPage()
    expect(await screen.findByTestId('system-status-page')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('system-node-phabricator'))
    await screen.findByRole('dialog')

    const initialLines = screen.getAllByTestId('log-line')
    const initialCount = initialLines.length

    // Type a search query that matches only one line
    const searchInput = screen.getByTestId('log-search-input')
    await userEvent.type(searchInput, 'rate limit')

    await waitFor(() => {
      const filtered = screen.getAllByTestId('log-line')
      expect(filtered.length).toBeLessThan(initialCount)
    })
    // The matching line should still be there
    expect(screen.getByText(/rate limit approaching/)).toBeInTheDocument()
  })

  it('log viewer level tabs filter by level', async () => {
    renderPage()
    expect(await screen.findByTestId('system-status-page')).toBeInTheDocument()
    // Open memory node logs (has INFO, WARN, ERROR)
    await userEvent.click(screen.getByTestId('system-node-memory'))
    await screen.findByRole('dialog')

    const allLines = screen.getAllByTestId('log-line')
    expect(allLines.length).toBe(3) // INFO, WARN, ERROR

    // Click WARN tab
    await userEvent.click(screen.getByTestId('level-tab-WARN'))
    await waitFor(() => {
      const warnLines = screen.getAllByTestId('log-line')
      expect(warnLines.length).toBe(1)
    })

    // Click ERROR tab
    await userEvent.click(screen.getByTestId('level-tab-ERROR'))
    await waitFor(() => {
      const errorLines = screen.getAllByTestId('log-line')
      expect(errorLines.length).toBe(1)
    })

    // Back to all
    await userEvent.click(screen.getByTestId('level-tab-all'))
    await waitFor(() => {
      const resetLines = screen.getAllByTestId('log-line')
      expect(resetLines.length).toBe(3)
    })
  })

  it('stat cards show correct counts', async () => {
    renderPage()
    expect(await screen.findByTestId('stat-cards')).toBeInTheDocument()
    const statCards = screen.getByTestId('stat-cards')

    // Operational: 9 healthy out of 10 live (12 total minus 2 planned)
    expect(within(statCards).getByText('9/10')).toBeInTheDocument()
    // Degraded: 1
    expect(within(statCards).getByText('1')).toBeInTheDocument()
    // Connectors: 4
    expect(within(statCards).getByText('4')).toBeInTheDocument()
    // Config version
    expect(within(statCards).getByText('0.4.0')).toBeInTheDocument()
  })

  it('shows degraded banner when a node is degraded', async () => {
    renderPage()
    expect(await screen.findByTestId('system-status-page')).toBeInTheDocument()
    expect(screen.getByTestId('degraded-banner')).toBeInTheDocument()
    expect(
      screen.getByText(/Memory layer \(Zep\) is degraded/),
    ).toBeInTheDocument()
  })

  it('close button dismisses the log viewer', async () => {
    renderPage()
    expect(await screen.findByTestId('system-status-page')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('system-node-phabricator'))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /close/i }))
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    )
  })
})

describe('SystemStatus — LLM Infra sub-tab', () => {
  // The diagram is the default tab; the LLM Infra tab is a sibling sub-view.
  // Rows now come from the mocked /api/llm/calls endpoint.
  async function openLLMTab() {
    renderPage()
    expect(await screen.findByTestId('system-status-page')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('system-tab-llm'))
    expect(await screen.findByTestId('llm-infra')).toBeInTheDocument()
    // Wait for the fetched rows to render.
    await screen.findAllByTestId('llm-log-row')
  }

  it('defaults to the diagram tab and hides the LLM panel', async () => {
    renderPage()
    expect(await screen.findByTestId('system-diagram')).toBeInTheDocument()
    expect(screen.queryByTestId('llm-infra')).not.toBeInTheDocument()
  })

  it('switches to the LLM Infra tab, hiding the diagram', async () => {
    await openLLMTab()
    expect(screen.queryByTestId('system-diagram')).not.toBeInTheDocument()
    expect(screen.getByText('LLM Invocation Log')).toBeInTheDocument()
  })

  it('shows LLM stat rollups from /api/llm/metrics', async () => {
    await openLLMTab()
    const cards = screen.getByTestId('llm-stat-cards')
    expect(within(cards).getByText('Calls (24h)')).toBeInTheDocument()
    expect(within(cards).getByText('Avg Latency')).toBeInTheDocument()
    expect(within(cards).getByText('Error Rate')).toBeInTheDocument()
    expect(within(cards).getByText('Batched')).toBeInTheDocument()
    // From LLM_METRICS fixture.
    await waitFor(() =>
      expect(within(cards).getByText('3,008')).toBeInTheDocument(),
    )
    expect(within(cards).getByText('330ms')).toBeInTheDocument()
    expect(within(cards).getByText('4%')).toBeInTheDocument() // error_rate 0.04
    expect(within(cards).getByText('33%')).toBeInTheDocument() // batched_pct 0.33
  })

  it('renders the invocation rows from the API', async () => {
    await openLLMTab()
    const rows = screen.getAllByTestId('llm-log-row')
    expect(rows.length).toBe(LLM_CALLS.length)
    expect(screen.getByText('classify · drop-confidence')).toBeInTheDocument()
    expect(screen.getByText('enrich · summarize diff')).toBeInTheDocument()
  })

  it('filters the fetched rows by query', async () => {
    await openLLMTab()
    const before = screen.getAllByTestId('llm-log-row').length
    await userEvent.type(screen.getByTestId('llm-search-input'), 'enrich')
    await waitFor(() => {
      expect(screen.getAllByTestId('llm-log-row').length).toBeLessThan(before)
    })
    for (const row of screen.getAllByTestId('llm-log-row')) {
      expect(row.textContent?.toLowerCase()).toContain('enrich')
    }
  })

  it('opens a call detail dialog fetched from /api/llm/calls/:id', async () => {
    await openLLMTab()
    await userEvent.click(screen.getAllByTestId('llm-log-row')[0])
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByTestId('llm-detail-stage')).toBeInTheDocument()
    expect(within(dialog).getByText('System prompt')).toBeInTheDocument()
    // System prompt text comes from the detail endpoint.
    expect(
      await within(dialog).findByText(/noise filter/i),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('Structured output')).toBeInTheDocument()
  })

  it('batched calls expose a sub-call selector to step through items', async () => {
    await openLLMTab()
    // The 2nd row (index 1, en_github) carries a batch of 3.
    await userEvent.click(screen.getAllByTestId('llm-log-row')[1])
    const dialog = await screen.findByRole('dialog')
    const selector = await within(dialog).findByTestId('llm-subcall-selector')
    expect(selector).toBeInTheDocument()
    expect(within(dialog).getByText(/batch ×3/i)).toBeInTheDocument()
    expect(within(dialog).getByTestId('llm-subcall-0')).toBeInTheDocument()
    expect(within(dialog).getByTestId('llm-subcall-2')).toBeInTheDocument()
  })

  it('links a path-shaped subcall item to its lineage page', async () => {
    await openLLMTab()
    // The 2nd row (index 1, en_github) carries a batch of 3 with subcall items
    // [5.1, relevance batch, D12865].
    await userEvent.click(screen.getAllByTestId('llm-log-row')[1])
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByTestId('llm-subcall-selector')
    const link = await within(dialog).findByRole('link', { name: '#5.1' })
    expect(link).toHaveAttribute('href', '/items/5.1')
    // free-text item stays a plain label, not a link
    expect(
      within(dialog).queryByRole('link', { name: /relevance batch/ }),
    ).toBeNull()
  })

  it('closes the call detail dialog', async () => {
    await openLLMTab()
    await userEvent.click(screen.getAllByTestId('llm-log-row')[0])
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /close/i }))
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    )
  })
})
