// SourceFlow — animated SVG Sankey: source adapters -> WorkBench -> output buckets.
//
// Dot density per source is proportional to that source's ingest volume.
// Hovering a source (or output) isolates its ribbons + dots so the user can
// read the cross-breakdown. Pure SVG + rAF; no chart lib.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react'
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Calendar,
  CircleCheckBig,
  Filter,
  Github,
  ListChecks,
  Mail,
  MessageCircle,
  TriangleAlert,
  GitPullRequestArrow,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { FlowMatrix } from '@/lib/funnel-helpers'
import { SOURCE_COLORS, OUTPUT_COLORS } from '@/lib/funnel-constants'

// ---- Constants ----

const W = 760
const H = 210 // 70% of the original 300 — shorter Signal Flow on the Overview
const TOP = 26
const BOT = 26
const NODE_W = 12
const GAP = 16
const xL = 150
const BAR_X = 350
const BAR_W = 64
const xR = 600
const BAR_RX = BAR_X + BAR_W
const BAR_H = H - TOP - BOT
const POOL = 80
const TRAVERSAL_BASE = 0.34
const TRAVERSAL_RANGE = 0.28
const SPAWN_RATE = 0.022

const SRC_ICONS: Record<string, LucideIcon> = {
  github: Github,
  email: Mail,
  calendar: Calendar,
  chat: MessageCircle,
  phabricator: GitPullRequestArrow,
}

const OUTPUT_ICONS: Record<string, LucideIcon> = {
  action_items: CircleCheckBig,
  triage_queue: ListChecks,
  filtered_out: Filter,
  errors: TriangleAlert,
}

const OUTPUT_ROUTES: Record<string, string> = {
  action_items: '/actions',
  triage_queue: '/triage',
  filtered_out: '/ingestion',
  errors: '/ingestion',
}

// Default colors when a source/output is not in the canonical palette.
const DEFAULT_SRC_COLOR = '#71717a'
const DEFAULT_OUTPUT_COLOR = '#71717a'

// ---- Types ----

interface SourceFlowProps {
  /** Data matrix from buildFlowMatrix(). When undefined, loading skeleton. */
  data?: FlowMatrix
  /** Set of source adapter_type strings with health_status = 'erroring'. */
  stalledSources?: Set<string>
  /** Ingestion rate (items/hour) displayed in the central module. */
  ingestRate?: number
  /** Egress rate (items/hour) displayed in the central module. */
  egressRate?: number
  /** Error message — renders destructive error card. */
  error?: string
  /** Navigate callback for output-node clicks. */
  onNavigate?: (to: string) => void
}

type FocusState =
  | { t: 'none'; i: -1; j: -1 }
  | { t: 'src'; i: number; j: -1 }
  | { t: 'out'; i: -1; j: number }

interface NodeLayout {
  y: number
  h: number
  v: number
}

interface RibbonLayout {
  side: 'L' | 'R'
  idx: number
  color: string
  value: number
  on: boolean
  broken: boolean
  band: string
  mid: string
}

// ---- Helpers ----

function ribbonPath(
  x0: number,
  x1: number,
  aT: number,
  aB: number,
  bT: number,
  bB: number,
) {
  const cx = (x0 + x1) / 2
  const band = `M${x0},${aT} C${cx},${aT} ${cx},${bT} ${x1},${bT} L${x1},${bB} C${cx},${bB} ${cx},${aB} ${x0},${aB} Z`
  const aC = (aT + aB) / 2
  const bC = (bT + bB) / 2
  const mid = `M${x0},${aC} C${cx},${aC} ${cx},${bC} ${x1},${bC}`
  return { band, mid }
}

function layNodes(vals: number[], scale: number): NodeLayout[] {
  const MINPITCH = 36
  const hs = vals.map((v) => Math.max(3, v * scale))
  const gaps = hs.map((h) => Math.max(GAP, MINPITCH - h))
  const totalH =
    hs.reduce((a, b) => a + b, 0) +
    gaps.slice(0, -1).reduce((a, b) => a + b, 0)
  let y = TOP + Math.max(0, (BAR_H - totalH) / 2)
  return vals.map((v, k) => {
    const o = { y, h: hs[k], v }
    y += hs[k] + gaps[k]
    return o
  })
}

function perDay(vol: number): number {
  return Math.max(1, Math.round(vol / 14))
}

// ---- Layout computation ----

function computeLayout(
  data: FlowMatrix,
  broken: Set<string>,
  focus: FocusState,
) {
  const { sources, outputs, matrix } = data
  const total = sources.reduce((a, s) => a + s.vol, 0)
  const numNodes = Math.max(sources.length, outputs.length)
  const scale = total > 0 ? (BAR_H - (numNodes - 1) * GAP) / total : 1

  const focusBroken =
    focus.t === 'src' && broken.has(sources[focus.i]?.id ?? '')

  const leftNodeVals = sources.map((s, i) =>
    focus.t === 'out' ? (matrix[i]?.[focus.j] ?? 0) : s.vol,
  )
  const rightNodeVals = outputs.map((o, j) =>
    focusBroken
      ? 0
      : focus.t === 'src'
        ? (matrix[focus.i]?.[j] ?? 0)
        : o.vol,
  )

  const leftRibVals = sources.map((s, i) =>
    focus.t === 'src'
      ? i === focus.i
        ? s.vol
        : 0
      : focus.t === 'out'
        ? (matrix[i]?.[focus.j] ?? 0)
        : s.vol,
  )
  const rightRibVals = outputs.map((o, j) =>
    focusBroken
      ? 0
      : focus.t === 'out'
        ? j === focus.j
          ? o.vol
          : 0
        : focus.t === 'src'
          ? (matrix[focus.i]?.[j] ?? 0)
          : o.vol,
  )

  const leftNodes = layNodes(leftNodeVals, scale)
  const rightNodes = layNodes(rightNodeVals, scale)

  const activeTotal = leftRibVals.reduce((a, b) => a + b, 0)
  const faceStart = TOP + Math.max(0, (BAR_H - activeTotal * scale) / 2)

  let lc = faceStart
  const lf = leftRibVals.map((v) => {
    const b = { y: lc, h: v * scale }
    lc += v * scale
    return b
  })

  let rc = faceStart
  const rf = rightRibVals.map((v) => {
    const b = { y: rc, h: v * scale }
    rc += v * scale
    return b
  })

  const leftRib: RibbonLayout[] = sources.map((s, i) => {
    const n = leftNodes[i]
    const f = lf[i]
    const v = leftRibVals[i]
    const isBroken = broken.has(s.id)
    const r =
      v > 0
        ? ribbonPath(xL + NODE_W, BAR_X, n.y, n.y + n.h, f.y, f.y + f.h)
        : ribbonPath(
            xL + NODE_W,
            BAR_X,
            n.y + n.h / 2,
            n.y + n.h / 2,
            faceStart,
            faceStart,
          )
    return {
      side: 'L' as const,
      idx: i,
      color: SOURCE_COLORS[s.id] ?? DEFAULT_SRC_COLOR,
      value: Math.max(1, v),
      on: v > 0,
      broken: isBroken,
      ...r,
    }
  })

  const rightRib: RibbonLayout[] = outputs.map((o, j) => {
    const n = rightNodes[j]
    const f = rf[j]
    const v = rightRibVals[j]
    const r =
      v > 0
        ? ribbonPath(BAR_RX, xR, f.y, f.y + f.h, n.y, n.y + n.h)
        : ribbonPath(
            BAR_RX,
            xR,
            faceStart,
            faceStart,
            n.y + n.h / 2,
            n.y + n.h / 2,
          )
    return {
      side: 'R' as const,
      idx: j,
      color: OUTPUT_COLORS[o.id] ?? DEFAULT_OUTPUT_COLOR,
      value: Math.max(1, v),
      on: v > 0,
      broken: false,
      ...r,
    }
  })

  return {
    leftNodes,
    rightNodes,
    ribbons: [...leftRib, ...rightRib],
  }
}

// ---- Transition styles ----

const RIB_TR: CSSProperties = {
  transition: 'd .28s ease, fill-opacity .2s ease',
}
const NODE_TR: CSSProperties = {
  transition: 'y .28s ease, height .28s ease, opacity .15s ease',
}
const FO_TR: CSSProperties = { transition: 'y .28s ease' }

// ---- Component ----

export function SourceFlow({
  data,
  stalledSources,
  ingestRate = 0,
  egressRate = 0,
  error,
  onNavigate,
}: SourceFlowProps) {
  const broken = stalledSources ?? new Set<string>()
  const [focus, setFocus] = useState<FocusState>({
    t: 'none',
    i: -1,
    j: -1,
  })

  const pathRefs = useRef<(SVGPathElement | null)[]>([])
  const dotRefs = useRef<(SVGCircleElement | null)[]>([])

  // -- Error state --
  if (error) {
    return (
      <Card
        data-testid="source-flow-error"
        className="border-destructive/50 bg-destructive/10"
      >
        <CardContent className="flex items-center gap-3 p-4 text-destructive">
          <TriangleAlert size={18} />
          <span className="text-sm">{error}</span>
        </CardContent>
      </Card>
    )
  }

  // -- Loading state --
  if (!data) {
    return (
      <div data-testid="source-flow-loading">
        <Skeleton className="h-[200px] w-full rounded-lg" />
      </div>
    )
  }

  // -- Empty state (all zero volumes) --
  const totalVol =
    data.sources.reduce((a, s) => a + s.vol, 0) +
    data.outputs.reduce((a, o) => a + o.vol, 0)

  return (
    <SourceFlowInner
      data={data}
      broken={broken}
      focus={focus}
      setFocus={setFocus}
      totalVol={totalVol}
      ingestRate={ingestRate}
      egressRate={egressRate}
      pathRefs={pathRefs}
      dotRefs={dotRefs}
      onNavigate={onNavigate}
    />
  )
}

// Inner component that renders the actual SVG. Split out so the outer
// SourceFlow can handle loading/error/empty without refs.
function SourceFlowInner({
  data,
  broken,
  focus,
  setFocus,
  totalVol,
  ingestRate,
  egressRate,
  pathRefs,
  dotRefs,
  onNavigate,
}: {
  data: FlowMatrix
  broken: Set<string>
  focus: FocusState
  setFocus: (f: FocusState) => void
  totalVol: number
  ingestRate: number
  egressRate: number
  pathRefs: React.MutableRefObject<(SVGPathElement | null)[]>
  dotRefs: React.MutableRefObject<(SVGCircleElement | null)[]>
  onNavigate?: (to: string) => void
}) {
  const layout = useMemo(
    () => computeLayout(data, broken, focus),
    [data, broken, focus],
  )

  const isEmpty = totalVol === 0

  // Detect prefers-reduced-motion.
  const reducedMotion = useRef(false)
  useEffect(() => {
    const mql = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedMotion.current = mql.matches
    const handler = (e: MediaQueryListEvent) => {
      reducedMotion.current = e.matches
    }
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  // Dot animation loop via rAF. The 80-dot pool flows along cubic Bezier
  // ribbon paths. Spawn rate is proportional to source volume.
  useEffect(() => {
    if (reducedMotion.current) return
    const paths = pathRefs.current
    // Guard: jsdom and some environments lack SVG geometry methods.
    const lens = paths.map((p) =>
      p && typeof p.getTotalLength === 'function' ? p.getTotalLength() : 0,
    )
    const ribbons = layout.ribbons
    const spawnable = ribbons.map((r) => (r.on && !r.broken ? r.value : 0))
    const totalVal = spawnable.reduce((a, b) => a + b, 0) || 1

    interface Dot {
      active: boolean
      r: number
      t: number
      speed: number
    }

    const dots: Dot[] = Array.from({ length: POOL }, () => ({
      active: false,
      r: 0,
      t: 0,
      speed: 0,
    }))

    const pick = (): number => {
      let x = Math.random() * totalVal
      for (let k = 0; k < spawnable.length; k++) {
        x -= spawnable[k]
        if (x <= 0) return k
      }
      return 0
    }

    // Seed initial dots at random progress along their paths.
    const seedCount = Math.min(54, POOL)
    for (let i = 0; i < seedCount; i++) {
      dots[i].active = true
      dots[i].r = pick()
      dots[i].t = Math.random()
      dots[i].speed = TRAVERSAL_BASE + Math.random() * TRAVERSAL_RANGE
    }

    const setDot = (d: Dot, c: SVGCircleElement) => {
      if (!d.active) {
        c.style.opacity = '0'
        return
      }
      const rb = ribbons[d.r]
      const p = paths[d.r]
      if (!p || !rb.on || typeof p.getPointAtLength !== 'function') {
        c.style.opacity = '0'
        return
      }
      const pt = p.getPointAtLength(d.t * lens[d.r])
      c.setAttribute('cx', pt.x.toFixed(1))
      c.setAttribute('cy', pt.y.toFixed(1))
      c.setAttribute('fill', rb.color)
      c.style.opacity = '0.95'
    }

    // Initial positions.
    for (let i = 0; i < dots.length; i++) {
      const c = dotRefs.current[i]
      if (c) setDot(dots[i], c)
    }

    // Per-ribbon accumulator for spawn scheduling.
    const accum = ribbons.map(() => Math.random())
    let raf: number
    let last = performance.now()

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now

      for (let r = 0; r < ribbons.length; r++) {
        if (spawnable[r] <= 0) continue
        accum[r] += spawnable[r] * SPAWN_RATE * dt
        while (accum[r] >= 1) {
          accum[r] -= 1
          const free = dots.findIndex((d) => !d.active)
          if (free >= 0) {
            dots[free].active = true
            dots[free].r = r
            dots[free].t = 0
            dots[free].speed =
              TRAVERSAL_BASE + Math.random() * TRAVERSAL_RANGE
          }
        }
      }

      for (let i = 0; i < dots.length; i++) {
        const d = dots[i]
        const c = dotRefs.current[i]
        if (!c) continue
        if (d.active) {
          d.t += d.speed * dt
          if (d.t >= 1) d.active = false
        }
        setDot(d, c)
      }

      raf = requestAnimationFrame(frame)
    }

    // Visibility API: pause when tab hidden.
    const onVisChange = () => {
      if (document.hidden) {
        cancelAnimationFrame(raf)
      } else {
        last = performance.now()
        raf = requestAnimationFrame(frame)
      }
    }
    document.addEventListener('visibilitychange', onVisChange)

    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      document.removeEventListener('visibilitychange', onVisChange)
    }
  }, [layout, pathRefs, dotRefs])

  const ribOpacity = (rb: RibbonLayout) =>
    rb.on ? (focus.t === 'none' ? 0.26 : 0.42) : 0
  const leftDim = (i: number) => focus.t === 'src' && i !== focus.i
  const rightDim = (j: number) => focus.t === 'out' && j !== focus.j

  const handleSourceEnter = useCallback(
    (i: number) => setFocus({ t: 'src', i, j: -1 }),
    [setFocus],
  )
  const handleOutputEnter = useCallback(
    (j: number) => setFocus({ t: 'out', i: -1, j }),
    [setFocus],
  )
  const handleLeave = useCallback(
    () => setFocus({ t: 'none', i: -1, j: -1 }),
    [setFocus],
  )

  return (
    <div
      data-testid="source-flow"
      style={{ maxWidth: 1100, margin: '0 auto' }}
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height="auto"
        style={{ display: 'block' }}
        role="img"
        aria-label="Signal flow: input sources through WorkBench to outputs. Hover a source or output to see its breakdown."
      >
        <title>
          Source flow diagram showing {data.sources.length} sources feeding
          through WorkBench to {data.outputs.length} output buckets
        </title>

        {/* Ribbon bands (filled regions) */}
        {layout.ribbons.map((rb) => (
          <path
            key={rb.side + rb.idx}
            d={rb.band}
            fill={rb.broken ? '#e5484d' : rb.color}
            fillOpacity={
              rb.broken ? (rb.on ? 0.12 : 0) : ribOpacity(rb)
            }
            stroke={rb.broken && rb.on ? '#e5484d' : 'none'}
            strokeWidth={rb.broken && rb.on ? 1 : 0}
            strokeOpacity="0.6"
            strokeDasharray={rb.broken ? '5 3' : undefined}
            style={RIB_TR}
          />
        ))}

        {/* Hidden mid-paths for dot flow (stroke:none, no visual) */}
        {layout.ribbons.map((rb, i) => (
          <path
            key={`m${i}`}
            ref={(el) => {
              pathRefs.current[i] = el
            }}
            d={rb.mid}
            fill="none"
            stroke="none"
          />
        ))}

        {/* Dot pool */}
        {Array.from({ length: POOL }).map((_, i) => (
          <circle
            key={`d${i}`}
            ref={(el) => {
              dotRefs.current[i] = el
            }}
            r="2.4"
            data-dot
            style={{ opacity: 0 }}
          />
        ))}

        {/* Central WorkBench module */}
        <rect
          x={BAR_X}
          y={TOP}
          width={BAR_W}
          height={BAR_H}
          rx="10"
          fill="var(--card)"
          stroke="var(--border)"
        />
        <rect
          x={BAR_X}
          y={TOP}
          width={BAR_W}
          height={BAR_H}
          rx="10"
          fill="none"
          stroke="var(--primary)"
          strokeOpacity="0.25"
        />
        <foreignObject
          x={BAR_X}
          y={TOP}
          width={BAR_W}
          height={BAR_H}
        >
          <div
            style={{
              width: '100%',
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px 0',
              boxSizing: 'border-box',
            }}
          >
            <div
              title="Ingestion rate"
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 1,
                color: 'var(--brand, var(--primary))',
              }}
            >
              <ArrowDownToLine size={13} />
              <span className="font-mono font-bold" style={{ fontSize: 10 }}>
                {ingestRate}
              </span>
              <span
                className="font-mono text-muted-foreground"
                style={{
                  fontSize: 7,
                  letterSpacing: '.08em',
                }}
              >
                IN/h
              </span>
            </div>
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                flex: 1,
              }}
            >
              <img
                src={`${import.meta.env.BASE_URL}wb-icon.svg`}
                alt="WorkBench"
                width="34"
                height="34"
                style={{ display: 'block' }}
              />
            </div>
            <div
              title="Egress rate"
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 1,
                color: '#9a7af0',
              }}
            >
              <span
                className="font-mono text-muted-foreground"
                style={{
                  fontSize: 7,
                  letterSpacing: '.08em',
                }}
              >
                OUT/h
              </span>
              <span className="font-mono font-bold" style={{ fontSize: 10 }}>
                {egressRate}
              </span>
              <ArrowUpFromLine size={13} />
            </div>
          </div>
        </foreignObject>

        {/* Source nodes (left side) */}
        {layout.leftNodes.map((n, i) => {
          const src = data.sources[i]
          if (!src) return null
          const brk = broken.has(src.id)
          const SrcIcon = SRC_ICONS[src.id] ?? Github
          return (
            <g
              key={src.id}
              data-source={src.id}
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => handleSourceEnter(i)}
              onMouseLeave={handleLeave}
            >
              <title>
                {src.label}
                {brk ? ' — ingestion stalled' : ''}
              </title>
              <rect
                x={xL}
                y={n.y}
                width={NODE_W}
                height={Math.max(3, n.h)}
                rx="2"
                fill={brk ? '#e5484d' : SOURCE_COLORS[src.id] ?? DEFAULT_SRC_COLOR}
                opacity={leftDim(i) ? 0.32 : 1}
                style={NODE_TR}
              />
              <foreignObject
                x={xL - 112}
                y={n.y + n.h / 2 - 14}
                width="104"
                height="28"
                style={FO_TR}
              >
                <div
                  style={{
                    height: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'flex-end',
                    gap: 6,
                    opacity: leftDim(i) ? 0.4 : 1,
                    transition: 'opacity .15s ease',
                  }}
                >
                  <SrcIcon
                    size={17}
                    style={{
                      color: brk
                        ? '#e5484d'
                        : SOURCE_COLORS[src.id] ?? DEFAULT_SRC_COLOR,
                    }}
                  />
                  {brk ? (
                    <span
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 3,
                        color: '#e5484d',
                      }}
                    >
                      <TriangleAlert size={12} />
                      <span
                        className="font-mono font-bold uppercase"
                        style={{
                          fontSize: 9,
                          letterSpacing: '.04em',
                        }}
                      >
                        stalled
                      </span>
                    </span>
                  ) : (
                    <span className="font-mono text-xs font-bold">
                      {perDay(n.v)}
                      <span
                        className="font-mono text-muted-foreground"
                        style={{
                          fontSize: 8,
                          fontWeight: 500,
                        }}
                      >
                        /d
                      </span>
                    </span>
                  )}
                </div>
              </foreignObject>
            </g>
          )
        })}

        {/* Output nodes (right side) */}
        {layout.rightNodes.map((n, j) => {
          const out = data.outputs[j]
          if (!out) return null
          const OutIcon = OUTPUT_ICONS[out.id] ?? Filter
          const route = OUTPUT_ROUTES[out.id]
          return (
            <g
              key={out.id}
              data-output={out.id}
              style={{ cursor: route ? 'pointer' : 'default' }}
              onMouseEnter={() => handleOutputEnter(j)}
              onMouseLeave={handleLeave}
              onClick={() => {
                if (route && onNavigate) onNavigate(route)
              }}
            >
              <title>{out.label}</title>
              <rect
                x={xR}
                y={n.y}
                width={NODE_W}
                height={Math.max(3, n.h)}
                rx="2"
                fill={OUTPUT_COLORS[out.id] ?? DEFAULT_OUTPUT_COLOR}
                fillOpacity="0.85"
                opacity={rightDim(j) ? 0.32 : 1}
                style={NODE_TR}
              />
              <foreignObject
                x={xR + NODE_W + 8}
                y={n.y + n.h / 2 - 16}
                width="140"
                height="34"
                style={FO_TR}
              >
                <div
                  style={{
                    height: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    opacity: rightDim(j) ? 0.4 : 1,
                    transition: 'opacity .15s ease',
                  }}
                >
                  <OutIcon
                    size={17}
                    style={{
                      color:
                        OUTPUT_COLORS[out.id] ?? DEFAULT_OUTPUT_COLOR,
                    }}
                  />
                  <div
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      lineHeight: 1.15,
                    }}
                  >
                    <span className="font-mono text-xs font-bold whitespace-nowrap">
                      {Math.round(n.v)}
                    </span>
                    <span
                      className="font-mono text-muted-foreground uppercase whitespace-nowrap"
                      style={{
                        fontSize: 8,
                        letterSpacing: '.05em',
                      }}
                    >
                      {out.label}
                    </span>
                  </div>
                </div>
              </foreignObject>
            </g>
          )
        })}
      </svg>

      {/* sr-only table fallback for screen readers */}
      <table className="sr-only" data-testid="source-flow-sr-table">
        <caption>Source flow data: sources and their output breakdown</caption>
        <thead>
          <tr>
            <th>Source</th>
            <th>Volume</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {data.sources.map((s) => (
            <tr key={s.id}>
              <td>{s.label}</td>
              <td>{s.vol}</td>
              <td>{broken.has(s.id) ? 'stalled' : 'active'}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={3}>
              Outputs:{' '}
              {data.outputs
                .map((o) => `${o.label}: ${o.vol}`)
                .join(', ')}
            </td>
          </tr>
        </tfoot>
      </table>

      {/* Empty overlay for zero-volume */}
      {isEmpty && (
        <div
          data-testid="source-flow-empty"
          className="font-mono text-xs text-muted-foreground text-center py-2"
        >
          // No signal flow — all volumes are zero
        </div>
      )}
    </div>
  )
}
