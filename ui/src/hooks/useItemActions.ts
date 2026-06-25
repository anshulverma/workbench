// useItemActions.ts — the shared item lifecycle mutations (priority / done /
// snooze / archive) + toasts + cache invalidation, extracted from
// ItemDetailDialog so BOTH the dialog and the Search master/detail panel drive
// the same backend behavior. `onAfterDismiss` lets a caller react to actions
// that remove the item from view (done/archive): the dialog closes itself; the
// Search page advances the selection.

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, apiPost } from '@/lib/api'
import type { ItemAction } from '@/components/ItemDetailBody'

const errMsg = (err: unknown) =>
  err instanceof ApiError ? err.message : 'Unknown error'

export function useItemActions(opts?: { onAfterDismiss?: (id: number) => void }) {
  const qc = useQueryClient()

  // After any lifecycle action, refresh the detail (priority/status/log change)
  // plus every list/funnel that surfaces the item.
  const invalidate = (id: number) => {
    qc.invalidateQueries({ queryKey: ['item-detail', id] })
    qc.invalidateQueries({ queryKey: ['items-search'] })
    qc.invalidateQueries({ queryKey: ['search-items'] })
    qc.invalidateQueries({ queryKey: ['actions'] })
    qc.invalidateQueries({ queryKey: ['funnel'] })
  }

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
      opts?.onAfterDismiss?.(id)
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
      opts?.onAfterDismiss?.(id)
    },
    onError: (err) => toast.error(`Archive failed: ${errMsg(err)}`),
  })

  const onAction = (id: number, action: ItemAction, value?: string) => {
    switch (action) {
      case 'priority':
        if (value) priority.mutate({ id, value }) // blank "—" has no endpoint
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

  return { onAction }
}
