import type { MeetingContext as MeetingContextType } from '@/lib/types/search'
import { Mono } from '@/components/Mono'
import { relativeTime } from '@/lib/format'

/**
 * MeetingContext — contextual payload renderer for meeting items.
 * Shows when/duration/location/attendees metadata and the agenda block.
 */
export function MeetingContext({ ctx }: { ctx: MeetingContextType }) {
  return (
    <div className="grid gap-3">
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
        <dt className="text-muted-foreground">when</dt>
        <dd className="m-0">
          {relativeTime(ctx.when)} &middot; {ctx.duration}
        </dd>
        <dt className="text-muted-foreground">where</dt>
        <dd className="m-0">{ctx.location}</dd>
        <dt className="text-muted-foreground">attendees</dt>
        <dd className="m-0 flex flex-wrap gap-1.5">
          {ctx.attendees.map((a) => (
            <Mono key={a} className="text-xs">
              {a}
            </Mono>
          ))}
        </dd>
      </dl>
      <div className="rounded-md border border-border bg-[var(--surface-lowest)] p-3.5">
        <span className="mb-1.5 block font-mono text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Agenda
        </span>
        {ctx.agenda ? (
          <p className="m-0 text-sm">{ctx.agenda}</p>
        ) : (
          <p className="m-0 font-mono text-[13px] text-[var(--brand)]">
            // no agenda posted yet
          </p>
        )}
      </div>
    </div>
  )
}
