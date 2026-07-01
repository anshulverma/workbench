// Triage Card Detail View (#/triage/:cardId). Renders the structured diff
// card_content client-side: metadata + summary always visible, risk + why-care
// expanded, hunks via DiffHunks, a prominent View in Phabricator link, and
// reuses useTriage respond/confirm. Read-only when responded/expired. When a
// re-triage change section is present, a "What changed" callout leads (ADR 0032).
import { Link, useParams } from 'react-router-dom'
import { useTriageCard } from '@/hooks/useTriageCard'
import { useRespond } from '@/hooks/useTriage'
import { DiffHunks, type Hunk } from '@/components/DiffHunks'
import { ItemLink } from '@/components/ItemLink'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { sourceLabel } from '@/lib/source'

export function TriageDetail() {
  const { cardId = '' } = useParams()
  const card = useTriageCard(cardId)
  const respond = useRespond()

  if (card.isPending) {
    return (
      <div data-testid="detail-loading" className="space-y-3 p-2">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (card.isError) {
    const err = card.error as ApiError
    if (err.status === 401) {
      return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    }
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load card: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  const c = card.data
  const sections = (c.card_content.sections ?? {}) as Record<string, unknown>
  const metadata = (sections.metadata ?? {}) as { author?: string; team?: string; status?: string }
  const risk = (sections.risk ?? {}) as { factors?: string[]; watch_outs?: string[] }
  const hunks = (sections.hunks ?? []) as Hunk[]
  const diffUrl = (sections.diff_url as string | undefined) ?? undefined
  // Universal source identity (any source type). The diff-specific "View in
  // Phabricator" button (diffUrl) takes precedence for diffs; this generic
  // link covers tasks and every other source that carries a source_url.
  const sourceType = c.card_content.source_type
  const sourceRef = c.card_content.source_ref
  const sourceUrl = c.card_content.source_url
  const summary = (sections.summary as string) ?? c.card_content.summary ?? '(no summary)'
  const whyCare = (sections.why_care as string) ?? ''
  const change = (sections.change as string | undefined) ?? undefined
  const itemPath = (c.card_content.path ?? c.card_content.item_path) as string | undefined
  const readOnly = c.status === 'responded' || c.status === 'expired'

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <h1 className="text-lg font-semibold">{summary}</h1>
        <div className="flex shrink-0 items-center gap-2">
          <Badge variant="outline" data-testid="source-type-badge" className="uppercase">
            {sourceLabel(sourceType)}
          </Badge>
          {typeof c.relevance_score === 'number' && (
            <Badge variant="secondary">relevance {c.relevance_score}</Badge>
          )}
        </div>
      </div>

      {change && (
        <section className="rounded border border-amber-700/40 bg-amber-950/20 p-3">
          <h2 className="font-medium">What changed since last triage</h2>
          <p className="text-sm">{change}</p>
        </section>
      )}

      <div className="text-sm text-muted-foreground">
        by {metadata.author ?? '?'}
        {metadata.team ? ` (${metadata.team})` : ''} — {metadata.status ?? ''}
      </div>

      {/* Item lineage link — presence-gated (Task 14): the card payload does not
          yet carry the lineage path, so this renders nothing today and lights up
          automatically once the card endpoint resolves the item's path field (also
          tolerant of the legacy item_path field name for backend flexibility). */}
      {c.item_id ? (
        <ItemLink id={c.item_id} className="text-xs">
          #{c.item_id}
        </ItemLink>
      ) : (
        itemPath && (
          <Link
            to={`/items/${itemPath}`}
            className="font-mono text-xs text-primary hover:underline"
          >
            #{itemPath}
          </Link>
        )
      )}

      {diffUrl ? (
        <a
          href={diffUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-block rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground"
        >
          View in Phabricator
        </a>
      ) : (
        sourceUrl && (
          <a
            data-testid="source-link"
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground"
          >
            Open {sourceRef ?? 'in source'} ↗
          </a>
        )
      )}

      <section>
        <h2 className="font-medium">Risk Factors</h2>
        <ul className="list-disc pl-5 text-sm">
          {(risk.factors ?? []).map((f, i) => <li key={`f${i}`}>{f}</li>)}
          {(risk.watch_outs ?? []).map((w, i) => <li key={`w${i}`}>⚠ {w}</li>)}
        </ul>
      </section>

      {whyCare && (
        <section>
          <h2 className="font-medium">Why it matters</h2>
          <p className="text-sm">{whyCare}</p>
        </section>
      )}

      <section>
        <h2 className="font-medium">Changes</h2>
        <DiffHunks hunks={hunks} maxHunks={15} />
      </section>

      {!readOnly && (
        <div className="flex flex-wrap gap-2">
          {c.options.map((o, i) => (
            <Button
              key={`${o.action}-${i}`}
              variant="outline"
              disabled={respond.isPending}
              onClick={() => respond.mutate({ card_id: c.id, choice: i + 1 })}
            >
              {i + 1}. {o.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  )
}
