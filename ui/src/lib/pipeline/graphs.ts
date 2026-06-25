// graphs.ts — canonical mock graphs for the Pipeline editor. Replace with the
// real graph from your pipeline API; coordinates are recomputed by layout().

import type { ConditionTree, PipelineGraph } from '../types/pipeline'

// Default graph: Source → Extraction → LLM filter → {Auto-include, Drop,
// on-triage → Enricher(deep for diffs) → Triage}.
export const defaultGraph: PipelineGraph = {
  id: 'default',
  nodes: [
    { id: 1, type: 'source', label: 'All sources', source_scope: null, config: {}, enabled: true, ui_x: 84, ui_y: 250, stat: 'src' },
    { id: 2, type: 'extraction', label: 'Extraction', source_scope: null, config: {}, enabled: true, ui_x: 488, ui_y: 250, stat: 'ext' },
    { id: 3, type: 'llm_filter', label: 'Relevance filter', source_scope: ['all'], config: { include: 70, drop: 30, confidence: 70 }, enabled: true, ui_x: 760, ui_y: 250, stat: 'llm' },
    { id: 7, type: 'enricher', label: 'Enrich', source_scope: ['diff'], config: { provider: 'diff_meta', depth: 'deep' }, enabled: true, ui_x: 1010, ui_y: 392, stat: 'enr' },
    { id: 4, type: 'sink', role: 'auto_include', label: 'Auto-include', source_scope: null, config: {}, enabled: true, ui_x: 1410, ui_y: 96 },
    { id: 5, type: 'sink', role: 'drop', label: 'Drop', source_scope: null, config: {}, enabled: true, ui_x: 1410, ui_y: 250 },
    { id: 6, type: 'sink', role: 'triage', label: 'Triage', source_scope: null, config: {}, enabled: true, ui_x: 1410, ui_y: 404 },
  ],
  edges: [
    { id: 1, from_node: 1, to_node: 2, predicate: { op: 'always' }, order_index: 1 },
    { id: 2, from_node: 2, to_node: 3, predicate: { op: 'always' }, order_index: 1 },
    { id: 3, from_node: 3, to_node: 4, predicate: { field: 'relevance', operator: 'gte', value: 70 }, order_index: 1 },
    { id: 4, from_node: 3, to_node: 5, predicate: { field: 'relevance', operator: 'lt', value: 40 }, order_index: 2 },
    { id: 5, from_node: 3, to_node: 7, predicate: { op: 'always' }, order_index: 3 },
    { id: 6, from_node: 7, to_node: 6, predicate: { op: 'always' }, order_index: 1 },
  ],
}

// Edited variation: a pre-filter drops draft diffs; a diff branch
// (enrich → rule) and a task branch (rule) converge on one shared LLM filter,
// then re-diverge to type-specific enrichers before Triage. Demonstrates
// diverge → converge → re-diverge. Includes default fallback edges (14, 15) so
// every item has a path and the graph validates clean.
export const editedGraph: PipelineGraph = {
  id: 'edited',
  nodes: [
    { id: 1, type: 'source', label: 'All sources', source_scope: null, config: {}, enabled: true, ui_x: 80, ui_y: 250, stat: 'src' },
    { id: 8, type: 'pre_filter', label: 'Drop draft diffs', source_scope: ['diff'], config: {}, enabled: true, ui_x: 280, ui_y: 250, stat: 'pre' },
    { id: 2, type: 'extraction', label: 'Extraction', source_scope: null, config: {}, enabled: true, ui_x: 484, ui_y: 250, stat: 'ext' },
    { id: 9, type: 'enricher', label: 'Diff metadata', source_scope: ['diff'], config: { provider: 'diff_meta', depth: 'shallow' }, enabled: true, ui_x: 660, ui_y: 110 },
    { id: 10, type: 'rule_filter', label: 'Heavy diffs', source_scope: ['diff'], config: { action: 'drop' }, enabled: true, ui_x: 852, ui_y: 110, stat: 'rf_diff' },
    { id: 11, type: 'rule_filter', label: 'Low-priority tasks', source_scope: ['task'], config: { action: 'drop' }, enabled: true, ui_x: 660, ui_y: 392, stat: 'rf_task' },
    { id: 3, type: 'llm_filter', label: 'Relevance filter', source_scope: ['all'], config: { include: 70, drop: 30, confidence: 70 }, enabled: true, ui_x: 1056, ui_y: 250, stat: 'llm' },
    { id: 12, type: 'enricher', label: 'Diff enrich', source_scope: ['diff'], config: { provider: 'github_meta', depth: 'deep' }, enabled: true, ui_x: 1250, ui_y: 110, stat: 'enr_diff' },
    { id: 13, type: 'enricher', label: 'Task enrich', source_scope: ['task'], config: { provider: 'thread', depth: 'shallow' }, enabled: false, ui_x: 1250, ui_y: 392, stat: 'enr_task' },
    { id: 6, type: 'sink', role: 'triage', label: 'Triage', source_scope: null, config: {}, enabled: true, ui_x: 1480, ui_y: 250 },
    { id: 5, type: 'sink', role: 'drop', label: 'Drop', source_scope: null, config: {}, enabled: true, ui_x: 1480, ui_y: 430 },
    { id: 4, type: 'sink', role: 'auto_include', label: 'Auto-include', source_scope: null, config: {}, enabled: true, ui_x: 1480, ui_y: 72 },
  ],
  edges: [
    { id: 1, from_node: 1, to_node: 8, predicate: { op: 'always' }, order_index: 1 },
    { id: 2, from_node: 8, to_node: 2, predicate: { op: 'always' }, order_index: 1 },
    { id: 3, from_node: 2, to_node: 9, predicate: { field: 'type', operator: 'eq', value: 'diff' }, order_index: 1 },
    { id: 4, from_node: 2, to_node: 11, predicate: { field: 'type', operator: 'eq', value: 'task' }, order_index: 2 },
    { id: 5, from_node: 9, to_node: 10, predicate: { op: 'always' }, order_index: 1 },
    { id: 6, from_node: 10, to_node: 3, predicate: { op: 'always' }, order_index: 1 },
    { id: 7, from_node: 10, to_node: 5, predicate: { field: 'files', operator: 'gt', value: 50 }, order_index: 2 },
    { id: 8, from_node: 11, to_node: 3, predicate: { op: 'always' }, order_index: 1 },
    { id: 9, from_node: 3, to_node: 4, predicate: { field: 'relevance', operator: 'gte', value: 80 }, order_index: 1 },
    { id: 10, from_node: 3, to_node: 12, predicate: { field: 'type', operator: 'eq', value: 'diff' }, order_index: 2 },
    { id: 11, from_node: 3, to_node: 13, predicate: { field: 'type', operator: 'eq', value: 'task' }, order_index: 3 },
    { id: 12, from_node: 12, to_node: 6, predicate: { op: 'always' }, order_index: 1 },
    { id: 13, from_node: 13, to_node: 6, predicate: { op: 'always' }, order_index: 1 },
    { id: 14, from_node: 2, to_node: 3, predicate: { op: 'always' }, order_index: 3 }, // non-diff/task → relevance
    { id: 15, from_node: 3, to_node: 6, predicate: { op: 'always' }, order_index: 4 }, // uncertain / other → Triage
  ],
}

/** A nested AND/OR sample tree for the RuleBuilder demos. */
export const sampleTree: ConditionTree = {
  op: 'AND',
  children: [
    { field: 'author', operator: 'in', value: ['octocat', 'hubot'] },
    { field: 'files', operator: 'gt', value: 50 },
    { op: 'OR', children: [
      { field: 'status', operator: 'eq', value: 'draft' },
      { field: 'category', operator: 'eq', value: 'informational' },
    ] },
  ],
}
