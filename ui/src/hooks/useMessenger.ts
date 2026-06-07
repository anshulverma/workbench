// Query + mutation hooks for the Messenger page (spec Design Section 2.6).
//
// Reads: GET /api/messenger?check=true returns the messenger envelope plus a
// best-effort reachability probe. The allowlisted `config` only ever carries
// non-secret fields (space_id, timeout_seconds); service_account_key_path is
// never present. usePendingCount reads GET /api/triage/pending for the
// no-messenger "queued but unsent" count. useUpdateMessenger PATCHes the
// non-secret config, invalidates ['messenger'], and toasts on success/error.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, apiGet, apiPatch } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'

export interface MessengerInfo {
  configured: boolean
  type: string | null
  class: string | null
  config: { space_id?: string; timeout_seconds?: number }
  reachable?: boolean | null
  checked_at?: string
  note?: string
}

// Editable, non-secret messenger config. Secrets are never typed or sent.
export interface MessengerUpdate {
  space_id?: string
  timeout_seconds?: number
}

// Reachability is checked on read; ?check=true adds {reachable, checked_at}.
export function useMessenger() {
  return useQuery({
    queryKey: ['messenger'],
    queryFn: () => apiGet<MessengerInfo>('/api/messenger?check=true'),
    refetchInterval: pollWhenVisible(60_000),
  })
}

// Only fetched in the no-messenger state so the user sees what is queued but
// unsent. The endpoint returns the list of pending triage cards.
export function usePendingCount(enabled: boolean) {
  return useQuery({
    queryKey: ['triage', 'pending'],
    queryFn: () => apiGet<unknown[]>('/api/triage/pending'),
    enabled,
    refetchInterval: pollWhenVisible(30_000),
  })
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.requestId ? `${err.message} (req ${err.requestId})` : err.message
  }
  return err instanceof Error ? err.message : 'Unknown error'
}

// Pessimistic PATCH: await the server, invalidate ['messenger'] so the read view
// refetches the hot-swapped provider. The caller may inspect the rejected
// ApiError to map 422 field errors; we still surface a fallback error toast.
export function useUpdateMessenger() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: MessengerUpdate) =>
      apiPatch<{ status: string }>('/api/messenger', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['messenger'] })
      toast.success('Messenger updated')
    },
    onError: (err) => toast.error(`Update failed: ${errMessage(err)}`),
  })
}
