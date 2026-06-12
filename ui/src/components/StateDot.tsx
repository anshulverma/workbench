import type { ItemState } from '@/lib/types/search'
import { cn } from '@/lib/utils'

const STATE_META: Record<ItemState, { label: string; color: string }> = {
  triaged: { label: 'triaged', color: 'var(--success)' },
  pending_triage: { label: 'in triage queue', color: 'var(--tertiary)' },
  action_item: { label: 'action item', color: 'var(--primary)' },
  dropped: { label: 'dropped', color: 'var(--muted-foreground)' },
  archived: { label: 'archived', color: 'var(--muted-foreground)' },
}

/**
 * StateDot — small colored dot + label for item state.
 * Colors vary per state.
 */
export function StateDot({
  state,
  className,
}: {
  state: ItemState
  className?: string
}) {
  const m = STATE_META[state] ?? STATE_META.triaged

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground',
        className,
      )}
      data-state={state}
    >
      <span
        className="size-[7px] shrink-0 rounded-full"
        style={{ background: m.color }}
        aria-hidden="true"
      />
      {m.label}
    </span>
  )
}
