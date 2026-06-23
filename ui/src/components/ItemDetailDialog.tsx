import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError, apiPost } from '@/lib/api'
import { useItemDetail } from '@/hooks/useItemDetail'
import { useItemDialog } from '@/hooks/useItemDialog'
import { ItemDetailBody, type ItemAction } from './ItemDetailBody'
import { titleText } from './ItemTitle'

/** App-root item-detail popup. Driven entirely by the `?item=<id>` URL param. */
export function ItemDetailDialog() {
  const { itemId, closeItem } = useItemDialog()
  const q = useItemDetail(itemId)
  const qc = useQueryClient()

  // After any lifecycle action, refresh the popup (priority badge, status, and
  // the processing log all change) plus the lists/funnel that surface the item.
  const invalidate = (id: number) => {
    qc.invalidateQueries({ queryKey: ['item-detail', id] })
    qc.invalidateQueries({ queryKey: ['items-search'] })
    qc.invalidateQueries({ queryKey: ['search-items'] })
    qc.invalidateQueries({ queryKey: ['actions'] })
    qc.invalidateQueries({ queryKey: ['funnel'] })
  }

  const errMsg = (err: unknown) =>
    err instanceof ApiError ? err.message : 'Unknown error'

  const priority = useMutation({
    mutationFn: ({ id, value }: { id: number; value: string }) =>
      apiPost(`/api/actions/${id}/priority`, { priority: value }),
    onSuccess: (_d, { id, value }) => {
      invalidate(id)
      toast.success(`Priority set to ${value}`)
    },
    onError: (err) => toast.error(`Priority change failed: ${errMsg(err)}`),
  })

  const markDone = useMutation({
    mutationFn: (id: number) => apiPost(`/api/actions/${id}/done`),
    onSuccess: (_d, id) => {
      invalidate(id)
      toast.success('Marked done')
      closeItem()
    },
    onError: (err) => toast.error(`Mark done failed: ${errMsg(err)}`),
  })

  const snooze = useMutation({
    mutationFn: (id: number) => apiPost(`/api/actions/${id}/snooze`, { hours: 4 }),
    onSuccess: (_d, id) => {
      invalidate(id)
      toast.success('Snoozed 4h')
    },
    onError: (err) => toast.error(`Snooze failed: ${errMsg(err)}`),
  })

  const archive = useMutation({
    mutationFn: (id: number) => apiPost(`/api/actions/${id}/archive`),
    onSuccess: (_d, id) => {
      invalidate(id)
      toast.success('Item archived')
      closeItem()
    },
    onError: (err) => toast.error(`Archive failed: ${errMsg(err)}`),
  })

  const onAction = (id: number, action: ItemAction, value?: string) => {
    switch (action) {
      case 'priority':
        // The blank "—" option has no clear endpoint; ignore it.
        if (value) priority.mutate({ id, value })
        break
      case 'done':
        markDone.mutate(id)
        break
      case 'snooze':
        snooze.mutate(id)
        break
      default: // archive | delete → soft-archive
        archive.mutate(id)
    }
  }

  return (
    <Dialog open={itemId != null} onOpenChange={(o) => !o && closeItem()}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        {/* Accessible name for the dialog; the visible, formatted title is the
            <h2> rendered by ItemDetailBody. */}
        <DialogHeader className="sr-only">
          <DialogTitle>
            {q.data ? titleText(q.data.summary, q.data.kind) : `Item ${itemId}`}
          </DialogTitle>
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

// Re-exported for callers/tests that want the plain accessible title string.
export { titleText }
