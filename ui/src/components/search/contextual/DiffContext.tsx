import { ExternalLink, User } from 'lucide-react'
import type { DiffContext as DiffContextType } from '@/lib/types/search'
import { DiffHunks } from '@/components/DiffHunks'
import { Mono } from '@/components/Mono'
import { Badge } from '@/components/ui/badge'

/**
 * DiffContext — contextual payload renderer for diff/PR items.
 * Shows author, team, review status, a link to Phabricator, and curated hunks.
 */
export function DiffContext({ ctx }: { ctx: DiffContextType }) {
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2.5 text-[13px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <User size={14} />
          <Mono className="text-[13px]">{ctx.author}</Mono>
        </span>
        <span aria-hidden="true">&middot;</span>
        <span>{ctx.team}</span>
        <Badge variant="outline">{ctx.status}</Badge>
        <a
          href={ctx.url}
          target="_blank"
          rel="noreferrer"
          className="ml-auto inline-flex items-center gap-1.5 text-[13px] text-[var(--tertiary)] no-underline hover:underline"
        >
          <ExternalLink size={14} /> View in Phabricator
        </a>
      </div>
      <DiffHunks hunks={ctx.hunks} maxHunks={6} />
    </div>
  )
}
