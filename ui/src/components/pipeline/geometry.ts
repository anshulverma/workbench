// geometry.ts — pure SVG/canvas geometry for the routing-DAG editor.
//
// Ported from the reference `PGeom`. Edges connect at a node's title row
// (ui_y + PORT_DY) for determinism. Two edge styles: 'schematic' (orthogonal,
// rounded corners) and 'flow' (curved bézier, matching the app's SourceFlow).

import type { PipelineNode } from '@/lib/types/pipeline'

/** Fallback canvas size when the auto-layout pass doesn't supply one. */
export const CANVAS_W = 1680
export const CANVAS_H = 540
export const NODE_W = 152
/** Edges connect at the title row, this far below the node top. */
export const PORT_DY = 30

export type EdgeVariant = 'schematic' | 'flow'

export interface Point {
  x: number
  y: number
}

export function outPort(n: PipelineNode): Point {
  return { x: n.ui_x + NODE_W, y: n.ui_y + PORT_DY }
}

export function inPort(n: PipelineNode): Point {
  return { x: n.ui_x, y: n.ui_y + PORT_DY }
}

export function edgeMid(a: Point, b: Point): Point {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
}

export function edgePath(a: Point, b: Point, variant: EdgeVariant): string {
  const x0 = a.x
  const y0 = a.y
  const x1 = b.x
  const y1 = b.y
  if (variant === 'schematic') {
    const midX = x0 + Math.max(28, (x1 - x0) / 2)
    const r = Math.min(12, Math.abs(y1 - y0) / 2, Math.abs(midX - x0))
    if (Math.abs(y1 - y0) < 1.5) return `M${x0},${y0} L${x1},${y1}`
    const dir = y1 > y0 ? 1 : -1
    return (
      `M${x0},${y0} L${midX - r},${y0} Q${midX},${y0} ${midX},${y0 + r * dir} ` +
      `L${midX},${y1 - r * dir} Q${midX},${y1} ${midX + r},${y1} L${x1},${y1}`
    )
  }
  const dx = Math.max(40, (x1 - x0) * 0.45)
  return `M${x0},${y0} C${x0 + dx},${y0} ${x1 - dx},${y1} ${x1},${y1}`
}
