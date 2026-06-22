import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { useItemDetail } from '@/hooks/useItemDetail'
import { useItemDialog } from '@/hooks/useItemDialog'
import { useItemActions, useSnoozeItem } from '@/hooks/useSearchItems'
import { ItemDetailBody, type ItemAction } from './ItemDetailBody'

/** App-root item-detail popup. Driven entirely by the `?item=<id>` URL param. */
export function ItemDetailDialog() {
  const { itemId, closeItem } = useItemDialog()
  const q = useItemDetail(itemId)
  const { archive } = useItemActions()
  const snooze = useSnoozeItem()

  const onAction = (id: number, action: ItemAction, value?: string) => {
    switch (action) {
      case 'priority':
        toast.success(`Set ${id} → ${value || '—'}`)
        break
      case 'snooze':
        snooze.mutate({ itemId: id, durationMinutes: 240 })
        break
      default:
        archive.mutate(id) // done | archive | delete → soft-archive
    }
  }

  return (
    <Dialog open={itemId != null} onOpenChange={(o) => !o && closeItem()}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Item {itemId}</DialogTitle>
        </DialogHeader>
        {q.isPending && (
          <div className="grid gap-3" data-testid="item-detail-loading">
            <Skeleton className="h-7 w-48" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}
        {q.isError && (
          <div role="alert" className="p-2 text-destructive">
            {q.error instanceof ApiError && q.error.status === 404
              ? 'Item not found'
              : `Failed to load item: ${q.error instanceof ApiError ? q.error.message : 'Unknown error'}`}
          </div>
        )}
        {q.data && (
          <>
            <ItemDetailBody item={q.data} onAction={onAction} />
            {q.data.path && (
              <Link
                to={`/items/${q.data.path}`}
                onClick={closeItem}
                className="text-xs text-primary hover:underline"
              >
                open full page ↗
              </Link>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
