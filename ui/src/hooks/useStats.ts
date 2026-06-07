// Query hooks for the Overview page (spec Design Section 2.1).
//
// Each hook wraps a single read endpoint with a TanStack Query. Live views
// poll via `refetchInterval`; polling pauses on a hidden tab through the shared
// `pollWhenVisible` helper (which reads document.visibilityState).

import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'

export interface ItemsBreakdown {
  by_status: Record<string, number>
  by_priority: Record<string, number>
  by_category: Record<string, number>
  by_source: Record<string, number>
  total: number
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
  id: string
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

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => apiGet<HealthResponse>('/health'),
    refetchInterval: pollWhenVisible(15_000),
  })
}

export function useJobs(limit = 10) {
  return useQuery({
    queryKey: ['jobs', { limit, offset: 0 }],
    queryFn: () => apiGet<JobsResponse>(`/api/jobs?limit=${limit}`),
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
