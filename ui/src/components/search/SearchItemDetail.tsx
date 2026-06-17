import {
  GitPullRequestArrow,
  Mail,
  Calendar,
  MessageCircle,
  FileText,
  Search,
  Sparkles,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { SearchItem } from '@/lib/types/search'
import type { FunnelStage as FunnelStageType } from '@/lib/types/funnel'
import { relativeTime } from '@/lib/format'
import { itemLog, stageTimings } from '@/lib/funnel-helpers'
import { Mono } from '@/components/Mono'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from '@/components/ui/card'
import { StateDot } from '@/components/StateDot'
import { VerdictPill } from '@/components/VerdictPill'
import { FunnelStage } from '@/components/funnel/FunnelStage'
import { ItemContext } from './contextual/ItemContext'

const KIND_ICON: Record<string, LucideIcon> = {
  diff: GitPullRequestArrow,
  pr: GitPullRequestArrow,
  email: Mail,
  meeting: Calendar,
  chat: MessageCircle,
}

const PRIORITY_VARIANT: Record<string, 'p0' | 'p1' | 'p2' | 'p3'> = {
  P0: 'p0',
  P1: 'p1',
  P2: 'p2',
  P3: 'p3',
}

const CTX_LABEL: Record<string, string> = {
  diff: 'Diff',
  email: 'Message',
  meeting: 'Meeting',
  chat: 'Thread',
  pr: 'Pull request',
}

export type ItemAction = 'priority' | 'done' | 'snooze' | 'archive' | 'delete'

/**
 * SearchItemDetail — the detail panel for the selected search result. Shows
 * header, actions bar, LLM "Why this matters" summary, contextual payload,
 * processing log via FunnelStage, and current verdict.
 */
export function SearchItemDetail({
  item,
  onAction,
}: {
  item: SearchItem | null
  onAction: (itemId: number, action: ItemAction, value?: string) => void
}) {
  if (!item) {
    return (
      <div className="flex min-h-[360px] flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border text-muted-foreground">
        <Search size={22} />
        <p className="m-0 font-mono text-[13px]">
          // select an item to inspect its full processing log
        </p>
      </div>
    )
  }

  const Icon = KIND_ICON[item.kind] ?? FileText
  const ctxLabel = CTX_LABEL[item.kind] ?? 'Context'

  // Build processing log from item stages
  const log: FunnelStageType[] = itemLog({
    id: item.id,
    summary: item.summary,
    source: item.source,
    created_at: item.created_at,
    stages: item.stages,
    verdict: item.verdict,
  })
  const timings = stageTimings(log)
  const baseTime = item.created_at ? new Date(item.created_at).getTime() : null
  const enricherCount = log.filter((s) =>
    String(s.filterId).startsWith('en_'),
  ).length

  return (
    <div className="grid content-start gap-4">
      {/* header */}
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Icon size={15} className="text-[var(--brand)]" />
          <Mono className="text-xs text-muted-foreground">{item.id}</Mono>
          {item.priority && (
            <Badge variant={PRIORITY_VARIANT[item.priority] ?? 'p3'}>
              {item.priority}
            </Badge>
          )}
          <StateDot state={item.state} />
          <span className="font-mono text-[11px] text-muted-foreground">
            &middot; {item.source} &middot; {relativeTime(item.created_at)}
          </span>
        </div>
        <h2 className="text-xl font-semibold">{item.summary}</h2>
        {item.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {item.tags.map((t) => (
              <span
                key={t}
                className="rounded-sm border border-border px-1.5 py-px font-mono text-[11px] text-muted-foreground"
              >
                #{t}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* actions bar */}
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-card p-3">
        <span className="font-mono text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Actions
        </span>
        <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          priority
          <select
            aria-label="Set priority"
            value={item.priority ?? ''}
            onChange={(e) => onAction(item.id, 'priority', e.target.value)}
            className="h-7 rounded border border-border bg-transparent px-1.5 font-mono text-xs text-foreground"
          >
            <option value="">&mdash;</option>
            {['P0', 'P1', 'P2', 'P3'].map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <Button
          size="sm"
          onClick={() => onAction(item.id, 'done')}
        >
          Mark done
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onAction(item.id, 'snooze')}
        >
          Snooze 4h
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onAction(item.id, 'archive')}
        >
          Archive
        </Button>
        <Button
          size="sm"
          variant="destructive"
          className="ml-auto"
          onClick={() => onAction(item.id, 'delete')}
        >
          Delete
        </Button>
      </div>

      {/* LLM summary */}
      <div
        className="rounded-md p-4"
        style={{
          border:
            '1px solid color-mix(in srgb, var(--primary) 35%, var(--border))',
          background:
            'color-mix(in srgb, var(--primary) 7%, var(--card))',
        }}
      >
        <div className="mb-2 flex items-center gap-2">
          <Sparkles size={15} className="text-[var(--brand)]" />
          <h3 className="m-0 font-mono text-[13px] font-semibold uppercase tracking-wide">
            Why this matters to you
          </h3>
        </div>
        <p className="m-0 text-sm leading-relaxed">{item.llm_summary}</p>
      </div>

      {/* contextual payload */}
      <Card>
        <CardHeader divided className="px-4 py-3.5">
          <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {ctxLabel}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4">
          <ItemContext ctx={item.context} />
        </CardContent>
      </Card>

      {/* processing log */}
      <Card>
        <CardHeader divided className="px-4 py-3.5">
          <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Processing Log &middot; {enricherCount} enricher
            {enricherCount === 1 ? '' : 's'} + {log.length - enricherCount}{' '}
            filters
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4">
          {log.map((s, i) => (
            <FunnelStage
              key={i}
              stage={s}
              index={i}
              isLast={i === log.length - 1}
              item={{
                id: item.id,
                summary: item.summary,
                source: item.source,
                created_at: item.created_at,
                stages: item.stages,
                verdict: item.verdict,
              }}
              editable={!String(s.filterId).startsWith('en_')}
              timing={timings[i]}
              baseTime={baseTime}
            />
          ))}
          {/* current verdict */}
          <div
            className="mt-2 rounded-md p-3.5"
            style={{
              border:
                'solid 1px color-mix(in srgb, var(--primary) 30%, var(--border))',
              background:
                'color-mix(in srgb, var(--primary) 6%, var(--card))',
            }}
          >
            <div className="mb-2 flex items-center gap-2">
              <Sparkles size={14} className="text-[var(--brand)]" />
              <h3 className="m-0 text-[13px] font-semibold">Current verdict</h3>
              <span className="ml-auto">
                <VerdictPill verdict={item.verdict} />
              </span>
            </div>
            <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">
              {item.verdict.rationale}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
