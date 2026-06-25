// pipeline.ts — types for the Ingestion ▸ Pipeline routing-DAG editor.
// Mirrors the backend pipeline model; ui_x/ui_y are a cache of the auto-layout
// pass (see lib/pipeline/layout.ts), `pinned` flips a node to manual placement.

export type NodeType =
  | 'source'
  | 'extraction'
  | 'sink'
  | 'pre_filter'
  | 'rule_filter'
  | 'llm_filter'
  | 'enricher'
  | 'loopback'

export type SinkRole = 'drop' | 'auto_include' | 'triage'

export interface PipelineNode {
  id: number
  type: NodeType
  role?: SinkRole
  label: string
  source_scope: string[] | null
  config: Record<string, unknown>
  enabled: boolean
  ui_x: number
  ui_y: number
  pinned?: boolean
  /** key into the funnel-stats map, for the live entered/dropped/passed counts */
  stat?: string
}

/** A leaf condition: `field operator value` (value type depends on the field). */
export interface Condition {
  field: string
  operator: string
  value: unknown
}

/** A boolean group. NOT has exactly one child. */
export interface ConditionGroup {
  op: 'AND' | 'OR' | 'NOT'
  children: ConditionTree[]
}

export type ConditionTree = Condition | ConditionGroup

/** The default edge predicate — always matches (first-match-wins fallback). */
export interface AlwaysPredicate {
  op: 'always'
}

export type EdgePredicate = ConditionTree | AlwaysPredicate

export interface PipelineEdge {
  id: number
  from_node: number
  to_node: number
  predicate: EdgePredicate
  /** first-match-wins evaluation order among edges leaving the same node */
  order_index: number
}

export interface PipelineGraph {
  id?: string
  nodes: PipelineNode[]
  edges: PipelineEdge[]
}

export type FieldType =
  | 'enum'
  | 'string'
  | 'int'
  | 'float'
  | 'bool'
  | 'datetime'
  | 'list'

/** A field the rule builder can test, scoped to pre/post/both extraction. */
export interface FieldSpec {
  key: string
  label: string
  type: FieldType
  operators: string[]
  enum_values?: string[]
  segment: 'pre' | 'post' | 'both'
  description?: string
}

export interface NodeStats {
  node_id: number
  entered: number
  dropped: number
  passed: number
}

export interface ProviderSpec {
  id: string
  label: string
  adds: string[]
}

/** A single validation finding, with the nodes/edges it implicates. */
export interface PipelineProblem {
  id: string
  msg: string
  nodes: number[]
  edges: number[]
}

export interface ValidationResult {
  problems: PipelineProblem[]
  errorNodes: Set<number>
  errorEdges: Set<number>
  ok: boolean
}

/** Output of the auto-layout pass. */
export interface LaneBand {
  key: string
  label: string
  x: number
  w: number
}

export interface LayoutResult {
  nodes: PipelineNode[]
  edges: PipelineEdge[]
  lanes: LaneBand[]
  width: number
  height: number
}
