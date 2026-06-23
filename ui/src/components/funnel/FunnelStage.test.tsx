import { describe, it, expect, beforeEach, afterEach, afterAll } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { FunnelStage } from './FunnelStage'
import type { FunnelStage as FunnelStageType, FunnelItem } from '@/lib/types/funnel'

// ---------------------------------------------------------------------------
// MSW server for server-backed tests
// ---------------------------------------------------------------------------

const server = setupServer()
let serverStarted = false

beforeEach(() => {
  if (!serverStarted) {
    server.listen({ onUnhandledRequest: 'bypass' })
    serverStarted = true
  }
})

afterEach(() => {
  server.resetHandlers()
})

afterAll(() => {
  if (serverStarted) {
    server.close()
    serverStarted = false
  }
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeStage(overrides: Partial<FunnelStageType> = {}): FunnelStageType {
  return {
    filterId: 'fr_01',
    outcome: 'drop',
    reason: 'Matched auto-drop pattern',
    confidence: 92,
    ...overrides,
  }
}

function makeItem(overrides: Partial<FunnelItem> = {}): FunnelItem {
  return {
    id: 1,
    summary: 'Test PR #42',
    source: 'github',
    created_at: '2026-06-10T12:00:00Z',
    stages: [makeStage()],
    verdict: { decision: 'dropped', rationale: 'auto-dropped', confidence: 92 },
    ...overrides,
  }
}

function renderStage(props: {
  stage: FunnelStageType
  index: number
  isLast: boolean
  item?: FunnelItem | null
  editable?: boolean
  timing?: { at: number; dur: number } | null
  baseTime?: number | null
  filterRules?: Array<{ id: number; prompt: string }>
  enrichers?: Array<{ id: number; label: string }>
}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <FunnelStage {...props} />
    </QueryClientProvider>
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FunnelStage', () => {
  it('renders stage with order number and filterId', () => {
    renderStage({ stage: makeStage(), index: 0, isLast: false })
    expect(screen.getByText(/01 · fr_01/)).toBeInTheDocument()
  })

  it('renders the ActionChip with the stage outcome', () => {
    const { container } = renderStage({
      stage: makeStage({ outcome: 'drop' }),
      index: 0,
      isLast: false,
    })
    expect(container.querySelector('[data-action="drop"]')).toBeInTheDocument()
  })

  it('shows connecting line when not last', () => {
    renderStage({ stage: makeStage(), index: 0, isLast: false })
    expect(screen.getByTestId('connecting-line')).toBeInTheDocument()
  })

  it('hides connecting line when last', () => {
    renderStage({ stage: makeStage(), index: 2, isLast: true })
    expect(screen.queryByTestId('connecting-line')).not.toBeInTheDocument()
  })

  it('shows enricher badge for enricher stages', () => {
    renderStage({
      stage: makeStage({ filterId: 'en_github', outcome: 'context' }),
      index: 0,
      isLast: false,
    })
    expect(screen.getByTestId('enricher-badge')).toBeInTheDocument()
    expect(screen.getByText(/enricher/)).toBeInTheDocument()
  })

  it('does not show enricher badge for filter stages', () => {
    renderStage({ stage: makeStage({ filterId: 'fr_01' }), index: 0, isLast: false })
    expect(screen.queryByTestId('enricher-badge')).not.toBeInTheDocument()
  })

  it('shows timing info when provided', () => {
    renderStage({
      stage: makeStage(),
      index: 0,
      isLast: false,
      timing: { at: 50, dur: 80 },
    })
    const timingEl = screen.getByTestId('timing-info')
    expect(timingEl).toHaveTextContent('+50ms')
    expect(timingEl).toHaveTextContent('80ms')
  })

  it('does not show timing info when not provided', () => {
    renderStage({ stage: makeStage(), index: 0, isLast: false })
    expect(screen.queryByTestId('timing-info')).not.toBeInTheDocument()
  })

  it('shows correct button when editable and item provided', () => {
    renderStage({
      stage: makeStage(),
      index: 0,
      isLast: false,
      item: makeItem(),
      editable: true,
    })
    expect(screen.getByTestId('correct-button')).toBeInTheDocument()
    expect(screen.getByText('correct')).toBeInTheDocument()
  })

  it('does not show correct button for enricher stages even when editable', () => {
    renderStage({
      stage: makeStage({ filterId: 'en_github', outcome: 'context' }),
      index: 0,
      isLast: false,
      item: makeItem(),
      editable: true,
    })
    expect(screen.queryByTestId('correct-button')).not.toBeInTheDocument()
  })

  it('opens correction picker on correct click', async () => {
    const user = userEvent.setup()
    renderStage({
      stage: makeStage({ outcome: 'drop' }),
      index: 0,
      isLast: false,
      item: makeItem(),
      editable: true,
    })
    await user.click(screen.getByTestId('correct-button'))
    expect(screen.getByTestId('correction-picker')).toBeInTheDocument()
    expect(screen.getByText('This should have been...')).toBeInTheDocument()
    // Should not show the current outcome as a choice
    expect(screen.queryByText('Drop')).not.toBeInTheDocument()
    expect(screen.getByText('Keep / include')).toBeInTheDocument()
  })

  it('posts a correction + tuning task and shows the receipt with a task link', async () => {
    const posted: Record<string, unknown>[] = []
    let correctionsData: unknown[] = []
    let tasksData: unknown[] = []

    server.use(
      http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })),
      http.post('/api/feedback/corrections', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        posted.push(body)
        const correction = {
          id: 7,
          item_id: 1,
          filter_id: 'fr_01',
          original_action: 'drop',
          corrected_action: 'include',
          item_summary: 'Test PR #42',
          from_label: null,
          to_label: null,
          reason: null,
          created_at: '2026-06-22T12:00:00Z',
        }
        correctionsData = [correction]
        return HttpResponse.json(correction)
      }),
      http.post('/api/feedback/tasks', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        posted.push(body)
        const task = {
          id: 42,
          filter_id: 'fr_01',
          item_id: 1,
          status: 'open',
          proposed_prompt: body.proposed_prompt,
          correction_ids: [7],
          item_summary: 'Test PR #42',
          from_outcome: 'drop',
          to_outcome: 'include',
          from_label: null,
          to_label: null,
          filter_prompt: 'test prompt',
          kind: 'filter-tuning',
          created_at: '2026-06-22T12:00:00Z',
          resolved_at: null,
        }
        tasksData = [task]
        return HttpResponse.json(task)
      }),
      http.get('/api/feedback/corrections', () => HttpResponse.json(correctionsData)),
      http.get('/api/feedback/tasks', () => HttpResponse.json(tasksData))
    )

    const user = userEvent.setup()
    renderStage({
      stage: makeStage({ outcome: 'drop' }),
      index: 0,
      isLast: false,
      item: makeItem(),
      editable: true,
      filterRules: [{ id: 1, prompt: 'test prompt' }],
    })

    // Wait for initial queries to settle
    await waitFor(() => expect(screen.getByTestId('correct-button')).toBeInTheDocument())

    await user.click(screen.getByTestId('correct-button'))
    await user.click(screen.getByText(/keep.*include/i))

    // Wait for the POST requests
    await waitFor(() => expect(posted).toHaveLength(2))

    // Verify correction POST
    expect(posted[0]).toMatchObject({
      item_id: 1,
      filter_id: 'fr_01',
      original_action: 'drop',
      corrected_action: 'include',
    })

    // Verify task POST
    expect(posted[1]).toMatchObject({
      filter_id: 'fr_01',
      item_id: 1,
      status: 'open',
      kind: 'filter-tuning',
      correction_ids: [7],
    })

    // Wait for the receipt to appear
    const link = await screen.findByRole('link', { name: /view the filter-tuning task/i })
    expect(link).toHaveAttribute('href', '#/actions?tuning=42')
  })

  it('removes correction on undo click', async () => {
    let deleted = false
    server.use(
      http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })),
      http.get('/api/feedback/corrections', ({ request }) => {
        const url = new URL(request.url)
        if (url.searchParams.get('item_id') === '1') {
          return HttpResponse.json(
            deleted
              ? []
              : [
                  {
                    id: 7,
                    item_id: 1,
                    filter_id: 'fr_01',
                    original_action: 'drop',
                    corrected_action: 'include',
                    item_summary: 'Test PR #42',
                    from_label: null,
                    to_label: null,
                    reason: null,
                    created_at: '2026-06-22T12:00:00Z',
                  },
                ]
          )
        }
        return HttpResponse.json([])
      }),
      http.get('/api/feedback/tasks', () =>
        HttpResponse.json([
          {
            id: 42,
            filter_id: 'fr_01',
            item_id: 1,
            status: 'open',
            proposed_prompt: 'p',
            correction_ids: [7],
            created_at: '2026-06-22T12:00:00Z',
            resolved_at: null,
          },
        ])
      ),
      http.delete('/api/feedback/corrections/7', () => {
        deleted = true
        return HttpResponse.json({ status: 'deleted' })
      })
    )

    const user = userEvent.setup()
    renderStage({
      stage: makeStage({ outcome: 'drop' }),
      index: 0,
      isLast: false,
      item: makeItem(),
      editable: true,
      filterRules: [{ id: 1, prompt: 'test prompt' }],
    })

    // Wait for initial corrections to load
    await waitFor(() => expect(screen.getByTestId('undo-button')).toBeInTheDocument())

    await user.click(screen.getByTestId('undo-button'))

    // Wait for the deletion to complete
    await waitFor(() => expect(deleted).toBe(true))

    // Corrections query will refetch, showing empty array
    await waitFor(() => {
      expect(screen.queryByTestId('override-display')).not.toBeInTheDocument()
    })

    expect(screen.getByTestId('correct-button')).toBeInTheDocument()
  })

  it('shows context badge when stage has context', () => {
    renderStage({
      stage: makeStage({ context: 'author: alice · files: 3' }),
      index: 0,
      isLast: false,
    })
    expect(screen.getByTestId('context-badge')).toBeInTheDocument()
    expect(screen.getByText('author: alice · files: 3')).toBeInTheDocument()
  })

  it('shows reason text', () => {
    renderStage({
      stage: makeStage({ reason: 'This matches the noise pattern' }),
      index: 0,
      isLast: false,
    })
    expect(screen.getByText('This matches the noise pattern')).toBeInTheDocument()
  })

  it('shows weak indicator when stage is weak', () => {
    renderStage({
      stage: makeStage({ weak: true }),
      index: 0,
      isLast: false,
    })
    expect(screen.getByText(/weak · below threshold/)).toBeInTheDocument()
  })
})
