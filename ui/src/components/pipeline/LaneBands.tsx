// LaneBands — the phase columns behind the DAG (Source → Pre-extraction →
// Extraction → Post-extraction → Sinks). Decorative + a per-lane label; the
// lane geometry comes from the auto-layout pass.

import type { LaneBand } from '@/lib/types/pipeline'
import { CANVAS_H } from './geometry'

export interface LaneBandsProps {
  lanes: LaneBand[]
  height?: number
}

export function LaneBands({ lanes, height }: LaneBandsProps) {
  const h = height ?? CANVAS_H
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0">
      {lanes.map((ln, i) => (
        <div
          key={ln.key}
          className="absolute top-0"
          style={{
            left: ln.x,
            width: ln.w,
            height: h,
            borderRight:
              i < lanes.length - 1
                ? '1px dashed color-mix(in srgb, var(--border) 70%, transparent)'
                : 'none',
            background:
              i % 2
                ? 'color-mix(in srgb, var(--surface-low) 35%, transparent)'
                : 'transparent',
          }}
        >
          <span
            className="absolute font-mono uppercase tracking-[0.08em] text-muted-foreground"
            style={{ top: 10, left: 12, fontSize: 10, opacity: 0.85 }}
          >
            {ln.label}
          </span>
        </div>
      ))}
    </div>
  )
}
