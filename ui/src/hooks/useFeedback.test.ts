// useFeedback.test.ts — TanStack Query hooks for /api/feedback/* endpoints.

import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement, type ReactNode } from 'react'
import {
  useCorrections,
  useTuningTasks,
  useAddCorrection,
  useDeleteCorrection,
  useUpdateTuningTask,
} from './useFeedback'
import { _resetToken } from '@/lib/api'

const CORRECTIONS = [
  {
    id: 1,
    item_id: 1,
    rule_id: 1,
    filter_id: 'r-1',
    item_summary: 'test item',
    original_action: 'drop',
    corrected_action: 'include',
    from_label: 'Drop',
    to_label: 'Include',
    reason: 'important diff',
    created_at: '2026-06-10T00:00:00Z',
  },
]

const TASKS = [
  {
    id: 1,
    rule_id: 1,
    filter_id: 'r-1',
    item_id: 1,
    item_summary: 'test item',
    from_outcome: 'drop',
    to_outcome: 'include',
    from_label: 'Drop',
    to_label: 'Include',
    filter_prompt: 'old prompt',
    proposed_prompt: 'updated prompt',
    kind: 'reclassify',
    correction_ids: [1],
    status: 'open',
    created_at: '2026-06-10T00:00:00Z',
    resolved_at: null,
  },
]

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-fb' })),
)

beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-fb' })),
  )
  _resetToken()
})
afterAll(() => server.close())

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return createElement(QueryClientProvider, { client }, children)
}

describe('useCorrections', () => {
  it('fetches corrections from the server', async () => {
    server.use(
      http.get('/api/feedback/corrections', () => HttpResponse.json(CORRECTIONS)),
    )
    const { result } = renderHook(() => useCorrections(), { wrapper })
    await waitFor(() => expect(result.current.data).toHaveLength(1))
    expect(result.current.data![0].id).toBe(1)
    expect(result.current.data![0].item_id).toBe(1)
  })

  it('passes item_id as query param when provided', async () => {
    let capturedUrl = ''
    server.use(
      http.get('/api/feedback/corrections', ({ request }) => {
        capturedUrl = request.url
        return HttpResponse.json([])
      }),
    )
    const { result } = renderHook(() => useCorrections(42), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(capturedUrl).toContain('item_id=42')
  })
})

describe('useTuningTasks', () => {
  it('fetches tuning tasks from the server', async () => {
    server.use(
      http.get('/api/feedback/tasks', () => HttpResponse.json(TASKS)),
    )
    const { result } = renderHook(() => useTuningTasks(), { wrapper })
    await waitFor(() => expect(result.current.data).toHaveLength(1))
    expect(result.current.data![0].status).toBe('open')
  })

  it('passes status as query param when provided', async () => {
    let capturedUrl = ''
    server.use(
      http.get('/api/feedback/tasks', ({ request }) => {
        capturedUrl = request.url
        return HttpResponse.json([])
      }),
    )
    const { result } = renderHook(() => useTuningTasks('open'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(capturedUrl).toContain('status=open')
  })
})

describe('useAddCorrection', () => {
  it('posts a correction and invalidates the corrections query', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      http.post('/api/feedback/corrections', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...posted, id: 999, created_at: '2026-06-10T12:00:00Z' })
      }),
    )

    const { result } = renderHook(() => useAddCorrection(), { wrapper })
    result.current.mutate({
      item_id: 5,
      rule_id: 1,
      filter_id: null,
      item_summary: null,
      original_action: 'drop',
      corrected_action: 'include',
      from_label: null,
      to_label: null,
      reason: 'test',
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(posted).toMatchObject({ item_id: 5, corrected_action: 'include' })
  })
})

describe('useDeleteCorrection', () => {
  it('sends a DELETE and completes', async () => {
    let deletedId = ''
    server.use(
      http.delete('/api/feedback/corrections/:id', ({ params }) => {
        deletedId = params.id as string
        return HttpResponse.json({ status: 'deleted' })
      }),
    )

    const { result } = renderHook(() => useDeleteCorrection(), { wrapper })
    result.current.mutate(1)
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(deletedId).toBe('1')
  })
})

describe('useUpdateTuningTask', () => {
  it('patches a task status', async () => {
    let patchedUrl = ''
    server.use(
      http.patch('/api/feedback/tasks/:id', ({ request }) => {
        patchedUrl = request.url
        return HttpResponse.json({ ...TASKS[0], status: 'applied' })
      }),
    )

    const { result } = renderHook(() => useUpdateTuningTask(), { wrapper })
    result.current.mutate({ taskId: 1, status: 'applied' })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(patchedUrl).toContain('status=applied')
  })
})
