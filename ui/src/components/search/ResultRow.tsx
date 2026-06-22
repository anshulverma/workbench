import {
  GitPullRequestArrow,
  Mail,
  Calendar,
  MessageCircle,
  FileText,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { SearchItem } from '@/lib/types/search'
import { relativeTime } from '@/lib/format'
import { Mono } from '@/components/Mono'
import { Badge } from '@/components/ui/badge'
import { StateDot } from '@/components/StateDot'
import { cn } from '@/lib/utils'

const KIND_ICON: Record<string, LucideIcon> = {
  diff: GitPullRequestArrow,
  pr: GitPullRequestArrow,
  email: Mail,
  meeting: Calendar,
  chat: MessageCircle,
}

const PRIORITY_VARIANT: Record<string, 'p0' | 'p1' | 'p2' | 'p3'> = {
  P0: 'p0',
  P1: 'p1',
  P2: 'p2',
  P3: 'p3',
}

/**
 * ResultRow — list row for a search result. Shows kind icon, item ID,
 * priority badge, state dot, summary, source + time + relevance.
 * Used as an `role="option"` inside the result listbox.
 */
export function ResultRow({
  item,
  active,
  onClick,
  id,
}: {
  item: SearchItem
  active: boolean
  onClick: () => void
  id?: string
}) {
  const Icon = KIND_ICON[item.kind] ?? FileText

  return (
    <div
      id={id}
      role="option"
      aria-selected={active}
      tabIndex={-1}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
      className={cn(
        'grid w-full cursor-pointer gap-1.5 rounded-md border p-3 text-left text-foreground transition-colors',
        active
          ? 'border-primary bg-[color-mix(in_srgb,var(--primary)_8%,var(--card))]'
          : 'border-border bg-card hover:border-muted-foreground/40',
      )}
    >
      <div className="flex items-center gap-2">
        <Icon size={14} className="shrink-0 text-[var(--brand)]" />
        <Mono className="text-[11px] text-muted-foreground">{item.id}</Mono>
        {item.priority && (
          <Badge variant={PRIORITY_VARIANT[item.priority] ?? 'p3'}>
            {item.priority}
          </Badge>
        )}
        <span className="ml-auto">
          <StateDot state={item.state} />
        </span>
      </div>
      <span className="truncate text-[13px] font-medium leading-snug text-foreground">
        {item.summary}
      </span>
      <Mono className="text-[11px] text-muted-foreground">
        {item.source} &middot; {relativeTime(item.created_at)} &middot;
        relevance {item.relevance}
      </Mono>
    </div>
  )
}
