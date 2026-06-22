import type { ReactNode } from 'react'
import { useItemDialog } from '@/hooks/useItemDialog'
import { cn } from '@/lib/utils'

/** A clickable item reference that opens the item-detail dialog by id (no navigation). */
export function ItemLink({
  id,
  children,
  className,
}: {
  id: number
  children: ReactNode
  className?: string
}) {
  const { openItem } = useItemDialog()
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        openItem(id)
      }}
      className={cn('font-mono text-primary hover:underline', className)}
    >
      {children}
    </button>
  )
}
