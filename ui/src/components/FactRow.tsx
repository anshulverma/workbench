// A single preference fact table row with Fact Curation controls (spec §12).
//
// Renders a <tr> with: source pill (Badge; "unknown" when empty), content,
// created date (Fact.timestamp; em-dash when null), and Edit/Delete actions.
// Edit opens a Dialog with a content textarea (rendered as plain text — never
// dangerouslySetInnerHTML); Save calls PATCH /api/memory/facts/{id}. Delete is
// behind a confirm Dialog calling DELETE /api/memory/facts/{id}. When the memory
// layer is noop the curation actions are disabled (the calls would 501); a stray
// 501 is still handled gracefully by the mutation's friendly toast. Dialog
// content is portalled to <body>, so it stays valid table markup.

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Mono } from '@/components/Mono'
import { TableCell, TableRow } from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useDeleteFact, useUpdateFact, type Fact } from '@/hooks/useFacts'

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toISOString().slice(0, 10)
}

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
    <TableRow className="border-b border-border">
      <TableCell className="align-top">
        <Badge variant="secondary">{fact.source || 'unknown'}</Badge>
      </TableCell>
      {/* Plain text only — fact content is never rendered as HTML. */}
      <TableCell className="whitespace-pre-wrap break-words">
        {fact.content}
      </TableCell>
      <TableCell className="align-top whitespace-nowrap">
        <Mono className="text-xs text-muted-foreground">
          {formatDate(fact.timestamp)}
        </Mono>
      </TableCell>
      <TableCell className="align-top text-right">
        <div className="flex justify-end gap-2">
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
        </div>

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
      </TableCell>
    </TableRow>
  )
}
