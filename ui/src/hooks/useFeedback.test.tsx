import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { _resetToken } from '@/lib/api'
import { useApplyTuningTask } from './useFeedback'
import { FUNNEL_KEYS } from './useFunnel'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen()); afterEach(() => { server.resetHandlers(); _resetToken() }); afterAll(() => server.close())
const wrap = ({ children }: { children: ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useApplyTuningTask', () => {
  it('patches the filter-rule prompt then marks the task applied', async () => {
    const calls: string[] = []
    server.use(
      http.patch('/api/filter-rules/5/prompt', async ({ request }) => {
        calls.push('prompt:' + (await request.json() as { prompt: string }).prompt)
        return HttpResponse.json({ status: 'ok' })
      }),
      http.patch('/api/feedback/tasks/9', ({ request }) => {
        calls.push('status:' + new URL(request.url).searchParams.get('status'))
        return HttpResponse.json({ id: 9, status: 'applied' })
      }),
    )
    const { result } = renderHook(() => useApplyTuningTask(), { wrapper: wrap })
    await result.current.mutateAsync({ taskId: 9, ruleId: 5, prompt: 'new prompt' })
    await waitFor(() => expect(calls).toEqual(['prompt:new prompt', 'status:applied']))
  })

  it('invalidates the correct funnel filter-rules query key on success', async () => {
    server.use(
      http.patch('/api/filter-rules/5/prompt', () => HttpResponse.json({ status: 'ok' })),
      http.patch('/api/feedback/tasks/9', () => HttpResponse.json({ id: 9, status: 'applied' })),
      http.get('/api/funnel/filter-rules', () => HttpResponse.json([]))
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    // Seed the filter-rules cache with stale data
    qc.setQueryData(FUNNEL_KEYS.filterRules, [{ id: 5, prompt: 'old prompt' }])
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')

    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useApplyTuningTask(), { wrapper })
    await result.current.mutateAsync({ taskId: 9, ruleId: 5, prompt: 'new prompt' })

    // Assert that the correct filter-rules query key was invalidated
    await waitFor(() => {
      const calls = invalidateSpy.mock.calls
      const filterRulesInvalidation = calls.find(
        ([options]) => JSON.stringify(options.queryKey) === JSON.stringify(FUNNEL_KEYS.filterRules)
      )
      expect(filterRulesInvalidation).toBeTruthy()
    })
  })
})
