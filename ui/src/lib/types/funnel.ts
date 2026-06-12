export type FilterAction = 'drop' | 'include' | 'label' | 'context' | 'loopback'

export type StageOutcome = FilterAction | 'pass' | 'skip'

export type FilterOrigin = 'learned' | 'explicit'

export interface FilterRuleExtended {
  id: string
  prompt: string
  action: FilterAction
  sources: string[]
  confidence: number | null
  origin: FilterOrigin
  matched: number
  enabled: boolean
  label?: string
  order_index: number
  tuned?: boolean
}

export interface Enricher {
  id: string
  type: string
  label: string
  depth: 'shallow' | 'deep'
  enabled: boolean
  adds: string[]
  records: string[]
  budget: { max_calls: number; max_time_ms: number }
  avg_ms: number
  enriched: number
}

export interface LoopBack {
  id: string
  label: string
  trigger: string
  condition: string
  max_loops: number
  enabled: boolean
  looped: number
  avg_loops: number
}

export interface FunnelStage {
  filterId: string
  outcome: StageOutcome
  reason?: string
  confidence?: number
  label?: string
  context?: string
  weak?: boolean
}

export interface Verdict {
  decision: 'triaged' | 'dropped' | 'queued'
  priority?: string
  confidence?: number
  rationale: string
}

export interface FunnelItem {
  id: string
  summary: string
  source: string
  created_at: string
  stages: FunnelStage[]
  verdict: Verdict
  loop_count?: number
}

export interface EnrichmentSample {
  id: string
  summary: string
  context: Record<string, string | number | boolean>
  entities?: string[]
}

export type FunnelOrderEntryKind = 'enricher' | 'filter' | 'loopback'

export interface FunnelOrderEntry {
  kind: FunnelOrderEntryKind
  id: string
}
