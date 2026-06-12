import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * SectionHeader — mono uppercase label used to separate content sections.
 * Optionally renders a right-side element (counts, links, etc.).
 */
export function SectionHeader({
  children,
  right,
  className,
}: {
  children: ReactNode
  right?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-center justify-between gap-4', className)}>
      <h3 className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {children}
      </h3>
      {right && <div>{right}</div>}
    </div>
  )
}
