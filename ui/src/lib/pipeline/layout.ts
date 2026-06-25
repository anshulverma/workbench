// layout.ts — lane-based layered auto-layout for the routing DAG.
//
// The lanes (Source → Pre-extraction → Extraction → Post-extraction → Sinks)
// define each node's COLUMN deterministically, so we only solve the tractable
// part: vertical ORDER within a column (barycenter crossing-minimization, seeded
// by current Y for stability) and Y placement (centered per column). Nodes with
// `pinned` keep their stored coordinates; auto-layout flows around them.
//
// Same layered approach a library like dagre implements, scoped to this app's
// fixed lane structure — which removes rank inference and keeps re-layout stable
// as stages are added/removed. Pure: returns new node objects, never mutates.

import type { LaneBand, LayoutResult, NodeType, PipelineGraph, PipelineNode } from '../types/pipeline'

const NODE_W = 152
const COL_PITCH = 200 // horizontal distance between column left edges
const ROW_PITCH = 128 // vertical distance between stacked node tops
const PAD_X = 28
const PAD_Y = 44
const MIN_H = 472
const POST: ReadonlySet<NodeType> = new Set<NodeType>(['rule_filter', 'llm_filter', 'enricher', 'loopback'])

/** longest-path depth of each post node, in post-nodes from extraction */
function postDepth(graph: PipelineGraph): Record<number, number> {
  const byId: Record<number, PipelineNode> = {}
  graph.nodes.forEach((n) => { byId[n.id] = n })
  const inc: Record<number, number[]> = {}
  graph.nodes.forEach((n) => { inc[n.id] = [] })
  graph.edges.forEach((e) => { if (inc[e.to_node]) inc[e.to_node].push(e.from_node) })
  const depth: Record<number, number> = {}
  const seen: Record<number, boolean> = {}
  function d(id: number): number {
    const n = byId[id]
    if (!n || !POST.has(n.type)) return -1 // non-post parent → child sits at 0
    if (depth[id] != null) return depth[id]
    if (seen[id]) return 0 // cycle guard
    seen[id] = true
    let best = 0
    ;(inc[id] || []).forEach((p) => { const pd = d(p); if (pd >= 0) best = Math.max(best, pd + 1) })
    depth[id] = best
    return best
  }
  graph.nodes.forEach((n) => { if (POST.has(n.type)) d(n.id) })
  return depth
}

function colIndex(node: PipelineNode, depth: Record<number, number>, postCols: number): number {
  switch (node.type) {
    case 'source': return 0
    case 'pre_filter': return 1
    case 'extraction': return 2
    case 'sink': return 3 + postCols
    default: return 3 + (depth[node.id] || 0)
  }
}

export function layout(graph: PipelineGraph): LayoutResult {
  const nodes = graph.nodes.map((n) => ({ ...n }))
  const depth = postDepth({ nodes, edges: graph.edges })
  const hasPost = nodes.some((n) => POST.has(n.type))
  let maxD = 0
  nodes.forEach((n) => { if (POST.has(n.type)) maxD = Math.max(maxD, depth[n.id] || 0) })
  const postCols = hasPost ? maxD + 1 : 1
  const totalCols = 4 + postCols // source, pre, extraction, [post…], sinks

  // bucket nodes into columns
  const cols: Record<number, PipelineNode[]> = {}
  nodes.forEach((n) => { const c = colIndex(n, depth, postCols); (cols[c] = cols[c] || []).push(n) })
  const colKeys = Object.keys(cols).map(Number).sort((a, b) => a - b)

  // adjacency for barycenter ordering
  const out: Record<number, number[]> = {}
  const inc: Record<number, number[]> = {}
  nodes.forEach((n) => { out[n.id] = []; inc[n.id] = [] })
  graph.edges.forEach((e) => { if (out[e.from_node]) out[e.from_node].push(e.to_node); if (inc[e.to_node]) inc[e.to_node].push(e.from_node) })

  // seed order within each column by current Y (stability across re-layouts)
  const order: Record<number, number> = {}
  colKeys.forEach((c) => { cols[c].sort((a, b) => (a.ui_y ?? 0) - (b.ui_y ?? 0)); cols[c].forEach((n, i) => { order[n.id] = i }) })

  const bary = (n: PipelineNode, adj: Record<number, number[]>) => {
    const nb = adj[n.id] || []
    if (!nb.length) return order[n.id]
    let s = 0, k = 0
    nb.forEach((m) => { if (order[m] != null) { s += order[m]; k++ } })
    return k ? s / k : order[n.id]
  }
  for (let it = 0; it < 8; it++) {
    const fwd = it % 2 === 0
    const keys = fwd ? colKeys : colKeys.slice().reverse()
    keys.forEach((c) => {
      const adj = fwd ? inc : out
      cols[c].sort((a, b) => bary(a, adj) - bary(b, adj))
      cols[c].forEach((n, i) => { order[n.id] = i })
    })
  }

  const maxRows = Math.max(1, ...colKeys.map((c) => cols[c].length))
  const height = Math.max(MIN_H, (maxRows - 1) * ROW_PITCH + PAD_Y * 2)
  const mid = height / 2

  colKeys.forEach((c) => {
    const arr = cols[c]
    const totalH = (arr.length - 1) * ROW_PITCH
    arr.forEach((n, i) => {
      if (n.pinned && n.ui_x != null && n.ui_y != null) return
      n.ui_x = PAD_X + c * COL_PITCH
      n.ui_y = Math.round(mid - totalH / 2 + i * ROW_PITCH)
    })
  })

  const width = PAD_X * 2 + (totalCols - 1) * COL_PITCH + NODE_W
  const band = (first: number, last: number, key: string, label: string): LaneBand => ({
    key, label,
    x: PAD_X + first * COL_PITCH - 16,
    w: (last - first) * COL_PITCH + NODE_W + 32,
  })
  const lanes: LaneBand[] = [
    band(0, 0, 'source', 'Source'),
    band(1, 1, 'pre', 'Pre-extraction'),
    band(2, 2, 'extract', 'Extraction'),
    band(3, 3 + postCols - 1, 'post', 'Post-extraction'),
    band(3 + postCols, 3 + postCols, 'sinks', 'Sinks'),
  ]

  return { nodes, edges: graph.edges, lanes, width, height }
}

export const LAYOUT_NODE_W = NODE_W
export const POST_TYPES = POST

/** which lane key a node type belongs to (used for drag snapping). */
export function laneKeyForType(type: NodeType): string {
  return type === 'source' ? 'source'
    : type === 'pre_filter' ? 'pre'
    : type === 'extraction' ? 'extract'
    : type === 'sink' ? 'sinks'
    : 'post'
}
