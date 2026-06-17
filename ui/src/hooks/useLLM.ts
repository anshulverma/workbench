// Query hooks for the LLM Infra tab (System Status page).
//
// The list endpoint returns summaries only (no prompt/completion bodies); the
// detail endpoint is fetched lazily when a row is clicked. Transport is
// TanStack polling via `pollWhenVisible` (ADR0060 — polling, not SSE).

import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'
import type { LLMCall, LLMCallDetailData } from '@/pages/SystemStatus'

export interface LLMMetrics {
  calls_24h: number
  avg_latency_ms: number | null
  error_rate: number
  batched_pct: number
  window_hours: number
  as_of: string
}

export function useLLMCalls(
  params: { limit?: number; stage?: string; status?: string } = {},
) {
  const qs = new URLSearchParams()
  qs.set('limit', String(params.limit ?? 50))
  if (params.stage) qs.set('stage', params.stage)
  if (params.status) qs.set('status', params.status)
  return useQuery({
    queryKey: ['llm', 'calls', params],
    queryFn: () => apiGet<LLMCall[]>(`/api/llm/calls?${qs}`),
    refetchInterval: pollWhenVisible(5_000),
  })
}

export function useLLMCallDetail(id: string | null) {
  return useQuery({
    queryKey: ['llm', 'call', id],
    queryFn: () => apiGet<LLMCallDetailData>(`/api/llm/calls/${id}`),
    enabled: id != null,
  })
}

export function useLLMMetrics() {
  return useQuery({
    queryKey: ['llm', 'metrics'],
    queryFn: () => apiGet<LLMMetrics>('/api/llm/metrics'),
    refetchInterval: pollWhenVisible(15_000),
  })
}
