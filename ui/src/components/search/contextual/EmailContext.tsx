import type { EmailContext as EmailContextType } from '@/lib/types/search'
import { Mono } from '@/components/Mono'
import { relativeTime } from '@/lib/format'

/**
 * EmailContext — contextual payload renderer for email items.
 * Shows from/to/when metadata and the email body in a pre block.
 */
export function EmailContext({ ctx }: { ctx: EmailContextType }) {
  return (
    <div className="grid gap-2.5">
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13px]">
        <dt className="text-muted-foreground">from</dt>
        <dd className="m-0">
          <Mono className="text-[13px]">{ctx.from}</Mono>
        </dd>
        <dt className="text-muted-foreground">to</dt>
        <dd className="m-0">
          <Mono className="text-[13px]">{ctx.to}</Mono>
        </dd>
        <dt className="text-muted-foreground">when</dt>
        <dd className="m-0 text-muted-foreground">{relativeTime(ctx.when)}</dd>
      </dl>
      <pre className="m-0 whitespace-pre-wrap rounded-md border border-border bg-[var(--surface-lowest)] p-3.5 font-sans text-sm leading-relaxed">
        {ctx.body}
      </pre>
    </div>
  )
}
