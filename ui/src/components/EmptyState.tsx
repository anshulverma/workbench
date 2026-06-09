import type { ReactNode } from 'react'

/**
 * EmptyState — a centered "terminal" empty surface (spec §5). Keeps the
 * {message, cta} public API and adds a mono `// End of feed` footer line for
 * the mission-control terminal aesthetic.
 */
export function EmptyState({ message, cta }: { message: string; cta?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-10 text-muted-foreground">
      <p>{message}</p>
      {cta}
      <p className="font-mono text-xs text-muted-foreground">// End of feed</p>
    </div>
  )
}
