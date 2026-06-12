// Funnel hooks — TanStack Query wrappers for the funnel API endpoints.
//
// Provides read hooks for filter rules, enrichers, loopbacks, funnel items,
// and individual item funnel detail, plus mutations for reordering and
// toggling funnel stages.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiGet, apiPatch, apiPost, ApiError } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'
import type {
  FilterRuleExtended,
  Enricher,
  LoopBack,
  FunnelItem,
  FunnelOrderEntry,
} from '@/lib/types/funnel'

// ---- Query keys ----

export const FUNNEL_KEYS = {
  filterRules: ['funnel', 'filter-rules'] as const,
  enrichers: ['funnel', 'enrichers'] as const,
  loopbacks: ['funnel', 'loopbacks'] as const,
  items: (params?: { source?: string; verdict?: string }) =>
    ['funnel', 'items', params ?? {}] as const,
  itemDetail: (id: string) => ['funnel', 'item', id] as const,
  order: ['funnel', 'order'] as const,
}

// ---- Read hooks ----

/** GET /api/funnel/filter-rules — all filter rules with match stats. */
export function useFilterRules() {
  return useQuery({
    queryKey: FUNNEL_KEYS.filterRules,
    queryFn: () => apiGet<FilterRuleExtended[]>('/api/funnel/filter-rules'),
    refetchInterval: pollWhenVisible(30_000),
  })
}

/** GET /api/funnel/enrichers — all enrichment stages. */
export function useEnrichers() {
  return useQuery({
    queryKey: FUNNEL_KEYS.enrichers,
    queryFn: () => apiGet<Enricher[]>('/api/funnel/enrichers'),
    refetchInterval: pollWhenVisible(30_000),
  })
}

/** GET /api/funnel/loopbacks — all loopback stages. */
export function useLoopbacks() {
  return useQuery({
    queryKey: FUNNEL_KEYS.loopbacks,
    queryFn: () => apiGet<LoopBack[]>('/api/funnel/loopbacks'),
    refetchInterval: pollWhenVisible(30_000),
  })
}

/** GET /api/funnel/items — recent items with optional source/verdict filter. */
export function useFunnelItems(params?: {
  source?: string
  verdict?: string
}) {
  const qs = new URLSearchParams()
  if (params?.source) qs.set('source', params.source)
  if (params?.verdict) qs.set('verdict', params.verdict)
  const query = qs.toString()
  return useQuery({
    queryKey: FUNNEL_KEYS.items(params),
    queryFn: () =>
      apiGet<FunnelItem[]>(`/api/funnel/items${query ? `?${query}` : ''}`),
    refetchInterval: pollWhenVisible(15_000),
  })
}

/** GET /api/funnel/items/:id — single item with full stage detail. */
export function useItemFunnel(id: string | null) {
  return useQuery({
    queryKey: FUNNEL_KEYS.itemDetail(id ?? ''),
    queryFn: () => apiGet<FunnelItem>(`/api/funnel/items/${id}`),
    enabled: !!id,
  })
}

/** GET /api/funnel/order — current funnel stage ordering. */
export function useFunnelOrder() {
  return useQuery({
    queryKey: FUNNEL_KEYS.order,
    queryFn: () => apiGet<FunnelOrderEntry[]>('/api/funnel/order'),
  })
}

// ---- Mutations ----

function errMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.requestId ? `${err.message} (req ${err.requestId})` : err.message
  }
  return err instanceof Error ? err.message : 'Unknown error'
}

/** PATCH /api/funnel/order — reorder funnel stages. */
export function useUpdateFunnelOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (order: FunnelOrderEntry[]) =>
      apiPatch<{ status: string }>('/api/funnel/order', { order }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: FUNNEL_KEYS.order })
      toast.success('Funnel order updated')
    },
    onError: (err) => {
      toast.error(`Failed to update funnel order: ${errMessage(err)}`)
    },
  })
}

/** POST /api/funnel/stages/:id/toggle — enable/disable a funnel stage. */
export function useToggleFunnelStage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      enabled,
    }: {
      id: string
      enabled: boolean
    }) =>
      apiPost<{ status: string }>(`/api/funnel/stages/${id}/toggle`, {
        enabled,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: FUNNEL_KEYS.filterRules })
      qc.invalidateQueries({ queryKey: FUNNEL_KEYS.enrichers })
      qc.invalidateQueries({ queryKey: FUNNEL_KEYS.loopbacks })
      toast.success('Stage toggled')
    },
    onError: (err) => {
      toast.error(`Failed to toggle stage: ${errMessage(err)}`)
    },
  })
}
