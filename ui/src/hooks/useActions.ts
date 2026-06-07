// Query + mutation hooks for the Action Items page (spec Design Section 2.3).
//
// Reads the grouped action list from GET /api/actions and exposes the three
// lifecycle mutations (mark-done, change-priority, snooze). All mutations
// invalidate the ['actions'] query so the table refreshes, and surface a sonner
// toast on success/failure. Preserves the /api/actions contract migrated from
// the legacy ActionList/ActionItem components.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, apiGet, apiPost } from '@/lib/api'

export interface Action {
  id: string
  summary: string
  priority: string
  parent_item: { id: string; summary: string } | null
  action_source: string
  action_category: string | null
  created_at: string
}

export interface ActionsResponse {
  categories: Record<string, Action[]>
  total: number
}

export function useActions(category?: string) {
  const query = category ? `?category=${encodeURIComponent(category)}` : ''
  return useQuery({
    queryKey: ['actions', { category: category ?? null }],
    queryFn: () => apiGet<ActionsResponse>(`/api/actions${query}`),
  })
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.requestId ? `${err.message} (req ${err.requestId})` : err.message
  }
  return err instanceof Error ? err.message : 'Unknown error'
}

export function useMarkDone() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiPost(`/api/actions/${id}/done`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['actions'] })
      toast.success('Marked done')
    },
    onError: (err) => toast.error(`Mark done failed: ${errMessage(err)}`),
  })
}

export function useChangePriority() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, priority }: { id: string; priority: string }) =>
      apiPost(`/api/actions/${id}/priority`, { priority }),
    onSuccess: (_data, { priority }) => {
      qc.invalidateQueries({ queryKey: ['actions'] })
      toast.success(`Priority set to ${priority}`)
    },
    onError: (err) => toast.error(`Priority change failed: ${errMessage(err)}`),
  })
}

export function useSnooze() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, hours }: { id: string; hours: number }) =>
      apiPost(`/api/actions/${id}/snooze`, { hours }),
    onSuccess: (_data, { hours }) => {
      qc.invalidateQueries({ queryKey: ['actions'] })
      toast.success(`Snoozed ${hours}h`)
    },
    onError: (err) => toast.error(`Snooze failed: ${errMessage(err)}`),
  })
}
