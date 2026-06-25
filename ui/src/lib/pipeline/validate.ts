// validate.ts — live validation of the routing DAG. Pure: given a graph, returns
// problems plus the offending node/edge id sets so the toolbar pill, the
// problems popover, and the red node/edge rings always reflect the real graph.
//
// Checks:
//   1. unreachable   — a node with no path from the Source
//   2. dead-end      — a non-sink node with no outgoing edge (items get stuck)
//   3. no-fallback   — a node that branches on conditions but has no `always`
//                      edge, so an item matching none is silently lost
//   4. field-segment — a predicate evaluated BEFORE extraction that references a
//                      field only produced BY extraction (e.g. relevance)
//   5. cycle         — a loop back onto an ancestor (DAG violation)

import type { PipelineGraph, PipelineNode, ValidationResult } from '../types/pipeline'
import { field } from './schema'
import { collectFields } from './predicate'

export function validate(graph: PipelineGraph): ValidationResult {
  const problems: ValidationResult['problems'] = []
  const errorNodes = new Set<number>()
  const errorEdges = new Set<number>()
  const { nodes, edges } = graph
  const byId: Record<number, PipelineNode> = {}
  nodes.forEach((n) => { byId[n.id] = n })
  const out: Record<number, typeof edges> = {}
  const inc: Record<number, typeof edges> = {}
  nodes.forEach((n) => { out[n.id] = []; inc[n.id] = [] })
  edges.forEach((e) => { if (out[e.from_node]) out[e.from_node].push(e); if (inc[e.to_node]) inc[e.to_node].push(e) })

  const sources = nodes.filter((n) => n.type === 'source')

  // 1. reachability from source (forward BFS over out-edges)
  const reach = new Set<number>()
  const q = sources.map((s) => s.id)
  sources.forEach((s) => reach.add(s.id))
  while (q.length) {
    const id = q.shift() as number
    ;(out[id] || []).forEach((e) => { if (!reach.has(e.to_node)) { reach.add(e.to_node); q.push(e.to_node) } })
  }
  nodes.forEach((n) => {
    if (n.type === 'source') return
    if (!reach.has(n.id)) {
      errorNodes.add(n.id)
      problems.push({ id: `unreach-${n.id}`, msg: `“${n.label}” is unreachable — no route leads to it from the source.`, nodes: [n.id], edges: [] })
    }
  })

  // 2. dead-ends: non-sink node with no outgoing edge
  nodes.forEach((n) => {
    if (n.type === 'sink') return
    if ((out[n.id] || []).length === 0) {
      errorNodes.add(n.id)
      problems.push({ id: `dead-${n.id}`, msg: `“${n.label}” has no outgoing route — items reaching it are stuck.`, nodes: [n.id], edges: [] })
    }
  })

  // 3. branching nodes need an `always` fallback
  nodes.forEach((n) => {
    const oe = out[n.id] || []
    if (oe.length < 2) return // a single edge always receives the item
    const hasAlways = oe.some((e) => !e.predicate || ('op' in e.predicate && e.predicate.op === 'always'))
    if (!hasAlways) {
      errorNodes.add(n.id)
      oe.forEach((e) => errorEdges.add(e.id))
      problems.push({ id: `nofall-${n.id}`, msg: `“${n.label}” branches on conditions with no default (always) route — items matching none are dropped.`, nodes: [n.id], edges: oe.map((e) => e.id) })
    }
  })

  // 4. field/segment: pre-extraction predicate using a post-only field
  const preContext = (fromNode?: PipelineNode) => !!fromNode && (fromNode.type === 'source' || fromNode.type === 'pre_filter')
  edges.forEach((e) => {
    const from = byId[e.from_node]
    if (!preContext(from)) return
    const fields = collectFields(e.predicate)
    const bad = fields.filter((k) => { const f = field(k); return f && f.segment === 'post' })
    if (bad.length) {
      errorEdges.add(e.id)
      problems.push({ id: `seg-${e.id}`, msg: `Edge E${e.id} runs before extraction but tests ${bad.map((b) => `“${b}”`).join(', ')}, which only exists after extraction.`, nodes: [], edges: [e.id] })
    }
  })
  nodes.filter((n) => n.type === 'pre_filter').forEach((n) => {
    const tree = (n.config && (n.config as { tree?: unknown }).tree) as never
    const fields = collectFields(tree)
    const bad = fields.filter((k) => { const f = field(k); return f && f.segment === 'post' })
    if (bad.length) {
      errorNodes.add(n.id)
      problems.push({ id: `segn-${n.id}`, msg: `Pre-filter “${n.label}” tests ${bad.map((b) => `“${b}”`).join(', ')}, a post-extraction field — unavailable here.`, nodes: [n.id], edges: [] })
    }
  })

  // 5. cycle detection (DFS)
  const WHITE = 0, GRAY = 1, BLACK = 2
  const color: Record<number, number> = {}
  nodes.forEach((n) => { color[n.id] = WHITE })
  let cyclic = false
  const dfs = (id: number) => {
    color[id] = GRAY
    ;(out[id] || []).forEach((e) => {
      if (color[e.to_node] === GRAY) { cyclic = true; errorEdges.add(e.id) }
      else if (color[e.to_node] === WHITE) dfs(e.to_node)
    })
    color[id] = BLACK
  }
  nodes.forEach((n) => { if (color[n.id] === WHITE) dfs(n.id) })
  if (cyclic) problems.push({ id: 'cycle', msg: 'The graph contains a cycle — items could loop forever.', nodes: [], edges: [] })

  return { problems, errorNodes, errorEdges, ok: problems.length === 0 }
}
