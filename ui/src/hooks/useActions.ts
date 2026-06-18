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
  id: number
  summary: string
  priority: string
  path?: string
  parent_item: { id: number; summary: string } | null
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

export interface CreateActionBody {
  summary: string
  priority?: string
  action_category?: string | null
}

// Manual Action Item creation (FAB). Hits POST /api/actions (B3), invalidates
// ['actions'] so the grouped sections refetch, and toasts on success. 422 (blank
// summary) is surfaced to the caller via onError so the form can render it
// inline; we intentionally do NOT toast a 422 (it is a field-level message).
export function useCreateAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateActionBody) =>
      apiPost<Action>('/api/actions', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['actions'] })
      toast.success('Action created')
    },
  })
}

export function useMarkDone() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiPost(`/api/actions/${id}/done`),
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
    mutationFn: ({ id, priority }: { id: number; priority: string }) =>
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
    mutationFn: ({ id, hours }: { id: number; hours: number }) =>
      apiPost(`/api/actions/${id}/snooze`, { hours }),
    onSuccess: (_data, { hours }) => {
      qc.invalidateQueries({ queryKey: ['actions'] })
      toast.success(`Snoozed ${hours}h`)
    },
    onError: (err) => toast.error(`Snooze failed: ${errMessage(err)}`),
  })
}
