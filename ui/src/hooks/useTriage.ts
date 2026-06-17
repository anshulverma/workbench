// Query + mutation hooks for the Triage page (spec Design Section 2.2).
//
// Reads: GET /api/triage/pending returns the list of pending TriageCards (each
// with id, card_content, options, relevance_score, status). The query polls
// while the tab is visible so newly-queued cards surface without a manual
// refresh.
//
// Mutations:
//   useRespond()  -> POST /api/triage/respond. Numbered ({card_id, choice}) or
//                    free-text ({card_id, raw_text}). A destructive free-text
//                    response returns {status:"awaiting_confirmation", ...}; the
//                    page then drives the confirmation round-trip. We only
//                    invalidate ['triage','pending'] when the card reached a
//                    terminal state (i.e. NOT awaiting_confirmation), so the card
//                    stays on screen while its confirm dialog is open.
//   useConfirm()  -> POST /api/triage/confirm. Completes/cancels a pending
//                    free-text confirmation, then invalidates the list.
//
// Both mutations surface sonner toasts and treat a 409 (the optimistic-
// concurrency guard: the card was already answered on the messenger or another
// tab) as a friendly "already answered" notice plus a refetch so the stale card
// drops off the list.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, apiGet, apiPost } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'

export interface TriageTheme {
  id: string
  label: string
  summary: string
  counts: Record<string, number>
  cards: number[]
}

export interface TriageOption {
  label: string
  action: string
  details?: Record<string, unknown>
  suggested?: boolean
  suggestion_reason?: string | null
}

export interface TriageCard {
  id: number
  item_id?: number | null
  card_content: {
    summary?: string
    source_type?: string
    priority?: string
    // Source identity for the source-type badge + "open in source" link.
    // source_ref is the human-readable id (e.g. "D123456", "T123", "#42");
    // source_url is the canonical external URL. Both server-populated, optional.
    source_ref?: string
    source_url?: string
    [k: string]: unknown
  }
  options: TriageOption[]
  relevance_score?: number
  confidence_score?: number
  status?: string
  // Row-birth timestamp (migration 007); powers the client Time-Window filter
  // (ADR0043). ISO-8601 string when serialized by /api/triage/pending.
  created_at?: string
}

// Server reply to POST /api/triage/respond. Numbered/non-destructive responses
// carry {status:"recorded"|"interpreted", ...}; a destructive free-text response
// carries {status:"awaiting_confirmation", explanation, card_id}.
export interface RespondResult {
  status: string
  action?: string
  explanation?: string
  card_id?: number
}

export const TRIAGE_PENDING_KEY = ['triage', 'pending'] as const

export function useTriagePending() {
  return useQuery({
    queryKey: TRIAGE_PENDING_KEY,
    queryFn: () => apiGet<TriageCard[]>('/api/triage/pending'),
    refetchInterval: pollWhenVisible(15_000),
  })
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.requestId ? `${err.message} (req ${err.requestId})` : err.message
  }
  return err instanceof Error ? err.message : 'Unknown error'
}

// A 409 means the card already reached a terminal state (answered on the
// messenger or in another tab). Surface a friendly toast and refetch so the
// stale card drops off the list. Returns true when it handled a 409.
function handleConflict(err: unknown, qc: ReturnType<typeof useQueryClient>): boolean {
  if (err instanceof ApiError && err.status === 409) {
    toast.info('That card was already answered elsewhere — refreshing.')
    qc.invalidateQueries({ queryKey: TRIAGE_PENDING_KEY })
    return true
  }
  return false
}

export interface RespondBody {
  card_id: number
  choice?: number
  raw_text?: string
}

export function useRespond() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RespondBody) =>
      apiPost<RespondResult>('/api/triage/respond', body),
    onSuccess: (data) => {
      // Keep the card on screen while a confirmation dialog is open; otherwise
      // it has reached a terminal state and can drop off the pending list.
      if (data.status !== 'awaiting_confirmation') {
        qc.invalidateQueries({ queryKey: TRIAGE_PENDING_KEY })
        toast.success('Response recorded')
      }
    },
    onError: (err) => {
      if (!handleConflict(err, qc)) {
        toast.error(`Response failed: ${errMessage(err)}`)
      }
    },
  })
}

export interface ConfirmBody {
  card_id: number
  confirm: boolean
}

export function useConfirm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ConfirmBody) =>
      apiPost<{ status: string }>('/api/triage/confirm', body),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: TRIAGE_PENDING_KEY })
      toast.success(vars.confirm ? 'Action confirmed' : 'Action cancelled')
    },
    onError: (err) => {
      if (!handleConflict(err, qc)) {
        toast.error(`Confirmation failed: ${errMessage(err)}`)
      }
    },
  })
}
