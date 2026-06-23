// useFeedback.ts — React hooks for feedback corrections and filter tuning.
//
// TanStack Query hooks for server API endpoints (/api/feedback/*), used for
// durable persistence and cross-device sync.

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api'

// ---------------------------------------------------------------------------
// Server API types (matching the Python domain models)
// ---------------------------------------------------------------------------

export interface ServerCorrection {
  id: number
  item_id: number
  rule_id: number | null
  filter_id: string | null
  item_summary: string | null
  original_action: string
  corrected_action: string
  from_label: string | null
  to_label: string | null
  reason: string | null
  created_at: string
}

export interface ServerTuningTask {
  id: number
  rule_id: number | null
  filter_id: string | null
  item_id: number | null
  item_summary: string | null
  from_outcome: string | null
  to_outcome: string | null
  from_label: string | null
  to_label: string | null
  filter_prompt: string | null
  proposed_prompt: string
  kind: string | null
  correction_ids: number[]
  status: string
  created_at: string
  resolved_at: string | null
}

// ---------------------------------------------------------------------------
// TanStack Query hooks — server sync
// ---------------------------------------------------------------------------

/** Fetch corrections from the server, optionally filtered by item_id. */
export function useCorrections(itemId?: number) {
  const qs = itemId != null ? `?item_id=${encodeURIComponent(itemId)}` : ''
  return useQuery({
    queryKey: ['feedback', 'corrections', itemId ?? null],
    queryFn: () => apiGet<ServerCorrection[]>(`/api/feedback/corrections${qs}`),
  })
}

/** Fetch tuning tasks from the server, optionally filtered by status. */
export function useTuningTasks(status?: string) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return useQuery({
    queryKey: ['feedback', 'tasks', status ?? null],
    queryFn: () => apiGet<ServerTuningTask[]>(`/api/feedback/tasks${qs}`),
  })
}

/** Mutation: add a correction to the server. */
export function useAddCorrection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Omit<ServerCorrection, 'id' | 'created_at'>) =>
      apiPost<ServerCorrection>('/api/feedback/corrections', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feedback', 'corrections'] })
    },
  })
}

/** Mutation: delete a correction from the server. */
export function useDeleteCorrection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (correctionId: number) =>
      apiDelete<{ status: string }>(`/api/feedback/corrections/${correctionId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feedback', 'corrections'] })
    },
  })
}

/** Mutation: create a tuning task on the server. */
export function useCreateTuningTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Omit<ServerTuningTask, 'id' | 'created_at' | 'resolved_at'>) =>
      apiPost<ServerTuningTask>('/api/feedback/tasks', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feedback', 'tasks'] })
    },
  })
}

/** Mutation: update a tuning task's status on the server. */
export function useUpdateTuningTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, status }: { taskId: number; status: string }) =>
      apiPatch<ServerTuningTask>(`/api/feedback/tasks/${taskId}?status=${encodeURIComponent(status)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feedback', 'tasks'] })
    },
  })
}

/** Mutation: delete a tuning task from the server. */
export function useDeleteTuningTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (taskId: number) =>
      apiDelete<{ status: string }>(`/api/feedback/tasks/${taskId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feedback', 'tasks'] })
    },
  })
}

/** Apply a tuning task: write the proposed prompt to the filter rule, then mark applied. */
export function useApplyTuningTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ taskId, ruleId, prompt }: { taskId: number; ruleId: number; prompt: string }) => {
      await apiPatch(`/api/filter-rules/${ruleId}/prompt`, { prompt })
      return apiPatch<ServerTuningTask>(`/api/feedback/tasks/${taskId}?status=applied`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feedback', 'tasks'] })
      qc.invalidateQueries({ queryKey: ['filter-rules'] })
    },
  })
}
