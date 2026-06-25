// ItemDetailDialog — app-root item-detail popup, driven entirely by the
// `?item=<id>` URL param. Still used by every surface that deep-links an item
// (LiveTail, Action Items, etc.). The Search page now renders ItemDetailBody
// inline instead of routing through here; both share the same lifecycle
// mutations via useItemActions, so behavior is identical.

import { Link } from 'react-router-dom'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { useItemDetail } from '@/hooks/useItemDetail'
import { useItemDialog } from '@/hooks/useItemDialog'
import { useItemActions } from '@/hooks/useItemActions'
import { ItemDetailBody } from './ItemDetailBody'
import { titleText } from './ItemTitle'

/** App-root item-detail popup. Driven entirely by the `?item=<id>` URL param. */
export function ItemDetailDialog() {
  const { itemId, closeItem } = useItemDialog()
  const q = useItemDetail(itemId)
  // done/archive dismiss the item from view → close the popup.
  const { onAction } = useItemActions({ onAfterDismiss: () => closeItem() })

  return (
    <Dialog open={itemId != null} onOpenChange={(o) => !o && closeItem()}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        {/* Accessible name for the dialog; the visible, formatted title is the
            heading rendered by ItemDetailBody. */}
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
