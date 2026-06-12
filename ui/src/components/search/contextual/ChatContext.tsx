import type { ChatContext as ChatContextType } from '@/lib/types/search'
import { Mono } from '@/components/Mono'
import { relativeTime } from '@/lib/format'

/**
 * ChatContext — contextual payload renderer for chat items.
 * Shows the channel name and a threaded list of messages.
 */
export function ChatContext({ ctx }: { ctx: ChatContextType }) {
  return (
    <div className="grid gap-2">
      <Mono className="text-xs text-[var(--tertiary)]">{ctx.channel}</Mono>
      <div className="grid gap-2">
        {ctx.messages.map((msg, i) => (
          <div
            key={i}
            className="grid grid-cols-[auto_1fr] items-baseline gap-2.5"
          >
            <Mono className="whitespace-nowrap text-xs text-[var(--brand)]">
              {msg.who}
            </Mono>
            <div>
              <span className="text-sm leading-snug">{msg.text}</span>
              <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                {relativeTime(msg.when)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
