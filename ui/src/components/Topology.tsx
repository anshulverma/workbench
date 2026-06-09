// Topology — a hand-rolled 2D SVG node-link graph (spec §7/§8, ADR0041).
//
// Renders the infrastructure graph returned by GET /api/topology as a hub-and-
// spoke SVG: the `app` node sits at the center, every other node is placed on a
// ring around it, and edges are drawn as lines. There is NO 3D / react-three-
// fiber / reactflow — just positioned <circle>/<line>/<text>.
//
// Accessibility: the <svg> carries role="img" + an aria-label summary, and a
// visually-hidden <table> mirrors every node + status so screen readers and
// tests get the full graph as structured data (the SVG itself is aria-hidden
// for AT, but kept role="img" per the spec's a11y contract).

import type { Topology, TopologyNode, TopologyStatus } from '@/hooks/useTopology'

// Status → fill/stroke, harmonized with the HealthBadge palette (spec 11.3).
const STATUS_FILL: Record<TopologyStatus, string> = {
  healthy: '#16a34a', // green-600
  degraded: '#f59e0b', // amber-500
  unhealthy: '#dc2626', // red-600
  unknown: '#6b7280', // gray-500
  not_configured: '#9ca3af', // gray-400
}

const WIDTH = 320
const HEIGHT = 220
const CENTER = { x: WIDTH / 2, y: HEIGHT / 2 }
const RING_RADIUS = 78
const NODE_RADIUS = 9
const HUB_RADIUS = 13

function layout(nodes: TopologyNode[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>()
  const hub = nodes.find((n) => n.kind === 'app') ?? nodes[0]
  const spokes = nodes.filter((n) => n.id !== hub?.id)
  if (hub) pos.set(hub.id, { ...CENTER })
  const n = spokes.length
  spokes.forEach((node, i) => {
    // Start at the top (-90°) and distribute evenly around the ring.
    const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / Math.max(n, 1)
    pos.set(node.id, {
      x: CENTER.x + RING_RADIUS * Math.cos(angle),
      y: CENTER.y + RING_RADIUS * Math.sin(angle),
    })
  })
  return pos
}

export function Topology({ data }: { data: Topology }) {
  const { nodes, edges } = data
  const pos = layout(nodes)
  const summary = `Infrastructure topology: ${nodes.length} nodes — ${nodes
    .map((n) => `${n.label} ${n.status}`)
    .join(', ')}`

  return (
    <div data-testid="topology-graph">
      <svg
        role="img"
        aria-label={summary}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full"
        preserveAspectRatio="xMidYMid meet"
      >
        {edges.map((e, i) => {
          const a = pos.get(e.from)
          const b = pos.get(e.to)
          if (!a || !b) return null
          return (
            <line
              key={`${e.from}-${e.to}-${i}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="#26262C"
              strokeWidth={1.5}
            />
          )
        })}
        {nodes.map((node) => {
          const p = pos.get(node.id)
          if (!p) return null
          const isHub = node.kind === 'app'
          const r = isHub ? HUB_RADIUS : NODE_RADIUS
          const fill = STATUS_FILL[node.status] ?? STATUS_FILL.unknown
          // Label offset: hub label below, ring labels nudge away from center.
          const labelY = p.y > CENTER.y ? p.y + r + 12 : p.y - r - 6
          return (
            <g key={node.id}>
              <circle
                cx={p.x}
                cy={p.y}
                r={r}
                fill={fill}
                stroke="#0e0e11"
                strokeWidth={2}
              />
              <text
                x={p.x}
                y={labelY}
                textAnchor="middle"
                fontSize={10}
                fontFamily="var(--font-mono)"
                fill="#e4e1e6"
              >
                {node.label}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Visually-hidden a11y / fallback table mirroring the graph. */}
      <table className="sr-only">
        <caption>Infrastructure topology</caption>
        <thead>
          <tr>
            <th>Component</th>
            <th>Kind</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((node) => (
            <tr key={node.id}>
              <td>{node.label}</td>
              <td>{node.kind}</td>
              <td>{node.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
