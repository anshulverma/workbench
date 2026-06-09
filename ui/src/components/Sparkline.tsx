import { Area, AreaChart, ResponsiveContainer, YAxis } from 'recharts'
import { CHART_COLORS } from '@/lib/chart-theme'
import { cn } from '@/lib/utils'

export interface SparklinePoint {
  count: number
}

/**
 * Sparkline — a compact, axis-less trend chart (spec §5, ADR 0038).
 *
 * Degenerate states are standardized:
 *  - empty data  → a flat baseline + an em-dash placeholder ("—").
 *  - single point → a single dot (a one-point line is meaningless).
 *  - else        → a Recharts area sparkline in the brand orange.
 */
export function Sparkline({
  data,
  dataKey = 'count',
  color = CHART_COLORS.primary,
  className,
  height = 32,
}: {
  data: SparklinePoint[]
  dataKey?: string
  color?: string
  className?: string
  height?: number
}) {
  if (data.length === 0) {
    return (
      <div
        className={cn(
          'flex items-center justify-center font-mono text-xs text-muted-foreground',
          className,
        )}
        style={{ height }}
        aria-hidden="true"
      >
        <span className="relative w-full">
          <span className="absolute inset-x-0 top-1/2 border-t border-border" />
          <span className="relative z-10 block text-center">—</span>
        </span>
      </div>
    )
  }

  if (data.length === 1) {
    return (
      <div
        className={cn('flex items-center', className)}
        style={{ height }}
        aria-hidden="true"
      >
        <span
          data-sparkline-dot
          className="inline-block size-1.5 rounded-full"
          style={{ backgroundColor: color }}
        />
      </div>
    )
  }

  return (
    <div className={className} style={{ height }} aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={data}
          margin={{ top: 2, right: 0, bottom: 2, left: 0 }}
        >
          <YAxis hide domain={['dataMin', 'dataMax']} />
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            fill={color}
            fillOpacity={0.2}
            strokeWidth={1.5}
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
