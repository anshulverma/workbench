// AddRuleDialog — new filter creation form with LLM disclaimer.
//
// Uses Radix Dialog (via shadcn) for accessible modal behavior.
// Fields: prompt (textarea), action (select), source (select).
// LLM disclaimer explains that the noise filter matches patterns
// with the LLM, not regex.

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

export interface AddRuleInput {
  prompt: string
  action: string
  sources: string[]
}

export interface AddRuleDialogProps {
  open: boolean
  onClose: () => void
  onCreate: (input: AddRuleInput) => void
}

export function AddRuleDialog({
  open,
  onClose,
  onCreate,
}: AddRuleDialogProps) {
  const [prompt, setPrompt] = useState('')
  const [action, setAction] = useState('drop')
  const [source, setSource] = useState('github')

  useEffect(() => {
    if (open) {
      setPrompt('')
      setAction('drop')
      setSource('github')
    }
  }, [open])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!prompt.trim()) return
    onCreate({
      prompt: prompt.trim(),
      action,
      sources:
        source === 'all'
          ? ['github', 'email', 'calendar', 'chat']
          : [source],
    })
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New Filter Rule</DialogTitle>
          <DialogDescription>
            Describe the pattern in plain language — the noise filter matches
            it with the LLM, not regex. New rules are added at the end of the
            order.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} style={{ display: 'grid', gap: 14 }}>
          <label style={{ display: 'grid', gap: 6, fontSize: 13 }}>
            <span style={{ color: 'var(--muted-foreground)' }}>Prompt</span>
            <textarea
              className="wb-textarea flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              rows={3}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. Drop receipts and order confirmations"
              autoFocus
              data-testid="add-rule-prompt"
            />
          </label>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 12,
            }}
          >
            <label style={{ display: 'grid', gap: 6, fontSize: 13 }}>
              <span style={{ color: 'var(--muted-foreground)' }}>Action</span>
              <select
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                value={action}
                onChange={(e) => setAction(e.target.value)}
                data-testid="add-rule-action"
              >
                <option value="drop">Auto-drop</option>
                <option value="include">Auto-include</option>
                <option value="label">Label</option>
              </select>
            </label>

            <label style={{ display: 'grid', gap: 6, fontSize: 13 }}>
              <span style={{ color: 'var(--muted-foreground)' }}>Source</span>
              <select
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                value={source}
                onChange={(e) => setSource(e.target.value)}
                data-testid="add-rule-source"
              >
                {['github', 'email', 'calendar', 'chat', 'all'].map((s) => (
                  <option key={s} value={s}>
                    {s === 'all' ? 'All sources' : s}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" data-testid="add-rule-submit">
              Create rule
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
