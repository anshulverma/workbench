import type { ReactNode } from 'react'

export function EmptyState({ message, cta }: { message: string; cta?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-10 text-muted-foreground">
      <p>{message}</p>
      {cta}
    </div>
  )
}
