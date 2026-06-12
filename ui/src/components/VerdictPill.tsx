import type { Verdict } from '@/lib/types/funnel'
import { cn } from '@/lib/utils'
import { Inbox, CircleSlash, CircleCheckBig } from 'lucide-react'

const VERDICT_CONFIG = {
  queued: {
    fg: '#06303f',
    bg: 'var(--tertiary)',
    icon: Inbox,
    label: 'in triage queue',
  },
  dropped: {
    fg: '#ffb4ab',
    bg: 'color-mix(in srgb, #93000a 32%, transparent)',
    icon: CircleSlash,
    label: 'dropped',
  },
  triaged: {
    fg: '#0e0e11',
    bg: 'var(--success)',
    icon: CircleCheckBig,
    label: 'triaged',
  },
} as const

/**
 * VerdictPill — decision badge showing the final verdict of an item.
 * Colors: queued=tertiary, dropped=destructive, triaged=success.
 */
export function VerdictPill({
  verdict,
  large,
  className,
}: {
  verdict: Verdict
  large?: boolean
  className?: string
}) {
  const cfg = VERDICT_CONFIG[verdict.decision] ?? VERDICT_CONFIG.triaged
  const Icon = cfg.icon

  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 font-mono font-bold uppercase tracking-[.04em]',
        large ? 'px-3 py-1.5 text-[13px]' : 'px-2 py-0.5 text-[11px]',
        className,
      )}
      style={{
        borderRadius: 'var(--radius-chip, 2px)',
        color: cfg.fg,
        background: cfg.bg,
      }}
      data-verdict={verdict.decision}
    >
      <Icon size={large ? 14 : 11} />
      {cfg.label}
      {verdict.priority ? ` · ~${verdict.priority}` : ''}
      {typeof verdict.confidence === 'number' ? ` · ${verdict.confidence}%` : ''}
    </span>
  )
}
