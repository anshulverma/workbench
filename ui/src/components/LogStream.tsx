import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'

export interface LogLine {
  id: string
  text: string
}

/**
 * LogStream — a mono, auto-scrolling terminal log pane (spec §5, §11).
 *
 * Accepts log lines via either `lines` or its alias `entries`. Renders a
 * fixed-height scroll region (`role="log"`, `aria-live="polite"`) that pins to
 * the bottom as new lines arrive — auto-scroll is gated by
 * `prefers-reduced-motion`. An empty stream shows a `// no activity` terminal
 * line.
 */
export function LogStream({
  lines,
  entries,
  className,
  height = 240,
}: {
  lines?: LogLine[]
  entries?: LogLine[]
  className?: string
  height?: number
}) {
  const data = lines ?? entries ?? []
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (typeof el.scrollTo === 'function') {
      el.scrollTo({
        top: el.scrollHeight,
        behavior: reduced ? 'auto' : 'smooth',
      })
    } else {
      // jsdom / older engines lack scrollTo; fall back to setting scrollTop.
      el.scrollTop = el.scrollHeight
    }
  }, [data.length])

  return (
    <div
      ref={ref}
      data-logstream
      role="log"
      aria-live="polite"
      className={cn(
        'overflow-y-auto rounded-md border border-border bg-[#0e0e11] p-3 font-mono text-[13px] leading-relaxed text-foreground',
        className,
      )}
      style={{ height }}
    >
      {data.length === 0 ? (
        <p className="text-muted-foreground">// no activity</p>
      ) : (
        data.map((line) => (
          <p key={line.id} className="whitespace-pre-wrap break-words">
            {line.text}
          </p>
        ))
      )}
    </div>
  )
}
