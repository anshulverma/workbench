import type { StageOutcome } from '@/lib/types/funnel'
import { STAGE_META } from '@/lib/funnel-constants'
import { cn } from '@/lib/utils'
import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/**
 * ActionChip — color-coded action badge using STAGE_META from funnel-constants.
 * Renders the stage icon, label, and optional confidence percentage.
 */
export function ActionChip({
  action,
  label,
  confidence,
  small,
  className,
}: {
  action: StageOutcome
  label?: string
  confidence?: number
  small?: boolean
  className?: string
}) {
  const m = STAGE_META[action] ?? STAGE_META.pass
  const Icon = (Icons as unknown as Record<string, LucideIcon>)[m.icon]

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 font-mono font-bold uppercase tracking-[.04em]',
        small ? 'px-1.5 py-px text-[10px]' : 'px-2 py-0.5 text-[11px]',
        action === 'skip' ? 'border border-dashed border-border' : '',
        className,
      )}
      style={{
        borderRadius: 'var(--radius-chip, 2px)',
        color: m.chipFg,
        background: m.chipBg,
      }}
      data-action={action}
    >
      {Icon && <Icon size={small ? 10 : 11} />}
      {action === 'label' ? `label: ${label ?? ''}` : m.label}
      {typeof confidence === 'number' ? ` ${confidence}%` : ''}
    </span>
  )
}
