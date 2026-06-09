// Query + mutation hooks for the Sources page (spec Design Section 2.5).
//
// Reads: per-source rollup (reused from useStats), adapter-type introspection,
// and the connections list. Mutations: pessimistic create/edit (await server,
// then invalidate), optimistic enable/disable + delete with rollback, and a
// manual poll. All mutations invalidate the sources query so the table refreshes.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from '@/lib/api'
import {
  useSourcesRollup,
  type SourceRelevance,
  type SourceRollup,
} from '@/hooks/useStats'

// Global relevance defaults (PipelineConfig). Shown as "inherited" placeholders
// in the Config Drawer when a source has no per-source `relevance` set.
export const RELEVANCE_DEFAULTS: SourceRelevance = {
  auto_include_threshold: 70,
  triage_threshold: 30,
  drop_below: 30,
}

// Per-adapter introspection from GET /api/sources/adapter-types. The backend
// returns the Pydantic `json_schema` (model_json_schema) per allowlisted type.
export interface AdapterType {
  adapter_type: string
  requires_connection: boolean
  json_schema: {
    type?: string
    properties?: Record<string, unknown>
    [k: string]: unknown
  }
}

export interface Connection {
  name: string
  healthy: boolean
}

export interface CreateSourceBody {
  adapter_type: string
  config: Record<string, unknown>
  schedule: string
  enabled: boolean
  connection?: string
}

export interface EditSourceBody {
  config: Record<string, unknown>
  schedule: string
  connection?: string
}

// Reuse the shared rollup query so create/edit/toggle/delete all invalidate the
// same cache entry the Sources table reads from.
export const useSourceStats = useSourcesRollup

export const useAdapterTypes = () =>
  useQuery({
    queryKey: ['adapter-types'],
    queryFn: () => apiGet<AdapterType[]>('/api/sources/adapter-types'),
  })

export const useConnections = () =>
  useQuery({
    queryKey: ['connections'],
    queryFn: () => apiGet<Connection[]>('/api/connections'),
  })

function errMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.requestId ? `${err.message} (req ${err.requestId})` : err.message
  }
  return err instanceof Error ? err.message : 'Unknown error'
}

// Pessimistic: await the server, then invalidate. The success toast is shown by
// the caller (SourceForm) so the wording can differ between create and edit.
export function useCreateSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateSourceBody) =>
      apiPost<{ id: string }>('/api/sources', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stats', 'sources'] })
      qc.invalidateQueries({ queryKey: ['stats', 'overview'] })
    },
  })
}

export function useEditSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: EditSourceBody }) =>
      apiPatch(`/api/sources/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stats', 'sources'] })
      qc.invalidateQueries({ queryKey: ['stats', 'overview'] })
    },
  })
}

// Optimistic enable/disable with rollback. The PATCH carries only `enabled`.
export function useToggleSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiPatch(`/api/sources/${id}`, { enabled }),
    onMutate: async ({ id, enabled }) => {
      await qc.cancelQueries({ queryKey: ['stats', 'sources'] })
      const prev = qc.getQueryData<SourceRollup[]>(['stats', 'sources'])
      qc.setQueryData<SourceRollup[]>(['stats', 'sources'], (old) =>
        (old ?? []).map((s) => (s.id === id ? { ...s, enabled } : s)),
      )
      return { prev }
    },
    onError: (err, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(['stats', 'sources'], ctx.prev)
      toast.error(`Toggle failed: ${errMessage(err)}`)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['stats', 'sources'] }),
  })
}

// Per-source relevance/noise thresholds (ADR0044). Pessimistic: await the
// server (so inline 422s surface in the drawer), then invalidate the rollup so
// the card reflects the hot-reloaded thresholds. The success/error toast is the
// caller's concern (it owns the inline 422 mapping).
export function useUpdateRelevance() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, relevance }: { id: string; relevance: SourceRelevance }) =>
      apiPatch(`/api/sources/${id}`, { relevance }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stats', 'sources'] })
    },
  })
}

export function usePollSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiPost(`/api/sources/${id}/poll`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['stats', 'sources'] }),
  })
}

// Optimistic delete: remove the row immediately, roll back if the server fails.
export function useDeleteSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/sources/${id}`),
    onMutate: async (id: string) => {
      await qc.cancelQueries({ queryKey: ['stats', 'sources'] })
      const prev = qc.getQueryData<SourceRollup[]>(['stats', 'sources'])
      qc.setQueryData<SourceRollup[]>(['stats', 'sources'], (old) =>
        (old ?? []).filter((s) => s.id !== id),
      )
      return { prev }
    },
    onError: (err, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(['stats', 'sources'], ctx.prev)
      toast.error(`Delete failed: ${errMessage(err)}`)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['stats', 'sources'] }),
  })
}
