// Filters page — interleaved enricher/filter/loopback cards in reorderable
// funnel order, with detail dialogs and a funnel output table at the bottom.
//
// Exported as both `Filters` (default) and named `IngestionFunnel` for
// embedding in the Ingestion page.

import { useState, useMemo, useCallback } from 'react'
import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type {
  FilterRuleExtended,
  Enricher,
  FunnelItem,
  FunnelOrderEntry,
} from '@/lib/types/funnel'
import { SRC_ICON } from '@/lib/funnel-constants'
import { ActionChip } from '@/components/ActionChip'
import { VerdictPill } from '@/components/VerdictPill'
import { SectionHeader } from '@/components/SectionHeader'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { FilterRuleCard } from '@/components/funnel/FilterRuleCard'
import { FilterDetailDialog } from '@/components/funnel/FilterDetailDialog'
import { EnricherCard } from '@/components/funnel/EnricherCard'
import { EnricherDetailDialog } from '@/components/funnel/EnricherDetailDialog'
import { LoopBackCard } from '@/components/funnel/LoopBackCard'
import { AddRuleDialog } from '@/components/funnel/AddRuleDialog'
import { ItemFunnelDialog } from '@/components/funnel/ItemFunnelDialog'
import { useFeedbackStore } from '@/hooks/useFeedback'
import {
  useFilterRules,
  useEnrichers,
  useLoopbacks,
  useFunnelItems,
  useFunnelOrder,
  useUpdateFunnelOrder,
  useToggleFunnelStage,
  useEnrichmentSamples,
  useCreateFilterRule,
  useDeleteFilterRule,
} from '@/hooks/useFunnel'
import { ApiError } from '@/lib/api'

function getIcon(name: string): LucideIcon | undefined {
  return (Icons as unknown as Record<string, LucideIcon>)[name]
}

function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401
}

export interface FiltersProps {
  embedded?: boolean
}

export function Filters({ embedded: _embedded }: FiltersProps) {
  const fb = useFeedbackStore()

  // ---- Data queries ----
  const filterRulesQ = useFilterRules()
  const enrichersQ = useEnrichers()
  const loopbacksQ = useLoopbacks()
  const funnelItemsQ = useFunnelItems()
  const funnelOrderQ = useFunnelOrder()
  const enrichmentSamplesQ = useEnrichmentSamples()

  // ---- Mutations ----
  const updateOrder = useUpdateFunnelOrder()
  const toggleStage = useToggleFunnelStage()
  const createRule = useCreateFilterRule()
  const deleteRule = useDeleteFilterRule()

  // ---- Local state ----
  const [adding, setAdding] = useState(false)
  const [detailRule, setDetailRule] = useState<FilterRuleExtended | null>(null)
  const [detailEnricher, setDetailEnricher] = useState<Enricher | null>(null)
  const [detailItem, setDetailItem] = useState<FunnelItem | null>(null)

  // ---- Derived data ----
  const rawRules = filterRulesQ.data ?? []
  const enrichers = enrichersQ.data ?? []
  const loopbacks = loopbacksQ.data ?? []
  const funnelItems = funnelItemsQ.data ?? []
  const enrichmentSamples = enrichmentSamplesQ.data ?? {}

  // Apply feedback-store tuned prompts to rules
  const rules: FilterRuleExtended[] = useMemo(
    () =>
      rawRules.map((r) => ({
        ...r,
        prompt: fb.promptFor(r.id, r.prompt),
        tuned: !!fb.promptFor(r.id, null as unknown as string),
      })),
    [rawRules, fb],
  )

  // Funnel order — server data or local seed fallback
  const serverOrder = funnelOrderQ.data
  const [localOrder, setLocalOrder] = useState<FunnelOrderEntry[] | null>(null)

  const order: FunnelOrderEntry[] = useMemo(() => {
    if (localOrder) return localOrder
    if (serverOrder && serverOrder.length > 0) return serverOrder
    // Seed from available data
    const seed: FunnelOrderEntry[] = []
    const seen = new Set<string>()
    enrichers.forEach((e) => {
      if (!seen.has(e.id)) {
        seed.push({ kind: 'enricher', id: e.id })
        seen.add(e.id)
      }
      // interleave filters that target this source
      rules
        .filter((r) => r.sources.includes(e.type))
        .forEach((r) => {
          if (!seen.has(r.id)) {
            seed.push({ kind: 'filter', id: r.id })
            seen.add(r.id)
          }
        })
    })
    // Remaining filters not yet added
    rules.forEach((r) => {
      if (!seen.has(r.id)) {
        seed.push({ kind: 'filter', id: r.id })
        seen.add(r.id)
      }
    })
    // Loopbacks at the end
    loopbacks.forEach((lb) => {
      if (!seen.has(lb.id)) {
        seed.push({ kind: 'loopback', id: lb.id })
        seen.add(lb.id)
      }
    })
    return seed
  }, [localOrder, serverOrder, enrichers, rules, loopbacks])

  // ---- Handlers ----
  const moveStage = useCallback(
    (id: string, dir: number) => {
      const curr = [...order]
      const i = curr.findIndex((s) => s.id === id)
      const j = i + dir
      if (i < 0 || j < 0 || j >= curr.length) return
      ;[curr[i], curr[j]] = [curr[j], curr[i]]
      setLocalOrder(curr)
      updateOrder.mutate(curr)
    },
    [order, updateOrder],
  )

  const onToggle = useCallback(
    (id: string) => {
      const rule = rules.find((r) => r.id === id)
      if (rule) {
        toggleStage.mutate({ id, enabled: !rule.enabled })
      }
    },
    [rules, toggleStage],
  )

  const onToggleEnricher = useCallback(
    (id: string) => {
      const enricher = enrichers.find((e) => e.id === id)
      if (enricher) {
        toggleStage.mutate({ id, enabled: !enricher.enabled })
      }
    },
    [enrichers, toggleStage],
  )

  const onToggleLoopback = useCallback(
    (id: string) => {
      const lb = loopbacks.find((l) => l.id === id)
      if (lb) {
        toggleStage.mutate({ id, enabled: !lb.enabled })
      }
    },
    [loopbacks, toggleStage],
  )

  const onDelete = useCallback(
    (id: string) => {
      deleteRule.mutate(id)
      setLocalOrder((prev) => (prev ?? order).filter((s) => s.id !== id))
    },
    [deleteRule, order],
  )

  const onCreate = useCallback(
    (input: { prompt: string; action: string; sources: string[] }) => {
      createRule.mutate(input)
    },
    [createRule],
  )

  // ---- Lookup helpers ----
  const ruleOf = (id: string) => rules.find((r) => r.id === id)
  const enricherOf = (id: string) => enrichers.find((e) => e.id === id)
  const loopbackOf = (id: string) => loopbacks.find((l) => l.id === id)

  // ---- Icons ----
  const ArrowDownUp = getIcon('ArrowDownUp')
  const Plus = getIcon('Plus')
  const ChevronRight = getIcon('ChevronRight')

  // ---- State handling ----
  const unauthorizedErr = [
    filterRulesQ,
    enrichersQ,
    loopbacksQ,
    funnelItemsQ,
  ]
    .map((q) => q.error)
    .find(isUnauthorized)

  if (unauthorizedErr) {
    return (
      <div
        data-testid="filters-unauthorized"
        className="flex flex-col items-center justify-center gap-2 p-10 text-center text-muted-foreground"
      >
        <p className="text-lg font-medium">token unavailable</p>
        <p className="text-sm">
          Check that the SSH tunnel is up and the server is bound to loopback.
        </p>
      </div>
    )
  }

  if (filterRulesQ.isPending || enrichersQ.isPending) {
    return (
      <div data-testid="filters-loading" className="space-y-4">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    )
  }

  if (filterRulesQ.isError) {
    const reqId =
      filterRulesQ.error instanceof ApiError
        ? filterRulesQ.error.requestId
        : null
    return (
      <div data-testid="filters-error" className="p-6 text-destructive">
        <p>GET /api/funnel/filter-rules failed.</p>
        {reqId && <p className="text-xs">Request ID: {reqId}</p>}
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gap: 16 }} data-testid="filters-page">
      {/* header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--muted-foreground)',
          }}
        >
          {ArrowDownUp && <ArrowDownUp size={13} />} evaluation order —
          enrichers{' '}
          <span style={{ color: 'var(--tertiary)' }}>add context</span>,
          filters <span style={{ color: 'var(--brand)' }}>decide</span> · use
          ↑ ↓ to reorder
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setAdding(true)}
          data-testid="add-filter-button"
        >
          {Plus && <Plus size={14} />} Add filter
        </Button>
      </div>

      {/* interleaved funnel */}
      <div style={{ display: 'grid', gap: 12 }}>
        {order.map((s, i) => {
          if (s.kind === 'enricher') {
            const e = enricherOf(s.id)
            return e ? (
              <EnricherCard
                key={s.id}
                enricher={e}
                order={i}
                total={order.length}
                reorderable
                onToggle={onToggleEnricher}
                onMove={moveStage}
                onOpen={setDetailEnricher}
              />
            ) : null
          }
          if (s.kind === 'loopback') {
            const lb = loopbackOf(s.id)
            return lb ? (
              <LoopBackCard
                key={s.id}
                lb={lb}
                order={i}
                total={order.length}
                reorderable
                onToggle={onToggleLoopback}
                onMove={moveStage}
              />
            ) : null
          }
          // filter
          const r = ruleOf(s.id)
          return r ? (
            <FilterRuleCard
              key={s.id}
              rule={r}
              order={i}
              total={order.length}
              reorderable
              onToggle={onToggle}
              onDelete={onDelete}
              onMove={moveStage}
              onOpen={setDetailRule}
            />
          ) : null
        })}
      </div>

      {/* Funnel output — recent items + their final treatment */}
      <section style={{ display: 'grid', gap: 10, marginTop: 8 }}>
        <SectionHeader
          right={
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--muted-foreground)',
              }}
            >
              click an item for its full funnel trace
            </span>
          }
        >
          Funnel Output
        </SectionHeader>
        <div
          data-testid="funnel-output-table"
          style={{
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-card, 6px)',
            overflow: 'hidden',
          }}
        >
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 13,
            }}
          >
            <thead>
              <tr>
                {['Item', 'Source', 'Treatment', 'Verdict', ''].map(
                  (hd, i) => (
                    <th
                      key={i}
                      style={{
                        textAlign: 'left',
                        padding: '10px 16px',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 10,
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        letterSpacing: '.06em',
                        color: 'var(--muted-foreground)',
                        background: 'var(--surface-high)',
                        borderBottom: '1px solid var(--border)',
                      }}
                    >
                      {hd}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {funnelItems.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    style={{
                      padding: 24,
                      textAlign: 'center',
                      color: 'var(--muted-foreground)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 12,
                    }}
                  >
                    // no items processed yet
                  </td>
                </tr>
              ) : (
                funnelItems.map((it) => {
                  const decisive = it.stages.filter((s) =>
                    ['drop', 'include', 'label', 'context'].includes(
                      s.outcome,
                    ),
                  )
                  const srcIconName = SRC_ICON[it.source] ?? 'Database'
                  const SrcIcon = getIcon(srcIconName)

                  return (
                    <tr
                      key={it.id}
                      onClick={() => setDetailItem(it)}
                      style={{
                        borderBottom: '1px solid var(--border)',
                        cursor: 'pointer',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'var(--accent)'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'transparent'
                      }}
                    >
                      <td
                        style={{
                          padding: '10px 16px',
                          maxWidth: 260,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {it.summary}
                      </td>
                      <td style={{ padding: '10px 16px' }}>
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                            color: 'var(--muted-foreground)',
                            fontFamily: 'var(--font-mono)',
                            fontSize: 12,
                          }}
                        >
                          {SrcIcon && <SrcIcon size={12} />}
                          {it.source}
                        </span>
                      </td>
                      <td style={{ padding: '10px 16px' }}>
                        <span
                          style={{
                            display: 'flex',
                            gap: 4,
                            flexWrap: 'wrap',
                          }}
                        >
                          {decisive.map((s, j) => (
                            <ActionChip
                              key={j}
                              action={s.outcome}
                              label={s.label}
                              small
                            />
                          ))}
                        </span>
                      </td>
                      <td style={{ padding: '10px 16px' }}>
                        <VerdictPill verdict={it.verdict} />
                      </td>
                      <td
                        style={{ padding: '10px 16px', textAlign: 'right' }}
                      >
                        {ChevronRight && (
                          <ChevronRight
                            size={15}
                            style={{ color: 'var(--muted-foreground)' }}
                          />
                        )}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Dialogs */}
      <AddRuleDialog
        open={adding}
        onClose={() => setAdding(false)}
        onCreate={onCreate}
      />
      <FilterDetailDialog
        rule={detailRule}
        items={funnelItems}
        onClose={() => setDetailRule(null)}
        onOpenItem={(it) => setDetailItem(it)}
      />
      <EnricherDetailDialog
        enricher={detailEnricher}
        samples={
          detailEnricher
            ? enrichmentSamples[detailEnricher.id] ?? []
            : []
        }
        onClose={() => setDetailEnricher(null)}
      />
      <ItemFunnelDialog
        item={detailItem}
        open={!!detailItem}
        onClose={() => setDetailItem(null)}
        filterRules={rules}
        enrichers={enrichers}
        enrichmentSamples={enrichmentSamples}
      />
    </div>
  )
}

export { Filters as IngestionFunnel }

export default Filters
