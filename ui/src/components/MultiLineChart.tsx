import { useState } from 'react'
import { smoothPath } from '@/lib/funnel-helpers'

export interface ChartSeries {
  name: string
  color: string
  data: number[]
}

/**
 * MultiLineChart -- custom SVG multi-series line chart.
 *
 * Features:
 * - Catmull-Rom smoothed curves via smoothPath
 * - Multiple series with colors + legend
 * - Hover tooltip showing values at cursor position, flips at 75% x-threshold
 * - Y-axis labels, X-axis labels (every Nth)
 * - HTML overlay for axis labels (not inside stretched SVG)
 */
export function MultiLineChart({
  series,
  height = 132,
  xLabels,
}: {
  series: ChartSeries[]
  height?: number
  xLabels?: string[]
}) {
  const W = 320
  const pad = { l: 30, r: 10, t: 10, b: 8 }
  const n = Math.max(...series.map((s) => s.data.length), 1)
  const max = Math.max(...series.flatMap((s) => s.data), 1)
  const iw = W - pad.l - pad.r
  const ih = height - pad.t - pad.b

  const x = (i: number) => pad.l + (i / Math.max(n - 1, 1)) * iw
  const y = (v: number) => pad.t + ih - (v / max) * ih

  const ticks = [0, Math.round(max / 2), max]
  const xPct = (i: number) => (x(i) / W) * 100
  const yPct = (v: number) => (y(v) / height) * 100

  const [hover, setHover] = useState<number | null>(null)

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const vbx = ((e.clientX - r.left) / r.width) * W
    const idx = Math.round(((vbx - pad.l) / iw) * (n - 1))
    setHover(Math.max(0, Math.min(n - 1, idx)))
  }

  return (
    <div data-testid="multi-line-chart" style={{ position: 'relative' }}>
      <div style={{ position: 'relative', height }}>
        {/* y-axis labels (HTML -- undistorted) */}
        {ticks.map((t, k) => (
          <span
            key={k}
            data-testid="y-label"
            style={{
              position: 'absolute',
              left: 0,
              top: `${yPct(t)}%`,
              transform: 'translateY(-50%)',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--muted-foreground)',
              pointerEvents: 'none',
            }}
          >
            {t}
          </span>
        ))}

        <svg
          viewBox={`0 0 ${W} ${height}`}
          width="100%"
          height={height}
          preserveAspectRatio="none"
          style={{ display: 'block' }}
          data-testid="chart-svg"
        >
          {/* grid lines */}
          {ticks.map((t, k) => (
            <line
              key={k}
              x1={pad.l}
              x2={W - pad.r}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--border)"
              strokeDasharray="3 3"
            />
          ))}
          {/* series curves */}
          {series.map((s, si) => (
            <path
              key={si}
              data-testid="series-path"
              d={smoothPath(s.data.map((v, i) => [x(i), y(v)]))}
              fill="none"
              stroke={s.color}
              strokeWidth="1.6"
              vectorEffect="non-scaling-stroke"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}
          {/* hover vertical line */}
          {hover != null && (
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={pad.t}
              y2={pad.t + ih}
              stroke="var(--muted-foreground)"
              strokeOpacity="0.4"
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>

        {/* hover dots (HTML, % positioned so they aren't stretched) */}
        {hover != null &&
          series.map((s, si) => (
            <span
              key={si}
              data-testid="hover-dot"
              style={{
                position: 'absolute',
                left: `${xPct(hover)}%`,
                top: `${yPct(s.data[hover])}%`,
                width: 7,
                height: 7,
                marginLeft: -3.5,
                marginTop: -3.5,
                borderRadius: 9999,
                background: s.color,
                border: '1.5px solid var(--card)',
                pointerEvents: 'none',
              }}
            />
          ))}

        {/* tooltip */}
        {hover != null && (
          <div
            data-testid="chart-tooltip"
            style={{
              position: 'absolute',
              left: `${xPct(hover)}%`,
              top: -4,
              transform: `translate(${xPct(hover) > 75 ? 'calc(-100% - 8px)' : '8px'}, 0)`,
              background: 'var(--popover)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-control, 4px)',
              boxShadow: 'var(--shadow-pop)',
              padding: '6px 8px',
              pointerEvents: 'none',
              zIndex: 5,
              whiteSpace: 'nowrap',
            }}
          >
            {xLabels && (
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9,
                  color: 'var(--muted-foreground)',
                  marginBottom: 3,
                }}
              >
                {xLabels[hover]}
              </div>
            )}
            {series.map((s, si) => (
              <div
                key={si}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: 11,
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 2,
                    background: s.color,
                    flexShrink: 0,
                  }}
                />
                <span style={{ color: 'var(--muted-foreground)' }}>
                  {s.name}
                </span>
                <span
                  style={{
                    marginLeft: 'auto',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 700,
                  }}
                >
                  {s.data[hover]}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* invisible hover capture layer */}
        <div
          data-testid="hover-capture"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          style={{ position: 'absolute', inset: 0, cursor: 'crosshair' }}
        />
      </div>

      {/* x-axis labels */}
      {xLabels && (
        <div
          data-testid="x-axis-labels"
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            paddingLeft: `${(pad.l / W) * 100}%`,
            paddingRight: `${(pad.r / W) * 100}%`,
            marginTop: 4,
          }}
        >
          {xLabels
            .filter((_, i) => {
              const step = Math.max(1, Math.floor(xLabels.length / 6))
              return i % step === 0 || i === xLabels.length - 1
            })
            .map((label, i) => (
              <span
                key={i}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9,
                  color: 'var(--muted-foreground)',
                }}
              >
                {label}
              </span>
            ))}
        </div>
      )}

      {/* legend */}
      <div
        data-testid="chart-legend"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '4px 14px',
          marginTop: 10,
        }}
      >
        {series.map((s, si) => (
          <span
            key={si}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 11,
              color: 'var(--muted-foreground)',
            }}
          >
            <span
              style={{
                width: 12,
                height: 2.5,
                borderRadius: 2,
                background: s.color,
                flexShrink: 0,
              }}
            />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  )
}
