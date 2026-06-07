// Query hooks for the Settings page (spec Design Section 2.8).
//
// Read-only system info: app/config versions + component health come from the
// shared useHealth hook (GET /health), and the redacted config sections come
// from GET /api/debug/config (already secret-redacted server-side). retry:false
// so a 503 (storage down) surfaces immediately as the degraded state rather
// than retrying.

import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'

// Re-export the shared health hook so Settings reads the same cache entry as
// the Overview page; useHealth lives in useStats.ts.
export { useHealth } from '@/hooks/useStats'
export type { HealthResponse } from '@/hooks/useStats'

export interface DebugConfigResponse {
  config: Record<string, unknown>
}

export function useDebugConfig() {
  return useQuery({
    queryKey: ['debug-config'],
    queryFn: () => apiGet<DebugConfigResponse>('/api/debug/config'),
    retry: false,
  })
}
