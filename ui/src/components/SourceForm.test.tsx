// SourceForm tests (spec Design Section 2.5, plan Task E3c).
//
// Drives the form through MSW with a local QueryClientProvider render helper.
// Covers: schedule preset Select driving the submitted cron, advanced custom
// cron overriding the preset, the client-side next-run preview (cron-parser)
// rendering for a valid cron and warning on an invalid one, and edit mode
// (adapter_type read-only, prefilled config, PATCH submit).

import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { SourceForm } from './SourceForm'
import { _resetToken } from '@/lib/api'
import type { SourceRollup } from '@/hooks/useStats'

const ADAPTER_TYPES = [
  {
    adapter_type: 'github',
    requires_connection: false,
    json_schema: {
      type: 'object',
      properties: { repos: { type: 'array', items: { type: 'string' } } },
    },
  },
]

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
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

const SOURCE: SourceRollup = {
  id: 's1',
  adapter_type: 'github',
  enabled: true,
  schedule: '0 * * * *',
  last_run: null,
  items_stored: 0,
  raw_enqueued: 0,
  in_flight: 0,
  health_status: 'healthy',
  config: { repos: ['meta/workbench'] },
}

function renderForm(props: Parameters<typeof SourceForm>[0]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SourceForm {...props} />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SourceForm', () => {
  it('create: schedule preset Select drives the submitted cron', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      http.post('/api/sources', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'new' })
      }),
    )
    renderForm({ onDone: () => {} })
    await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
    await userEvent.type(screen.getByLabelText(/repos/i), 'meta/workbench')
    await userEvent.selectOptions(
      screen.getByLabelText(/schedule preset/i),
      '0 * * * *',
    )
    await userEvent.click(screen.getByRole('button', { name: /create source/i }))
    await waitFor(() => expect(posted).toMatchObject({ schedule: '0 * * * *' }))
  })

  it('create: advanced custom cron overrides the preset', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      http.post('/api/sources', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'new' })
      }),
    )
    renderForm({ onDone: () => {} })
    await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
    await userEvent.type(screen.getByLabelText(/repos/i), 'meta/workbench')
    await userEvent.click(screen.getByRole('button', { name: /advanced/i }))
    const custom = screen.getByLabelText(/custom cron/i)
    await userEvent.clear(custom)
    await userEvent.type(custom, '30 2 * * 1')
    await userEvent.click(screen.getByRole('button', { name: /create source/i }))
    await waitFor(() => expect(posted).toMatchObject({ schedule: '30 2 * * 1' }))
  })

  it('create: next-run preview renders for a valid cron and warns on invalid', async () => {
    renderForm({ onDone: () => {} })
    await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
    expect(await screen.findByText(/next run:/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /advanced/i }))
    const custom = screen.getByLabelText(/custom cron/i)
    await userEvent.clear(custom)
    await userEvent.type(custom, 'not a cron')
    expect(await screen.findByText(/invalid cron/i)).toBeInTheDocument()
  })

  it('edit mode: adapter_type read-only, prefilled config, submits PATCH', async () => {
    let patched: Record<string, unknown> | null = null
    server.use(
      http.patch('/api/sources/s1', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 's1' })
      }),
    )
    renderForm({ source: SOURCE, onDone: () => {} })
    expect(screen.queryByText(/pick an adapter type/i)).not.toBeInTheDocument()
    expect(
      await screen.findByText(/adapter_type: github \(immutable\)/i),
    ).toBeInTheDocument()
    expect((screen.getByLabelText(/repos/i) as HTMLInputElement).value).toBe(
      'meta/workbench',
    )
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }))
    await waitFor(() =>
      expect(patched).toMatchObject({
        schedule: '0 * * * *',
        config: { repos: ['meta/workbench'] },
      }),
    )
  })
})
