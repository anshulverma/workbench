import { SRC_ICON } from '@/lib/funnel-constants'
import { cn } from '@/lib/utils'
import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Database } from 'lucide-react'

/**
 * SourceChip — source icon + name chip. Uses SRC_ICON from funnel-constants
 * to resolve the icon; falls back to Database if unknown.
 */
export function SourceChip({
  name,
  className,
}: {
  name: string
  className?: string
}) {
  const iconName = SRC_ICON[name]
  const Icon: LucideIcon =
    (iconName
      ? (Icons as unknown as Record<string, LucideIcon>)[iconName]
      : null) ?? Database

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-sm border border-border bg-[var(--surface-high)] px-2 py-0.5 font-mono text-[11px] text-foreground',
        className,
      )}
    >
      <Icon size={12} />
      {name}
    </span>
  )
}
