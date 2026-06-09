// Topology hook (spec §7/§8, ADR0041).
//
// GET /api/topology returns a small node-link graph composed from the live
// component health probes (app, storage, memory_service, connections, source
// adapters, messenger). The endpoint never 5xxes for an absent/unreachable
// component (ADR0016) — missing pieces are `not_configured`, probe failures
// `unknown`. Polled every 15s and rendered by <Topology/> as a 2D SVG with a
// visually-hidden a11y table fallback.

import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'

export type TopologyKind =
  | 'app'
  | 'storage'
  | 'memory_service'
  | 'connection'
  | 'adapter'
  | 'messenger'

export type TopologyStatus =
  | 'healthy'
  | 'degraded'
  | 'unhealthy'
  | 'unknown'
  | 'not_configured'

export interface TopologyNode {
  id: string
  label: string
  kind: TopologyKind
  status: TopologyStatus
}

export interface TopologyEdge {
  from: string
  to: string
  kind: string
}

export interface Topology {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

export function useTopology() {
  return useQuery({
    queryKey: ['topology'],
    queryFn: () => apiGet<Topology>('/api/topology'),
    refetchInterval: pollWhenVisible(15_000),
  })
}
