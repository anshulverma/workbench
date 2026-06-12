import type { CSSProperties, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Mono — the canonical wrapper for all numbers, timestamps, IDs, git hashes,
 * cron expressions, code, and metric values (spec §2). Applies `font-mono` +
 * `tabular-nums` so digits stay column-aligned, and forwards an extra className.
 */
export function Mono({
  children,
  className,
  style,
}: {
  children: ReactNode
  className?: string
  style?: CSSProperties
}) {
  return (
    <span className={cn('font-mono tabular-nums', className)} style={style}>
      {children}
    </span>
  )
}
