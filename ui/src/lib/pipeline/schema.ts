// schema.ts — static metadata for the pipeline editor: node/sink presentation,
// the field schema that drives the rule builder, operator sets, and the provider
// registry. Pure data + small lookups, no React.

import type { FieldSpec, FieldType, NodeType, PipelineNode, ProviderSpec, SinkRole } from '../types/pipeline'

/** Brand tokens used as node accent colors (resolve to CSS vars where possible). */
export const PIPE_TONE = {
  drop: 'var(--destructive)',
  include: 'var(--success)',
  triage: 'var(--primary)',
  llm: 'var(--tertiary)',
  enrich: '#b79cf7',
  filter: 'var(--brand)',
  neutral: 'var(--muted-foreground)',
} as const

export interface NodeMeta {
  label: string
  icon: string
  tone: string
  reserved: boolean
  lane: number
}

/** type → presentation. `reserved` nodes are locked (always-on, no delete/move). */
export const NODE_META: Record<NodeType, NodeMeta> = {
  source: { label: 'Source', icon: 'Inbox', tone: PIPE_TONE.neutral, reserved: true, lane: 0 },
  pre_filter: { label: 'Pre-filter', icon: 'Filter', tone: PIPE_TONE.filter, reserved: false, lane: 1 },
  extraction: { label: 'Extraction', icon: 'ScanLine', tone: PIPE_TONE.triage, reserved: true, lane: 2 },
  rule_filter: { label: 'Rule filter', icon: 'SlidersHorizontal', tone: PIPE_TONE.filter, reserved: false, lane: 3 },
  llm_filter: { label: 'LLM filter', icon: 'Sparkles', tone: PIPE_TONE.llm, reserved: false, lane: 3 },
  enricher: { label: 'Enricher', icon: 'Wand2', tone: PIPE_TONE.enrich, reserved: false, lane: 3 },
  sink: { label: 'Sink', icon: 'Flag', tone: PIPE_TONE.neutral, reserved: true, lane: 4 },
  loopback: { label: 'Loopback', icon: 'RotateCcw', tone: PIPE_TONE.neutral, reserved: false, lane: 3 },
}

export const SINK_META: Record<SinkRole, { label: string; icon: string; tone: string }> = {
  drop: { label: 'Drop', icon: 'Ban', tone: PIPE_TONE.drop },
  auto_include: { label: 'Auto-include', icon: 'CircleCheckBig', tone: PIPE_TONE.include },
  triage: { label: 'Triage', icon: 'ListChecks', tone: PIPE_TONE.triage },
}

/** Resolve a node's effective presentation (sinks merge role-specific meta). */
export function nodeMeta(n: PipelineNode): { label: string; icon: string; tone: string } {
  if (n.type === 'sink' && n.role) return { ...NODE_META.sink, ...SINK_META[n.role] }
  return NODE_META[n.type]
}

export const OPERATORS: Record<FieldType, string[]> = {
  enum: ['eq', 'neq', 'in', 'not_in', 'exists'],
  string: ['eq', 'neq', 'in', 'not_in', 'contains', 'matches', 'exists'],
  int: ['eq', 'gt', 'gte', 'lt', 'lte'],
  float: ['eq', 'gt', 'gte', 'lt', 'lte'],
  bool: ['is_true', 'is_false'],
  datetime: ['before', 'after', 'within_hours'],
  list: ['contains', 'len_gt'],
}

export const OP_LABEL: Record<string, string> = {
  eq: 'is', neq: 'is not', in: 'is one of', not_in: 'is not one of',
  contains: 'contains', matches: 'matches', exists: 'is set',
  gt: '>', gte: '≥', lt: '<', lte: '≤', is_true: 'is true', is_false: 'is false',
  before: 'before', after: 'after', within_hours: 'within hours', len_gt: 'count >',
}

export const FIELD_SCHEMA: FieldSpec[] = [
  // Universal (segment: both → available pre + post extraction)
  { key: 'type', label: 'type', type: 'enum', operators: OPERATORS.enum, enum_values: ['diff', 'task', 'email', 'chat', 'calendar'], segment: 'both', description: 'Item kind' },
  { key: 'source_type', label: 'source', type: 'enum', operators: OPERATORS.enum, enum_values: ['github', 'phabricator', 'email', 'chat', 'calendar'], segment: 'both' },
  { key: 'author', label: 'author', type: 'string', operators: OPERATORS.string, segment: 'both' },
  { key: 'created_at', label: 'created', type: 'datetime', operators: OPERATORS.datetime, segment: 'both' },
  // Pre-extraction only (cheap, pre-LLM)
  { key: 'title', label: 'title', type: 'string', operators: OPERATORS.string, segment: 'pre' },
  { key: 'is_draft', label: 'is draft', type: 'bool', operators: OPERATORS.bool, segment: 'pre' },
  { key: 'labels', label: 'labels', type: 'list', operators: OPERATORS.list, segment: 'pre' },
  // Post-extraction (derived by the model)
  { key: 'relevance', label: 'relevance', type: 'int', operators: OPERATORS.int, segment: 'post', description: 'Model relevance 0–100' },
  { key: 'priority', label: 'priority', type: 'enum', operators: OPERATORS.enum, enum_values: ['P0', 'P1', 'P2', 'P3'], segment: 'post' },
  { key: 'status', label: 'status', type: 'enum', operators: OPERATORS.enum, enum_values: ['draft', 'open', 'merged', 'closed'], segment: 'post' },
  { key: 'files', label: 'files changed', type: 'int', operators: OPERATORS.int, segment: 'post' },
  { key: 'category', label: 'category', type: 'enum', operators: OPERATORS.enum, enum_values: ['action_item', 'meeting', 'plan_seed', 'informational'], segment: 'post' },
]

export function field(key: string): FieldSpec | undefined {
  return FIELD_SCHEMA.find((f) => f.key === key)
}

export function allowedFields(segment: 'pre' | 'post' | 'both'): FieldSpec[] {
  return FIELD_SCHEMA.filter((f) => (segment === 'both' ? true : f.segment === segment || f.segment === 'both'))
}

export const PROVIDERS: ProviderSpec[] = [
  { id: 'github_meta', label: 'GitHub metadata', adds: ['reviewers', 'ci_status', 'files'] },
  { id: 'diff_meta', label: 'Diff context', adds: ['diff_stat', 'risk', 'owners'] },
  { id: 'thread', label: 'Thread resolver', adds: ['participants', 'last_reply'] },
  { id: 'calendar', label: 'Calendar links', adds: ['attendees', 'conflicts'] },
]

/** per-node funnel stats keyed by PipelineNode.stat (replace with live data). */
export const NODE_STATS: Record<string, { entered: number; dropped: number; passed: number }> = {
  src: { entered: 1357, dropped: 0, passed: 1357 },
  pre: { entered: 1357, dropped: 214, passed: 1143 },
  ext: { entered: 1143, dropped: 12, passed: 1131 },
  llm: { entered: 1131, dropped: 0, passed: 1131 },
  rf_diff: { entered: 612, dropped: 188, passed: 424 },
  rf_task: { entered: 240, dropped: 73, passed: 167 },
  enr: { entered: 410, dropped: 0, passed: 410 },
  enr_diff: { entered: 424, dropped: 0, passed: 424 },
  enr_task: { entered: 167, dropped: 0, passed: 167 },
}
