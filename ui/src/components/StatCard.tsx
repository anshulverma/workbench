import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Mono } from '@/components/Mono'
import { cn } from '@/lib/utils'

/**
 * StatCard — a single scalar metric tile (spec §5).
 *
 * The value renders in mono + tabular-nums (large) and the label is an
 * uppercase mono micro-label. Optional `delta` sits next to the value (e.g.
 * "+2") and `sub` fills a slot below the value (e.g. a <Sparkline/>). The
 * public API ({label, value, danger}) is preserved; `delta`/`sub` are additive.
 */
export function StatCard({
  label,
  value,
  danger,
  delta,
  sub,
}: {
  label: string
  value: ReactNode
  danger?: boolean
  delta?: ReactNode
  sub?: ReactNode
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <Mono
            className={cn(
              'text-2xl font-bold',
              danger ? 'text-destructive' : undefined,
            )}
          >
            {value}
          </Mono>
          {delta != null ? (
            <Mono className="text-xs text-muted-foreground">{delta}</Mono>
          ) : null}
        </div>
        {sub != null ? <div className="mt-2">{sub}</div> : null}
      </CardContent>
    </Card>
  )
}
