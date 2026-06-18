// Query hooks for the Overview page (spec Design Section 2.1).
//
// Each hook wraps a single read endpoint with a TanStack Query. Live views
// poll via `refetchInterval`; polling pauses on a hidden tab through the shared
// `pollWhenVisible` helper (which reads document.visibilityState).

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, apiDelete, apiGet, apiPost } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'

export interface ItemsBreakdown {
  by_status: Record<string, number>
  by_priority: Record<string, number>
  by_category: Record<string, number>
  by_source: Record<string, number>
  total: number
}

// Derived-metrics block (ADR0039/0040, spec §6). Any zero-denominator or
// degraded source is serialized as `null` and rendered "n/a" (never fabricated).
export interface OverviewMetrics {
  signal_velocity: number
  throughput: number
  efficiency_peak: number | null
  auto_resolved_pct: number | null
  avg_triage_seconds: number | null
  growth_velocity: number | null
  ingestion_success_rate: number | null
}

export interface StatsOverview {
  pending_triage: number
  in_flight: number
  dead_letters: number
  active_items: number
  sources_enabled: number
  sources_total: number
  items: ItemsBreakdown
  queue: { in_flight: number; dead_letters: number }
  metrics?: OverviewMetrics
}

// Generic derived timeseries point (GET /api/stats/timeseries). Zero-filled
// full bucket axis; `bucket` is an ISO timestamp.
export interface MetricPoint {
  bucket: string
  count: number
}

export interface IngestionPoint {
  date: string
  count: number
}

export interface HealthResponse {
  status: string
  version: string
  components: {
    storage: { status: string; error?: string }
    connections: Record<string, { status: string; error?: string }>
  }
  queue: {
    ingestion_depth?: number
    triage_pending?: number
    dead_letters?: number
  }
}

export interface Job {
  id: number
  trigger: string
  status: string
  items_extracted: number
  created_at: string
}

export interface JobsResponse {
  jobs: Job[]
  total: number
  limit: number
  offset: number
}

export interface MessengerInfo {
  configured: boolean
  type: string
  class: string | null
  config: Record<string, unknown>
}

export function useStatsOverview() {
  return useQuery({
    queryKey: ['stats', 'overview'],
    queryFn: () => apiGet<StatsOverview>('/api/stats/overview'),
    refetchInterval: pollWhenVisible(15_000),
  })
}

export function useIngestionTimeseries(days = 14, bucket = 'day') {
  return useQuery({
    queryKey: ['stats', 'ingestion-timeseries', { days, bucket }],
    queryFn: () =>
      apiGet<IngestionPoint[]>(
        `/api/stats/ingestion-timeseries?days=${days}&bucket=${bucket}`,
      ),
    refetchInterval: pollWhenVisible(60_000),
  })
}

// Generic derived metric timeseries (signal_velocity | throughput), used for
// the Overview Signal Velocity sparkline (spec §8). 422s on an unknown metric.
export function useMetricsTimeseries(metric: string, window = 24, bucket = 'hour') {
  return useQuery({
    queryKey: ['stats', 'timeseries', { metric, window, bucket }],
    queryFn: () =>
      apiGet<MetricPoint[]>(
        `/api/stats/timeseries?metric=${encodeURIComponent(metric)}&window=${window}&bucket=${bucket}`,
      ),
    refetchInterval: pollWhenVisible(60_000),
  })
}

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => apiGet<HealthResponse>('/health'),
    refetchInterval: pollWhenVisible(15_000),
  })
}

export function useJobs(limit = 10, offset = 0, status?: string) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (status) params.set('status', status)
  return useQuery({
    queryKey: ['jobs', { limit, offset, status: status ?? null }],
    queryFn: () => apiGet<JobsResponse>(`/api/jobs?${params.toString()}`),
    refetchInterval: pollWhenVisible(30_000),
  })
}

export function useMessenger() {
  return useQuery({
    queryKey: ['messenger'],
    queryFn: () => apiGet<MessengerInfo>('/api/messenger'),
    refetchInterval: pollWhenVisible(60_000),
  })
}

// --- Ingestion page hooks (spec Design Section 2.4) ---

// Per-source relevance/noise thresholds (ADR0044). Integers 0..100. `null` on
// a SourceRollup means "inherit the global defaults" (rendered as 70/30/30).
export interface SourceRelevance {
  auto_include_threshold: number
  triage_threshold: number
  drop_below: number
}

export interface SourceRollup {
  id: string
  adapter_type: string
  enabled: boolean
  schedule: string | null
  last_run: string | null
  items_stored: number
  raw_enqueued: number
  in_flight: number
  health_status: string
  config?: Record<string, unknown>
  relevance?: SourceRelevance | null
}

export interface ActivityItem {
  id: number
  status: string
  source_type: string
  summary: string | null
  created_at: string | null
  // Lineage path id. Not yet emitted by /api/activity (Task 14 deferred-gated);
  // present here so the LiveTail link lights up once the payload carries it.
  path?: string
}

export interface QueueStats {
  by_status: Record<string, number>
  by_source: Record<string, number>
  queued: number
  processing: number
  dead_letter: number
}

export interface DeadLetterEntry {
  id: number
  raw_content: string
  source_type: string
  source_id: string | null
  urgency_score: number
  job_id: number
  status: string
  attempt: number
  max_attempts: number
  error: string | null
  created_at: string
  updated_at: string
}

export function useSourcesRollup() {
  return useQuery({
    queryKey: ['stats', 'sources'],
    queryFn: () => apiGet<SourceRollup[]>('/api/stats/sources'),
    refetchInterval: pollWhenVisible(30_000),
  })
}

export function useActivity(limit = 50) {
  return useQuery({
    queryKey: ['activity', { limit }],
    queryFn: () => apiGet<ActivityItem[]>(`/api/activity?limit=${limit}`),
    refetchInterval: pollWhenVisible(15_000),
  })
}

export function useQueueStats() {
  return useQuery({
    queryKey: ['stats', 'queue'],
    queryFn: () => apiGet<QueueStats>('/api/stats/queue'),
    refetchInterval: pollWhenVisible(15_000),
  })
}

export function useDeadLetters() {
  return useQuery({
    queryKey: ['queue', 'dead-letter'],
    queryFn: () => apiGet<DeadLetterEntry[]>('/api/queue/dead-letter'),
    refetchInterval: pollWhenVisible(30_000),
  })
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.requestId ? `${err.message} (req ${err.requestId})` : err.message
  }
  return err instanceof Error ? err.message : 'Unknown error'
}

export function useRetryDeadLetter() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiPost<{ status: string }>(`/api/queue/dead-letter/${id}/retry`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['queue', 'dead-letter'] })
      qc.invalidateQueries({ queryKey: ['stats', 'queue'] })
      toast.success('Dead letter requeued')
    },
    onError: (err) => toast.error(`Retry failed: ${errMessage(err)}`),
  })
}

export function usePurgeDeadLetter() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiDelete<{ status: string }>(`/api/queue/dead-letter/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['queue', 'dead-letter'] })
      qc.invalidateQueries({ queryKey: ['stats', 'queue'] })
      toast.success('Dead letter purged')
    },
    onError: (err) => toast.error(`Purge failed: ${errMessage(err)}`),
  })
}
