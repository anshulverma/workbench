// Triage page — web-native triage of pending cards (spec Design Section 2.2).
//
// Lists pending Triage Cards from GET /api/triage/pending. Each card renders its
// `card_content` summary, a relevance badge, numbered option buttons (1..n), and
// a free-text input. Numbered choices POST {card_id, choice}; free-text POSTs
// {card_id, raw_text}. A destructive free-text response returns
// status:"awaiting_confirmation" with an explanation, which opens a confirm/
// cancel Dialog that drives POST /api/triage/confirm. A 409 (card already
// answered on the messenger or another tab) surfaces a friendly toast + refetch
// via the hook.
//
// Card content is rendered as plain text only — never dangerouslySetInnerHTML.
//
// Implements the five UI states: loading / error (with X-Request-ID) /
// unauthorized / empty ("Inbox zero") / normal.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useTriagePending,
  useRespond,
  useConfirm,
  type TriageCard,
} from '@/hooks/useTriage'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ApiError } from '@/lib/api'

function TriageCardItem({ card }: { card: TriageCard }) {
  const respond = useRespond()
  const confirm = useConfirm()
  const [text, setText] = useState('')
  const [pending, setPending] = useState<{ explanation: string } | null>(null)

  const summary = card.card_content?.summary ?? '(no summary)'
  const busy = respond.isPending || confirm.isPending

  const sendFreeText = async () => {
    const trimmed = text.trim()
    if (!trimmed) return
    try {
      const res = await respond.mutateAsync({ card_id: card.id, raw_text: trimmed })
      if (res.status === 'awaiting_confirmation') {
        setPending({ explanation: res.explanation ?? 'This action needs confirmation.' })
      } else {
        setText('')
      }
    } catch {
      /* toast handled by the mutation's onError */
    }
  }

  const closeConfirm = () => setPending(null)

  const onConfirm = (value: boolean) => {
    confirm.mutate({ card_id: card.id, confirm: value })
    setPending(null)
    setText('')
  }

  return (
    <div className="space-y-3 rounded border border-border p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium">{summary}</p>
        {typeof card.relevance_score === 'number' && (
          <Badge variant="secondary" className="shrink-0">
            relevance {card.relevance_score}
          </Badge>
        )}
        <Link to={`/triage/${card.id}`} className="shrink-0 text-sm underline">
          Review
        </Link>
      </div>

      <div className="flex flex-wrap gap-2">
        {card.options.map((o, i) => (
          <Button
            key={`${o.action}-${i}`}
            variant="outline"
            disabled={busy}
            onClick={() => respond.mutate({ card_id: card.id, choice: i + 1 })}
          >
            {i + 1}. {o.label}
          </Button>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          aria-label="free-text response"
          placeholder="Or reply in your own words…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void sendFreeText()
            }
          }}
          disabled={busy}
          className="flex-1 rounded border border-border bg-background p-2"
        />
        <Button onClick={() => void sendFreeText()} disabled={!text.trim() || busy}>
          Send
        </Button>
      </div>

      <Dialog open={pending !== null} onOpenChange={(o) => !o && closeConfirm()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm action</DialogTitle>
            <DialogDescription>
              This looks like a destructive action. Confirm to proceed.
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm">{pending?.explanation}</p>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={confirm.isPending}
              onClick={() => onConfirm(false)}
            >
              Cancel
            </Button>
            <Button disabled={confirm.isPending} onClick={() => onConfirm(true)}>
              Confirm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export function Triage() {
  const pending = useTriagePending()

  if (pending.isPending) {
    return (
      <div data-testid="triage-loading" className="space-y-3 p-2">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (pending.isError) {
    const err = pending.error as ApiError
    if (err.status === 401) {
      return (
        <div role="alert" className="p-6">
          token unavailable; check tunnel/binding
        </div>
      )
    }
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load triage: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  if (pending.data.length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold">Triage</h1>
        <EmptyState message="Inbox zero — no cards awaiting triage" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Triage</h1>
      <div className="space-y-4">
        {pending.data.map((c) => (
          <TriageCardItem key={c.id} card={c} />
        ))}
      </div>
    </div>
  )
}
