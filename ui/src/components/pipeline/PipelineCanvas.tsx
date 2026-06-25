// PipelineCanvas — lane bands + an SVG edge layer + HTML StageNode cards.
//
// Selection, hover-to-focus (dims off-path nodes/edges), and — when `editable` —
// node drag-to-pin (with lane snapping), output-port drag-to-connect (DAG-safe,
// with a live ghost wire), a selected-node toolbar (configure / pin / delete),
// and pan + zoom. Geometry (lanes, width, height) comes from the auto-layout
// pass so the board resizes as stages are added/removed.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Maximize2, Pin, PinOff, Settings2, Trash2, ZoomIn, ZoomOut } from 'lucide-react'
import { NODE_META } from '@/lib/pipeline/schema'
import { laneKeyForType } from '@/lib/pipeline/layout'
import type { LaneBand, PipelineEdge, PipelineGraph, PipelineNode } from '@/lib/types/pipeline'
import {
  CANVAS_H,
  CANVAS_W,
  NODE_W,
  edgeMid,
  edgePath,
  inPort,
  outPort,
  type EdgeVariant,
} from './geometry'
import { LaneBands } from './LaneBands'
import { StageNode } from './StageNode'
import { EdgePredicateBadge } from './EdgePredicateBadge'

type Adjacency = { out: Record<number, number[]>; inc: Record<number, number[]> }

function buildAdjacency(graph: PipelineGraph): Adjacency {
  const out: Record<number, number[]> = {}
  const inc: Record<number, number[]> = {}
  graph.nodes.forEach((n) => {
    out[n.id] = []
    inc[n.id] = []
  })
  graph.edges.forEach((e) => {
    ;(out[e.from_node] = out[e.from_node] || []).push(e.to_node)
    ;(inc[e.to_node] = inc[e.to_node] || []).push(e.from_node)
  })
  return { out, inc }
}

/** all nodes connected to `start` in either direction (for hover-to-focus). */
function closure(adj: Adjacency, start: number): Set<number> {
  const seen = new Set<number>([start])
  const walk = (map: Record<number, number[]>, id: number) => {
    ;(map[id] || []).forEach((nx) => {
      if (!seen.has(nx)) {
        seen.add(nx)
        walk(map, nx)
      }
    })
  }
  walk(adj.out, start)
  walk(adj.inc, start)
  return seen
}

/** forward-reachable set from `start` (for cycle-safe connect checks). */
function descendants(adjOut: Record<number, number[]>, start: number): Set<number> {
  const seen = new Set<number>()
  const stack = (adjOut[start] || []).slice()
  while (stack.length) {
    const x = stack.pop() as number
    if (!seen.has(x)) {
      seen.add(x)
      ;(adjOut[x] || []).forEach((y) => stack.push(y))
    }
  }
  return seen
}

export interface PipelineCanvasProps {
  graph: PipelineGraph
  variant?: EdgeVariant
  selectedId?: number | null
  selectedEdgeId?: number | null
  onSelect?: (id: number | null) => void
  onSelectEdge?: (id: number | null) => void
  onConfig?: (node: PipelineNode) => void
  onToggle?: (id: number, enabled: boolean) => void
  interactive?: boolean
  editable?: boolean
  errorNodes?: Set<number>
  errorEdges?: Set<number>
  lanes?: LaneBand[]
  canvasW?: number
  canvasH?: number
  onNodeMove?: (id: number, x: number, y: number) => void
  onPinToggle?: (id: number) => void
  onDelete?: (id: number) => void
  onConnect?: (from: number, to: number) => void
}

export function PipelineCanvas({
  graph,
  variant = 'schematic',
  selectedId,
  selectedEdgeId,
  onSelect,
  onSelectEdge,
  onConfig,
  onToggle,
  interactive = false,
  editable = false,
  errorNodes,
  errorEdges,
  lanes,
  canvasW,
  canvasH,
  onNodeMove,
  onPinToggle,
  onDelete,
  onConnect,
}: PipelineCanvasProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(800)
  const [hover, setHover] = useState<number | null>(null)
  const [hoverEdge, setHoverEdge] = useState<number | null>(null)
  const [pan, setPan] = useState({ x: 0, y: 0, z: 1 })
  const [drag, setDrag] = useState<{ id: number; x: number; y: number } | null>(null)
  const [wire, setWire] = useState<{ fromId: number; x: number; y: number } | null>(null)
  const hoverRef = useRef<number | null>(null)
  hoverRef.current = hover
  const errN = errorNodes || new Set<number>()
  const errE = errorEdges || new Set<number>()
  const CW = canvasW || CANVAS_W
  const CH = canvasH || CANVAS_H

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return undefined
    const ro = new ResizeObserver(() => setW(el.clientWidth))
    ro.observe(el)
    setW(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const fit = Math.min(1, w / CW)
  const scaleRef = useRef(fit)
  const scale = fit * (interactive ? pan.z : 1)
  scaleRef.current = scale
  const boardH = CH * fit * (interactive ? pan.z : 1)

  // live positions (drag overrides the dragged node only)
  const nodeById: Record<number, PipelineNode> = {}
  graph.nodes.forEach((n) => {
    nodeById[n.id] = drag && drag.id === n.id ? { ...n, ui_x: drag.x, ui_y: drag.y } : n
  })
  const positioned = graph.nodes.map((n) => nodeById[n.id])

  const adj = useMemo(() => buildAdjacency(graph), [graph])

  // can a from→to edge be added? (DAG-safe, no dupes, respects port rules)
  const canConnect = useCallback(
    (from: number | null, to: number | null): boolean => {
      if (from == null || to == null || from === to) return false
      const fn = graph.nodes.find((n) => n.id === from)
      const tn = graph.nodes.find((n) => n.id === to)
      if (!fn || !tn) return false
      if (fn.type === 'sink') return false // sinks have no output
      if (tn.type === 'source') return false // sources have no input
      if (graph.edges.some((e) => e.from_node === from && e.to_node === to)) return false // dupe
      if (descendants(adj.out, to).has(from)) return false // would create a cycle
      return true
    },
    [graph, adj],
  )

  const focusSet = hover != null && !drag && !wire ? closure(adj, hover) : null
  const nodeDim = (id: number) => (focusSet ? !focusSet.has(id) : false)
  const edgeDim = (e: PipelineEdge) =>
    focusSet ? !(focusSet.has(e.from_node) && focusSet.has(e.to_node)) : false

  // ---- background pan ----
  const panState = useRef<{ x: number; y: number; px: number; py: number } | null>(null)
  const onBgDown = (e: React.MouseEvent) => {
    if (!interactive) return
    const t = e.target as HTMLElement
    if (t.closest('[data-node]') || t.closest('[data-edgebadge]') || t.closest('[data-nodebar]')) return
    panState.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y }
  }

  // ---- node drag ----
  const dragRef = useRef<{ id: number; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null)
  const onNodeMouseDown = (e: React.MouseEvent, node: PipelineNode) => {
    if (!editable) return
    e.stopPropagation()
    dragRef.current = { id: node.id, sx: e.clientX, sy: e.clientY, ox: node.ui_x, oy: node.ui_y, moved: false }
  }

  // ---- edge draw (wire) ----
  const wireRef = useRef<{ fromId: number } | null>(null)
  const toCanvas = (clientX: number, clientY: number) => {
    const r = wrapRef.current!.getBoundingClientRect()
    const px = interactive ? pan.x : 0
    const py = interactive ? pan.y : 0
    return { x: (clientX - r.left - px) / scaleRef.current, y: (clientY - r.top - py) / scaleRef.current }
  }
  const onPortDown = (e: React.MouseEvent, node: PipelineNode) => {
    e.stopPropagation()
    e.preventDefault()
    wireRef.current = { fromId: node.id }
    const p = outPort(node)
    setWire({ fromId: node.id, x: p.x, y: p.y })
  }

  // snap a dragged node so it stays inside its phase lane (narrow lanes center it)
  const clampToLane = (node: PipelineNode, x: number, y: number) => {
    const ny = Math.max(8, Math.min(CH - 72, y))
    const lane = (lanes || []).find((l) => l.key === laneKeyForType(node.type))
    if (!lane) return { x: Math.round(x), y: Math.round(ny) }
    const pad = 18
    const minX = lane.x + pad
    const maxX = lane.x + lane.w - NODE_W - pad
    const nx = maxX - minX < 40 ? lane.x + (lane.w - NODE_W) / 2 : Math.max(minX, Math.min(maxX, x))
    return { x: Math.round(nx), y: Math.round(ny) }
  }

  useEffect(() => {
    if (!interactive) return undefined
    const move = (e: MouseEvent) => {
      if (wireRef.current) {
        const c = toCanvas(e.clientX, e.clientY)
        setWire({ fromId: wireRef.current.fromId, x: c.x, y: c.y })
        return
      }
      if (dragRef.current) {
        const dr = dragRef.current
        const dx = (e.clientX - dr.sx) / scaleRef.current
        const dy = (e.clientY - dr.sy) / scaleRef.current
        if (Math.abs(e.clientX - dr.sx) + Math.abs(e.clientY - dr.sy) > 3) dr.moved = true
        const node = graph.nodes.find((n) => n.id === dr.id)
        if (!node) return
        const sn = clampToLane(node, dr.ox + dx, dr.oy + dy)
        setDrag({ id: dr.id, x: sn.x, y: sn.y })
        return
      }
      if (panState.current) {
        const p = panState.current
        setPan((pp) => ({ ...pp, x: p.px + (e.clientX - p.x), y: p.py + (e.clientY - p.y) }))
      }
    }
    const up = () => {
      if (wireRef.current) {
        const from = wireRef.current.fromId
        const to = hoverRef.current
        wireRef.current = null
        setWire(null)
        if (canConnect(from, to)) onConnect?.(from, to as number)
      }
      if (dragRef.current) {
        const dr = dragRef.current
        dragRef.current = null
        setDrag((d) => {
          if (d && dr.moved) onNodeMove?.(dr.id, d.x, d.y)
          return null
        })
      }
      panState.current = null
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactive, onNodeMove, onConnect, canConnect, pan, lanes, CH, graph])

  const selNode = editable && selectedId != null ? nodeById[selectedId] : null
  const selReserved = selNode ? NODE_META[selNode.type].reserved : false

  return (
    <div
      ref={wrapRef}
      onMouseDown={onBgDown}
      onClick={() => {
        onSelect?.(null)
        onSelectEdge?.(null)
      }}
      style={{
        position: 'relative',
        width: '100%',
        height: boardH,
        overflow: 'hidden',
        borderRadius: 'var(--radius-card)',
        border: '1px solid var(--border)',
        background: 'var(--surface-lowest)',
        cursor: panState.current ? 'grabbing' : 'default',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: interactive ? pan.y : 0,
          left: interactive ? pan.x : 0,
          transform: `scale(${scale})`,
          transformOrigin: 'top left',
          width: CW,
          height: CH,
        }}
      >
        <LaneBands lanes={lanes || []} height={CH} />

        {/* edge layer */}
        <svg
          width={CW}
          height={CH}
          style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'visible' }}
        >
          <defs>
            <marker id="pipe-arrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
              <path d="M1,1 L7,4.5 L1,8" fill="none" stroke="var(--muted-foreground)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </marker>
            <marker id="pipe-arrow-on" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
              <path d="M1,1 L7,4.5 L1,8" fill="none" stroke="var(--primary)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </marker>
          </defs>
          {graph.edges.map((e) => {
            const a = outPort(nodeById[e.from_node])
            const b = inPort(nodeById[e.to_node])
            const d = edgePath(a, b, variant)
            const on = (focusSet && !edgeDim(e)) || selectedEdgeId === e.id || hoverEdge === e.id
            const dim = edgeDim(e)
            const isAlways = !e.predicate || ('op' in e.predicate && e.predicate.op === 'always')
            const err = errE.has(e.id)
            const stroke = err
              ? 'var(--destructive)'
              : on
                ? 'var(--primary)'
                : 'color-mix(in srgb, var(--muted-foreground) 55%, transparent)'
            return (
              <g key={e.id} style={{ opacity: dim ? 0.18 : 1, transition: 'opacity .14s ease' }}>
                <path
                  d={d}
                  stroke="transparent"
                  strokeWidth="16"
                  fill="none"
                  style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
                  onMouseEnter={() => setHoverEdge(e.id)}
                  onMouseLeave={() => setHoverEdge((h) => (h === e.id ? null : h))}
                  onClick={(ev) => {
                    ev.stopPropagation()
                    onSelectEdge?.(e.id)
                  }}
                />
                <path
                  d={d}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={on ? 2 : 1.5}
                  strokeDasharray={variant === 'flow' && !isAlways ? '5 6' : 'none'}
                  markerEnd={`url(#${on ? 'pipe-arrow-on' : 'pipe-arrow'})`}
                />
              </g>
            )
          })}
          {/* live wire being drawn */}
          {wire &&
            (() => {
              const fromN = nodeById[wire.fromId]
              if (!fromN) return null
              const a = outPort(fromN)
              const valid = canConnect(wire.fromId, hover)
              const col = hover != null ? (valid ? 'var(--primary)' : 'var(--destructive)') : 'var(--brand)'
              return (
                <path
                  d={edgePath(a, { x: wire.x, y: wire.y }, variant)}
                  fill="none"
                  stroke={col}
                  strokeWidth="2"
                  strokeDasharray="4 5"
                  markerEnd="url(#pipe-arrow-on)"
                  style={{ pointerEvents: 'none' }}
                />
              )
            })()}
        </svg>

        {/* predicate badges — hidden by default; shown on edge-hover, node-focus, selection */}
        {graph.edges.map((e) => {
          const a = outPort(nodeById[e.from_node])
          const b = inPort(nodeById[e.to_node])
          const m = edgeMid(a, b)
          const show = selectedEdgeId === e.id || hoverEdge === e.id || (focusSet && !edgeDim(e))
          return (
            <div
              key={`b${e.id}`}
              onMouseEnter={() => setHoverEdge(e.id)}
              onMouseLeave={() => setHoverEdge((h) => (h === e.id ? null : h))}
              style={{
                position: 'absolute',
                left: m.x,
                top: m.y,
                transform: 'translate(-50%,-50%)',
                opacity: show ? 1 : 0,
                pointerEvents: show ? 'auto' : 'none',
                zIndex: show ? 12 : 1,
                transition: 'opacity .12s ease',
              }}
            >
              <EdgePredicateBadge edge={e} selected={selectedEdgeId === e.id} onClick={() => onSelectEdge?.(e.id)} />
            </div>
          )
        })}

        {/* nodes */}
        {positioned.map((n) => {
          const wireTarget = wire && hover === n.id
          const validTarget = !!wireTarget && canConnect(wire!.fromId, n.id)
          const invalidTarget = !!wireTarget && !canConnect(wire!.fromId, n.id) && wire!.fromId !== n.id
          return (
            <div
              data-node
              key={n.id}
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover((h) => (h === n.id ? null : h))}
            >
              <StageNode
                node={n}
                selected={selectedId === n.id}
                dimmed={nodeDim(n.id)}
                error={errN.has(n.id) || invalidTarget}
                dropValid={validTarget}
                onSelect={onSelect}
                onToggle={onToggle}
                onConfig={onConfig}
                draggable={editable && !wire}
                onNodeMouseDown={onNodeMouseDown}
                dragging={!!drag && drag.id === n.id}
                animate={!drag}
              />
            </div>
          )
        })}

        {/* output ports (editable) — drag from here to wire a new edge */}
        {editable &&
          positioned.map((n) => {
            if (n.type === 'sink') return null
            const p = outPort(n)
            const active = wire && wire.fromId === n.id
            const show = hover === n.id || selectedId === n.id || active
            return (
              <div
                key={`port${n.id}`}
                title="Drag to connect"
                onMouseDown={(e) => onPortDown(e, n)}
                onMouseEnter={() => setHover(n.id)}
                style={{
                  position: 'absolute',
                  left: p.x,
                  top: p.y,
                  width: 16,
                  height: 16,
                  transform: 'translate(-50%,-50%)',
                  borderRadius: 9999,
                  cursor: 'crosshair',
                  zIndex: drag ? 1 : 25,
                  background: active ? 'var(--primary)' : 'var(--card)',
                  border: `2px solid ${active ? 'var(--primary)' : 'var(--brand)'}`,
                  boxShadow: '0 1px 4px rgba(0,0,0,.5)',
                  opacity: show ? 1 : 0,
                  pointerEvents: show ? 'auto' : 'none',
                  transition: 'opacity .12s ease',
                }}
              />
            )
          })}

        {/* selected-node toolbar */}
        {selNode && !drag && !wire && (
          <div
            data-nodebar
            style={{
              position: 'absolute',
              left: selNode.ui_x + NODE_W - 4,
              top: selNode.ui_y - 12,
              transform: 'translateX(-100%)',
              display: 'flex',
              gap: 3,
              padding: 3,
              borderRadius: 6,
              background: 'var(--popover)',
              border: '1px solid var(--border)',
              boxShadow: '0 6px 18px rgba(0,0,0,.45)',
              zIndex: 30,
            }}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
          >
            {!selReserved && (
              <button className="wb-iconbtn" title="Configure" onClick={() => onConfig?.(selNode)} style={{ width: 24, height: 24 }}>
                <Settings2 size={13} />
              </button>
            )}
            {!selReserved && (
              <button
                className="wb-iconbtn"
                title={selNode.pinned ? 'Unpin (auto-place)' : 'Pin position'}
                onClick={() => onPinToggle?.(selNode.id)}
                style={{ width: 24, height: 24, color: selNode.pinned ? 'var(--brand)' : 'var(--muted-foreground)' }}
              >
                {selNode.pinned ? <PinOff size={13} /> : <Pin size={13} />}
              </button>
            )}
            {!selReserved && (
              <button className="wb-iconbtn" title="Delete stage" onClick={() => onDelete?.(selNode.id)} style={{ width: 24, height: 24, color: 'var(--error-text)' }}>
                <Trash2 size={13} />
              </button>
            )}
            {selReserved && (
              <span className="font-mono text-muted-foreground" style={{ fontSize: 10, padding: '4px 8px' }}>
                locked
              </span>
            )}
          </div>
        )}
      </div>

      {interactive && (
        <div style={{ position: 'absolute', right: 10, bottom: 10, display: 'flex', gap: 4 }}>
          <button
            className="wb-iconbtn"
            onClick={(e) => {
              e.stopPropagation()
              setPan((p) => ({ ...p, z: Math.max(0.5, p.z - 0.15) }))
            }}
            style={{ width: 28, height: 28, background: 'var(--card)', border: '1px solid var(--border)' }}
            aria-label="Zoom out"
            title="Zoom out"
          >
            <ZoomOut size={14} />
          </button>
          <button
            className="wb-iconbtn"
            onClick={(e) => {
              e.stopPropagation()
              setPan({ x: 0, y: 0, z: 1 })
            }}
            style={{ width: 28, height: 28, background: 'var(--card)', border: '1px solid var(--border)' }}
            aria-label="Reset zoom"
            title="Reset zoom"
          >
            <Maximize2 size={14} />
          </button>
          <button
            className="wb-iconbtn"
            onClick={(e) => {
              e.stopPropagation()
              setPan((p) => ({ ...p, z: Math.min(2, p.z + 0.15) }))
            }}
            style={{ width: 28, height: 28, background: 'var(--card)', border: '1px solid var(--border)' }}
            aria-label="Zoom in"
            title="Zoom in"
          >
            <ZoomIn size={14} />
          </button>
        </div>
      )}
    </div>
  )
}
