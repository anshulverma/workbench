// useSearchItems — hooks for searching items, performing item actions, and
// snoozing items. Used by the Filters page funnel output table and other pages
// that need item-level operations.

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiGet, apiPost, ApiError } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'
import type { FunnelItem } from '@/lib/types/funnel'

// ---- Query keys ----

export const SEARCH_ITEMS_KEYS = {
  items: (params?: { source?: string; verdict?: string; q?: string }) =>
    ['search-items', params ?? {}] as const,
}

// ---- Read hooks ----

/**
 * useSearchItems — search and filter items by source, verdict, or query string.
 * Returns FunnelItem[] enriched with stages and verdict for display in funnel
 * output tables and detail dialogs.
 */
export function useSearchItems(params?: {
  source?: string
  verdict?: string
  q?: string
}) {
  const qs = new URLSearchParams()
  if (params?.source) qs.set('source', params.source)
  if (params?.verdict) qs.set('verdict', params.verdict)
  if (params?.q) qs.set('q', params.q)
  const query = qs.toString()
  return useQuery({
    queryKey: SEARCH_ITEMS_KEYS.items(params),
    queryFn: () =>
      apiGet<FunnelItem[]>(`/api/funnel/items${query ? `?${query}` : ''}`),
    refetchInterval: pollWhenVisible(15_000),
  })
}

// ---- Mutations ----

function errMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.requestId ? `${err.message} (req ${err.requestId})` : err.message
  }
  return err instanceof Error ? err.message : 'Unknown error'
}

/**
 * useItemActions — mutation hooks for item-level actions (archive, boost, etc.).
 */
export function useItemActions() {
  const qc = useQueryClient()

  const archive = useMutation({
    mutationFn: (itemId: string) =>
      apiPost<{ status: string }>(`/api/items/${itemId}/archive`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['search-items'] })
      qc.invalidateQueries({ queryKey: ['funnel'] })
      toast.success('Item archived')
    },
    onError: (err) => {
      toast.error(`Failed to archive item: ${errMessage(err)}`)
    },
  })

  const boost = useMutation({
    mutationFn: (itemId: string) =>
      apiPost<{ status: string }>(`/api/items/${itemId}/boost`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['search-items'] })
      qc.invalidateQueries({ queryKey: ['funnel'] })
      toast.success('Item boosted')
    },
    onError: (err) => {
      toast.error(`Failed to boost item: ${errMessage(err)}`)
    },
  })

  return { archive, boost }
}

/**
 * useSnoozeItem — snooze an item for a given duration (in minutes).
 */
export function useSnoozeItem() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      itemId,
      durationMinutes,
    }: {
      itemId: string
      durationMinutes: number
    }) =>
      apiPost<{ status: string }>(`/api/items/${itemId}/snooze`, {
        duration_minutes: durationMinutes,
      }),
    onSuccess: (_, { durationMinutes }) => {
      qc.invalidateQueries({ queryKey: ['search-items'] })
      qc.invalidateQueries({ queryKey: ['funnel'] })
      const label =
        durationMinutes >= 60
          ? `${Math.round(durationMinutes / 60)}h`
          : `${durationMinutes}m`
      toast.success(`Item snoozed for ${label}`)
    },
    onError: (err) => {
      toast.error(`Failed to snooze item: ${errMessage(err)}`)
    },
  })
}
