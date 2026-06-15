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

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    healthyHandler(),
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
    expect(screen.getByTestId('legend-core')).toHaveStyle({ background: '#ff6a2b' })
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
