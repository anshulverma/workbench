// Triage page — combined 3-column shell (variant A) + keyboard cards (variant B).
// Spec §9 / ADR0043 (three-column layout) / ADR0027 (interaction stays text replies).
//
// LEFT filter rail: Sources checkboxes (+counts) derived from
// card_content.source_type, Priority filter, and a Time-Window quad
// (1H/24H/7D/ALL) keyed off card.created_at. ALL filtering is client-side
// (useMemo) over the fetched pending cards — no new endpoint.
//
// CENTER keyboard card feed (variant B): each card = priority/relevance colored
// left border, Item ID + relevance score, summary, numbered [1][2][3] option
// buttons, a free-text reply input ("Press Enter"), and J/K navigation. The
// ADR0027 text-reply interaction is preserved: numbered buttons POST the same
// {card_id, choice}; free-text POSTs {card_id, raw_text}; a destructive
// free-text response opens the confirm/cancel Dialog driving POST /confirm.
//
// RIGHT analytics column: Signal Velocity sparkline + Automation Stats
// (auto_resolved_pct, avg_triage_seconds, "n/a" on null) + an LLM Insight panel
// that renders ONLY when the active card carries a real per-option
// suggestion_reason (no static/fake copy).
//
// Card content is rendered as plain text only — never dangerouslySetInnerHTML.
// Five UI states preserved: loading / error (X-Request-ID) / unauthorized /
// empty ("Inbox zero / System Harmony") / normal, plus a distinct
// "no cards match filters" empty state for the filtered subset.
//
// Render-loop guardrail (ADR0043 post-mortem): `filtered` is a useMemo over
// STABLE inputs (the query data + filter state Sets held in useState, which only
// change on user action). The active-index clamp effect depends ONLY on the
// primitive `filtered.length`. The J/K global keydown effect has an empty
// dependency array and uses functional setState + a length ref, so it never
// re-binds and never re-sets state during render.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useTriagePending,
  useRespond,
  useConfirm,
  type TriageCard,
} from '@/hooks/useTriage'
import { useMetricsTimeseries, useStatsOverview } from '@/hooks/useStats'
import { EmptyState } from '@/components/EmptyState'
import { Sparkline } from '@/components/Sparkline'
import { Mono } from '@/components/Mono'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'

const PRIORITY_VARIANT: Record<string, 'p0' | 'p1' | 'p2' | 'p3'> = {
  P0: 'p0',
  P1: 'p1',
  P2: 'p2',
  P3: 'p3',
}

// Priority/relevance colored left-border (variant B). Falls back to a
// relevance-derived tier when the card has no explicit priority.
function borderClass(card: TriageCard): string {
  const prio = card.card_content?.priority
  if (prio === 'P0') return 'border-l-[#ffb4ab]'
  if (prio === 'P1') return 'border-l-[#ff6a2b]'
  if (prio === 'P2') return 'border-l-[#71d2ff]'
  if (prio === 'P3') return 'border-l-border'
  const r = card.relevance_score ?? 0
  if (r >= 80) return 'border-l-[#ff6a2b]'
  if (r >= 50) return 'border-l-[#71d2ff]'
  return 'border-l-border'
}

type TimeWindow = '1H' | '24H' | '7D' | 'ALL'
const WINDOW_MS: Record<Exclude<TimeWindow, 'ALL'>, number> = {
  '1H': 3_600_000,
  '24H': 24 * 3_600_000,
  '7D': 7 * 24 * 3_600_000,
}

/** Render a 0..1 ratio as a whole-number percent, or "n/a" when null. */
function pct(value: number | null | undefined): string {
  return value == null ? 'n/a' : `${Math.round(value * 100)}%`
}

/** Render a seconds metric compactly, or "n/a" when null. */
function secs(value: number | null | undefined): string {
  return value == null ? 'n/a' : `${Math.round(value)}s`
}

function TriageCardItem({
  card,
  active,
}: {
  card: TriageCard
  active: boolean
}) {
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
    <div
      data-testid="triage-card"
      data-active={active}
      className={cn(
        'space-y-3 rounded border border-l-4 border-border p-4',
        borderClass(card),
        active && 'ring-2 ring-ring',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <Mono className="text-xs text-muted-foreground">{card.id}</Mono>
            {typeof card.relevance_score === 'number' && (
              <Badge variant="secondary" className="shrink-0">
                relevance {card.relevance_score}
              </Badge>
            )}
            {card.card_content?.priority && (
              <Badge variant={PRIORITY_VARIANT[card.card_content.priority] ?? 'p3'}>
                {card.card_content.priority}
              </Badge>
            )}
          </div>
          <p className="font-medium">{summary}</p>
        </div>
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
            [{i + 1}] {o.label}
          </Button>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          aria-label="free-text response"
          placeholder="Reply in your own words… (Press Enter)"
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

// --- Right analytics column (spec §9). Each widget fails soft inline. ---

function SignalVelocityPanel() {
  const series = useMetricsTimeseries('signal_velocity', 24, 'hour')
  const total = series.data?.reduce((s, p) => s + p.count, 0)
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Signal Velocity (24h)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {series.isPending ? (
          <Skeleton className="h-8" />
        ) : series.isError ? (
          <p className="font-mono text-xs text-muted-foreground">n/a</p>
        ) : (
          <>
            <Mono className="text-lg font-bold">{total ?? '—'}</Mono>
            <Sparkline data={series.data ?? []} />
          </>
        )}
      </CardContent>
    </Card>
  )
}

function AutomationStatsPanel() {
  const overview = useStatsOverview()
  const m = overview.data?.metrics
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Automation Stats
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {overview.isPending ? (
          <Skeleton className="h-12" />
        ) : (
          <>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Auto-resolved</span>
              <Mono>{overview.isError ? 'n/a' : pct(m?.auto_resolved_pct)}</Mono>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Avg triage</span>
              <Mono>{overview.isError ? 'n/a' : secs(m?.avg_triage_seconds)}</Mono>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

// LLM Insight is data-backed: render ONLY when the active card has at least one
// option carrying a real suggestion_reason (no static/fake panel). Surfaces the
// card-level confidence_score when present.
function LlmInsightPanel({ card }: { card: TriageCard | undefined }) {
  const backed = card?.options.filter((o) => o.suggestion_reason) ?? []
  if (!card || backed.length === 0) return null
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
          LLM Insight
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {typeof card.confidence_score === 'number' && (
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Confidence</span>
            <Mono>{card.confidence_score}%</Mono>
          </div>
        )}
        <ul className="space-y-2">
          {backed.map((o, i) => (
            <li key={`${o.action}-${i}`} className="space-y-0.5">
              <span className="font-medium">{o.label}</span>
              <p className="text-muted-foreground">{o.suggestion_reason}</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

export function Triage() {
  const pending = useTriagePending()

  // Filter state. An EMPTY selection Set means "no filter" (all sources /
  // priorities pass) — this avoids any effect that re-initializes selection
  // from the fetched data on every render (render-loop guardrail).
  const [excludedSources, setExcludedSources] = useState<Set<string>>(new Set())
  const [excludedPriorities, setExcludedPriorities] = useState<Set<string>>(new Set())
  const [timeWindow, setTimeWindow] = useState<TimeWindow>('ALL')
  const [activeIdx, setActiveIdx] = useState(0)

  const cards = pending.data ?? []

  // Available source facets with counts, derived (useMemo) from the fetched
  // cards over the STABLE `cards` reference.
  const sourceFacets = useMemo(() => {
    const counts = new Map<string, number>()
    for (const c of cards) {
      const s = c.card_content?.source_type ?? 'unknown'
      counts.set(s, (counts.get(s) ?? 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [cards])

  const priorityFacets = useMemo(() => {
    const counts = new Map<string, number>()
    for (const c of cards) {
      const p = c.card_content?.priority
      if (p) counts.set(p, (counts.get(p) ?? 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [cards])

  // Client-side filtered feed — derived during render via useMemo over STABLE
  // inputs only (query data + filter-state Sets held in useState).
  const filtered = useMemo(() => {
    const cutoff =
      timeWindow === 'ALL' ? null : Date.now() - WINDOW_MS[timeWindow]
    return cards.filter((c) => {
      const src = c.card_content?.source_type ?? 'unknown'
      if (excludedSources.has(src)) return false
      const prio = c.card_content?.priority
      if (prio && excludedPriorities.has(prio)) return false
      if (cutoff !== null) {
        if (!c.created_at) return false
        if (new Date(c.created_at).getTime() < cutoff) return false
      }
      return true
    })
  }, [cards, excludedSources, excludedPriorities, timeWindow])

  // Clamp the active index whenever the filtered length changes. Depends ONLY
  // on the primitive `filtered.length` (never on the `filtered` array identity)
  // to avoid an infinite render loop.
  useEffect(() => {
    setActiveIdx((i) => (filtered.length === 0 ? 0 : Math.min(i, filtered.length - 1)))
  }, [filtered.length])

  // J/K keyboard navigation. The effect has an EMPTY dependency array so it
  // binds exactly once; it reads the current length from a ref and updates the
  // index with functional setState, so it never depends on unstable values.
  const lenRef = useRef(0)
  lenRef.current = filtered.length
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      // Don't hijack J/K while typing into the free-text reply.
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.key === 'j' || e.key === 'J') {
        e.preventDefault()
        setActiveIdx((i) => Math.min(i + 1, Math.max(0, lenRef.current - 1)))
      } else if (e.key === 'k' || e.key === 'K') {
        e.preventDefault()
        setActiveIdx((i) => Math.max(i - 1, 0))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const hasFilters =
    excludedSources.size > 0 || excludedPriorities.size > 0 || timeWindow !== 'ALL'
  const clearFilters = () => {
    setExcludedSources(new Set())
    setExcludedPriorities(new Set())
    setTimeWindow('ALL')
  }

  const toggle = (
    setter: React.Dispatch<React.SetStateAction<Set<string>>>,
    key: string,
  ) =>
    setter((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

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

  // Empty state #1: no pending cards at all → "Inbox zero / System Harmony".
  if (cards.length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold">Triage</h1>
        <EmptyState message="Inbox zero — System Harmony. No cards awaiting triage." />
      </div>
    )
  }

  const activeCard = filtered[activeIdx]

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Triage</h1>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[14rem_minmax(0,1fr)_16rem]">
        {/* LEFT: filter rail */}
        <aside aria-label="Triage filters" className="space-y-6">
          <section className="space-y-2">
            <h2 className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Sources
            </h2>
            <ul className="space-y-1">
              {sourceFacets.map(([src, count]) => (
                <li key={src}>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      aria-label={src}
                      checked={!excludedSources.has(src)}
                      onChange={() => toggle(setExcludedSources, src)}
                    />
                    <span className="flex-1">{src}</span>
                    <Mono className="text-xs text-muted-foreground">{count}</Mono>
                  </label>
                </li>
              ))}
            </ul>
          </section>

          {priorityFacets.length > 0 && (
            <section className="space-y-2">
              <h2 className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Priority
              </h2>
              <ul className="space-y-1">
                {priorityFacets.map(([prio, count]) => (
                  <li key={prio}>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        aria-label={prio}
                        checked={!excludedPriorities.has(prio)}
                        onChange={() => toggle(setExcludedPriorities, prio)}
                      />
                      <span className="flex-1">{prio}</span>
                      <Mono className="text-xs text-muted-foreground">{count}</Mono>
                    </label>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="space-y-2">
            <h2 className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Time Window
            </h2>
            <div className="flex flex-wrap gap-1">
              {(['1H', '24H', '7D', 'ALL'] as TimeWindow[]).map((w) => (
                <Button
                  key={w}
                  size="sm"
                  variant={timeWindow === w ? 'default' : 'outline'}
                  aria-pressed={timeWindow === w}
                  onClick={() => setTimeWindow(w)}
                >
                  {w}
                </Button>
              ))}
            </div>
          </section>

          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              Clear filters
            </Button>
          )}
        </aside>

        {/* CENTER: keyboard card feed */}
        <main aria-label="Triage cards" className="space-y-4">
          {filtered.length === 0 ? (
            <EmptyState message="No cards match filters" />
          ) : (
            filtered.map((c, i) => (
              <TriageCardItem key={c.id} card={c} active={i === activeIdx} />
            ))
          )}
        </main>

        {/* RIGHT: analytics column */}
        <aside aria-label="Triage analytics" className="space-y-4">
          <SignalVelocityPanel />
          <AutomationStatsPanel />
          <LlmInsightPanel card={activeCard} />
        </aside>
      </div>
    </div>
  )
}
