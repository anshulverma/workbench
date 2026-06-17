// Items hook — backs the Overview HOT FEED (spec §8).
//
// GET /api/items returns entity rows filtered by the optional priority/status/
// source_type query params. The HOT FEED wants the high-priority pending queue
// (P0|P1 & pending_triage); since the backend filter takes a single priority,
// we fetch the pending_triage queue once and keep P0/P1 client-side (one query,
// no over-fetch of triaged items). Sorted by priority then newest-first.

import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'

export interface Item {
  id: number
  source_type: string
  source_id: string
  summary: string
  category: string
  origin: string
  priority: string
  status: string
  created_at: string
  updated_at: string
}

export function useItems(params: { status?: string; priority?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.priority) qs.set('priority', params.priority)
  const query = qs.toString()
  return useQuery({
    queryKey: ['items', { status: params.status ?? null, priority: params.priority ?? null }],
    queryFn: () => apiGet<Item[]>(`/api/items${query ? `?${query}` : ''}`),
    refetchInterval: pollWhenVisible(15_000),
  })
}

const HOT_PRIORITY_ORDER: Record<string, number> = { P0: 0, P1: 1 }

/**
 * useHotFeed — the high-priority pending queue for the Overview HOT FEED.
 * Fetches `status=pending_triage`, keeps only P0/P1, and orders P0 before P1,
 * then newest-first. Returns the wrapped query plus the derived `items`.
 */
export function useHotFeed(limit = 6) {
  const query = useItems({ status: 'pending_triage' })
  const items = (query.data ?? [])
    .filter((it) => it.priority === 'P0' || it.priority === 'P1')
    .sort((a, b) => {
      const pa = HOT_PRIORITY_ORDER[a.priority] ?? 99
      const pb = HOT_PRIORITY_ORDER[b.priority] ?? 99
      if (pa !== pb) return pa - pb
      return (b.created_at ?? '').localeCompare(a.created_at ?? '')
    })
    .slice(0, limit)
  return { ...query, items }
}
