// Query + mutation hooks for the Knowledge page (spec Design Section 2.7).
//
// Reads: GET /api/memory/facts returns the envelope
// {available, memory_type, facts:[{id,content,source,timestamp}]} and is always
// 200. We capture the response X-Request-ID alongside the envelope so the
// "configured but unreachable" degraded state (available=false, memory_type!=noop)
// can surface the correlation id even though the request itself succeeded.
//
// Mutations: useDeleteFact + useUpdateFact (Fact Curation) call DELETE/PATCH and
// invalidate ['memory','facts'] on success. A 501 (NoopMemoryLayer) maps to a
// friendly "memory layer not configured" toast.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, apiDelete, apiPatch, apiPost } from '@/lib/api'

export interface Fact {
  id: string
  content: string
  source: string
  timestamp: string | null
}

export interface FactsEnvelope {
  available: boolean
  memory_type: string
  facts: Fact[]
}

// The envelope plus the read response's X-Request-ID, used by the unreachable
// degraded state. We do not route this through lib/api's `request` because that
// helper discards headers on the 2xx path.
export interface FactsResult extends FactsEnvelope {
  requestId: string | null
}

async function fetchFacts(): Promise<FactsResult> {
  // Re-use the token-vending flow by importing the same module memory used by
  // lib/api; the simplest path is to call apiGet-equivalent fetch ourselves.
  const tokenRes = await fetch('/api/auth/token')
  if (!tokenRes.ok) {
    throw new ApiError(
      'token unavailable',
      tokenRes.status,
      tokenRes.headers.get('X-Request-ID'),
    )
  }
  const { token } = (await tokenRes.json()) as { token: string }
  const res = await fetch('/api/memory/facts', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  const requestId = res.headers.get('X-Request-ID')
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ? JSON.stringify(body.detail) : detail
    } catch {
      /* non-json error body */
    }
    throw new ApiError(detail, res.status, requestId)
  }
  const env = (await res.json()) as FactsEnvelope
  return { ...env, requestId }
}

export const useFacts = () =>
  useQuery({
    queryKey: ['memory', 'facts'],
    queryFn: fetchFacts,
  })

export function factErrorMessage(err: unknown): string {
  return errMessage(err)
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 501) return 'memory layer not configured'
    return err.requestId ? `${err.message} (req ${err.requestId})` : err.message
  }
  return err instanceof Error ? err.message : 'Unknown error'
}

// Pessimistic delete: await the server, then invalidate the facts query so the
// list refetches. A 501 (Noop memory layer) surfaces the friendly toast.
export function useDeleteFact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/memory/facts/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memory', 'facts'] })
      toast.success('Fact deleted')
    },
    onError: (err) => toast.error(`Delete failed: ${errMessage(err)}`),
  })
}

export function useUpdateFact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      apiPatch(`/api/memory/facts/${id}`, { content }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memory', 'facts'] })
      toast.success('Fact updated')
    },
    onError: (err) => toast.error(`Update failed: ${errMessage(err)}`),
  })
}

// Manual fact create (ADR0045): POST /api/memory/facts {content} returns the
// created Fact (source "manual"). On success we refetch the facts query so the
// new row appears with its server-assigned id/timestamp. A 422 (blank content)
// surfaces inline at the call site (the dialog stays open); a 501 (Noop memory
// layer) maps to the friendly toast — though the Add Fact entry point is hidden
// whenever the memory layer is degraded, so 501 is a defensive fallback only.
export function useCreateFact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (content: string) =>
      apiPost<Fact>('/api/memory/facts', { content }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memory', 'facts'] })
      toast.success('Fact added')
    },
  })
}
