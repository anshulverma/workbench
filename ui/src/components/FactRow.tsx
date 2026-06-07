// A single preference fact row with Fact Curation controls (spec 2.7).
//
// Edit opens a Dialog with a content textarea (rendered as plain text — never
// dangerouslySetInnerHTML); Save calls PATCH /api/memory/facts/{id}. Delete is
// behind a confirm Dialog calling DELETE /api/memory/facts/{id}. When the memory
// layer is noop the curation actions are disabled (the calls would 501); a stray
// 501 is still handled gracefully by the mutation's friendly toast.

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useDeleteFact, useUpdateFact, type Fact } from '@/hooks/useFacts'

export function FactRow({
  fact,
  disabled = false,
}: {
  fact: Fact
  disabled?: boolean
}) {
  const del = useDeleteFact()
  const upd = useUpdateFact()
  const [editing, setEditing] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [editValue, setEditValue] = useState(fact.content)

  // Re-seed the textarea whenever the dialog opens (or the underlying fact
  // changes after a refetch).
  useEffect(() => {
    if (editing) setEditValue(fact.content)
  }, [editing, fact.content])

  return (
    <li className="flex items-center gap-3 border-b border-border py-2 text-sm">
      {/* Plain text only — fact content is never rendered as HTML. */}
      <span className="flex-1 whitespace-pre-wrap break-words">
        {fact.content}
      </span>
      <span className="shrink-0 text-xs text-muted-foreground">
        {fact.source}
      </span>
      <Button
        variant="outline"
        size="sm"
        aria-label={`Edit ${fact.id}`}
        disabled={disabled}
        onClick={() => setEditing(true)}
      >
        Edit
      </Button>
      <Button
        variant="destructive"
        size="sm"
        aria-label={`Delete ${fact.id}`}
        disabled={disabled}
        onClick={() => setConfirmingDelete(true)}
      >
        Delete
      </Button>

      <Dialog open={editing} onOpenChange={setEditing}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit fact</DialogTitle>
            <DialogDescription>
              Update the learned preference fact. Saved to the memory layer.
            </DialogDescription>
          </DialogHeader>
          <textarea
            aria-label={`Content for ${fact.id}`}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            rows={4}
            className="w-full rounded border border-border bg-background p-2"
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button
              disabled={upd.isPending}
              onClick={() => {
                upd.mutate(
                  { id: fact.id, content: editValue },
                  { onSuccess: () => setEditing(false) },
                )
              }}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmingDelete} onOpenChange={setConfirmingDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this fact?</DialogTitle>
            <DialogDescription>
              This removes the learned preference fact from the memory layer.
              This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmingDelete(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={del.isPending}
              onClick={() => {
                del.mutate(fact.id, {
                  onSuccess: () => setConfirmingDelete(false),
                })
              }}
            >
              Confirm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  )
}
