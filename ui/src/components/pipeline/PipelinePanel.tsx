// PipelinePanel — the Ingestion ▸ Pipeline tab shell. Owns the graph in local
// state; re-runs layout() (memoized) and validate() (memoized) on every
// mutation; and renders the toolbar (validate pill, Tidy, Legend, Add-stage
// menu, Save), the PipelineCanvas, a collapsible accessible fallback table, and
// the config dialogs. insert/delete/connect keep the graph connected.

import { useEffect, useMemo, useState } from 'react'
import {
  Ban,
  Check,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleCheckBig,
  Dot,
  Filter,
  Inbox,
  LayoutGrid,
  List,
  ListChecks,
  Plus,
  RotateCcw,
  ScanLine,
  SlidersHorizontal,
  Sparkles,
  Split,
  TriangleAlert,
  Wand2,
  type LucideIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Mono } from '@/components/Mono'
import { cn } from '@/lib/utils'
import { layout } from '@/lib/pipeline/layout'
import { validate } from '@/lib/pipeline/validate'
import { NODE_META, nodeMeta } from '@/lib/pipeline/schema'
import { predicateBadgeText, toTree } from '@/lib/pipeline/predicate'
import { sampleTree } from '@/lib/pipeline/graphs'
import type {
  ConditionTree,
  NodeType,
  PipelineEdge,
  PipelineGraph,
  PipelineNode,
  PipelineProblem,
} from '@/lib/types/pipeline'
import { CANVAS_H, CANVAS_W, type EdgeVariant } from './geometry'
import { pipelineIcon } from './icons'
import { PipelineCanvas } from './PipelineCanvas'
import { RuleBuilderDialog } from './RuleBuilderDialog'
import { PreFilterDialog } from './PreFilterDialog'
import { LlmFilterDialog } from './LlmFilterDialog'
import { EnricherConfigDialog } from './EnricherConfigDialog'

/* ---- graph-edit helpers (ported verbatim from the reference tab) ---- */

const nextId = (arr: { id: number }[]) => arr.reduce((m, x) => Math.max(m, x.id), 0) + 1

type NodeTemplate = Pick<PipelineNode, 'type' | 'label' | 'source_scope' | 'config' | 'enabled'>

const NODE_TEMPLATES: Partial<Record<NodeType, NodeTemplate>> = {
  pre_filter: { type: 'pre_filter', label: 'New pre-filter', source_scope: ['all'], config: {}, enabled: true },
  rule_filter: { type: 'rule_filter', label: 'New rule', source_scope: ['all'], config: { action: 'drop' }, enabled: true },
  llm_filter: { type: 'llm_filter', label: 'New LLM filter', source_scope: ['all'], config: { include: 70, drop: 30, confidence: 70 }, enabled: true },
  enricher: { type: 'enricher', label: 'New enricher', source_scope: ['all'], config: { provider: 'github_meta', depth: 'shallow' }, enabled: true },
}

type DialogKind = 'prefilter' | 'rule' | 'llm' | 'enricher' | 'edge'

/** Splice a new node into an existing edge: from --(pred)--> N --(always)--> to. */
function insertStage(
  graph: PipelineGraph,
  type: NodeType,
  selectedEdgeId: number | null,
): PipelineGraph & { _newId?: number } {
  const tpl = NODE_TEMPLATES[type]
  if (!tpl) return graph
  const nid = nextId(graph.nodes)
  let target: PipelineEdge | undefined
  if (type === 'pre_filter') {
    const ext = graph.nodes.find((n) => n.type === 'extraction')
    target = graph.edges.find((e) => ext && e.to_node === ext.id) || graph.edges[0]
  } else {
    target = (selectedEdgeId != null && graph.edges.find((e) => e.id === selectedEdgeId)) || undefined
    if (!target) {
      const ext = graph.nodes.find((n) => n.type === 'extraction')
      target = graph.edges.find((e) => ext && e.from_node === ext.id) || graph.edges[0]
    }
  }
  if (!target) return graph
  const from = graph.nodes.find((n) => n.id === target!.from_node)
  const to = graph.nodes.find((n) => n.id === target!.to_node)
  const node: PipelineNode = {
    id: nid,
    pinned: false,
    ...tpl,
    ui_x: from && to ? Math.round((from.ui_x + to.ui_x) / 2) : 600,
    ui_y: from && to ? Math.round((from.ui_y + to.ui_y) / 2) : 250,
  }
  const eid = nextId(graph.edges)
  const edges = graph.edges.map((e) => (e.id === target!.id ? { ...e, to_node: nid } : e))
  edges.push({ id: eid, from_node: nid, to_node: target.to_node, predicate: { op: 'always' }, order_index: 1 })
  return { ...graph, nodes: [...graph.nodes, node], edges, _newId: nid }
}

/** Remove a node and bridge its in-edges to its out-edges to stay connected. */
function deleteStage(graph: PipelineGraph, id: number): PipelineGraph {
  const incoming = graph.edges.filter((e) => e.to_node === id)
  const outgoing = graph.edges.filter((e) => e.from_node === id)
  const kept = graph.edges.filter((e) => e.from_node !== id && e.to_node !== id)
  let eid = nextId(graph.edges)
  const seen = new Set(kept.map((e) => `${e.from_node}>${e.to_node}`))
  incoming.forEach((i) =>
    outgoing.forEach((o) => {
      const key = `${i.from_node}>${o.to_node}`
      if (i.from_node !== o.to_node && !seen.has(key)) {
        seen.add(key)
        kept.push({ id: eid++, from_node: i.from_node, to_node: o.to_node, predicate: i.predicate, order_index: i.order_index })
      }
    }),
  )
  return { ...graph, nodes: graph.nodes.filter((n) => n.id !== id), edges: kept }
}

/* ---- toolbar pieces ---- */

function ValidatePill({
  problems,
  open,
  onToggle,
}: {
  problems: PipelineProblem[]
  open: boolean
  onToggle: () => void
}) {
  const ok = problems.length === 0
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="inline-flex cursor-pointer items-center gap-1.5 rounded-[var(--radius-control)] px-2.5 py-1 font-mono uppercase tracking-[0.04em]"
        style={{
          fontSize: 11,
          border: `1px solid ${ok ? 'color-mix(in srgb, var(--success) 45%, transparent)' : 'color-mix(in srgb, var(--destructive) 55%, transparent)'}`,
          background: ok ? 'color-mix(in srgb, var(--success) 12%, transparent)' : 'color-mix(in srgb, var(--destructive) 12%, transparent)',
          color: ok ? 'var(--success)' : 'var(--error-text)',
        }}
      >
        {ok ? <CircleCheck size={13} /> : <TriangleAlert size={13} />}
        {ok ? 'valid' : `${problems.length} problem${problems.length === 1 ? '' : 's'}`}
      </button>
      {open && !ok && (
        <div className="wb-menu left-0 right-auto" style={{ minWidth: 248, padding: 8 }} role="dialog" aria-label="Validation problems">
          <div className="grid gap-1.5">
            {problems.map((p, i) => (
              <div key={i} className="flex items-start gap-2 text-foreground" style={{ fontSize: 12 }}>
                <Dot size={14} style={{ color: 'var(--destructive)', flexShrink: 0, marginTop: 1 }} />
                <span>{p.msg}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const ADD_STAGES: { type: NodeType; label: string; icon: LucideIcon; hint: string; disabled?: boolean }[] = [
  { type: 'pre_filter', label: 'Pre-filter', icon: Filter, hint: 'pre-extraction · drop only' },
  { type: 'rule_filter', label: 'Rule filter', icon: SlidersHorizontal, hint: 'post-extraction' },
  { type: 'llm_filter', label: 'LLM filter', icon: Sparkles, hint: 'post-extraction' },
  { type: 'enricher', label: 'Enricher', icon: Wand2, hint: 'post-extraction' },
  { type: 'loopback', label: 'Loopback', icon: RotateCcw, hint: 'coming soon', disabled: true },
]

function AddStageMenu({ onPick }: { onPick: (t: NodeType) => void }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Plus size={14} /> Add stage
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[230px]">
        {ADD_STAGES.map((s) => (
          <DropdownMenuItem
            key={s.type}
            disabled={s.disabled}
            onSelect={() => onPick(s.type)}
            className="gap-2.5"
          >
            <s.icon size={15} className="text-muted-foreground" />
            <span className="grid gap-px">
              <span style={{ fontSize: 13 }}>{s.label}</span>
              <span className="font-mono text-muted-foreground" style={{ fontSize: 10 }}>
                {s.hint}
              </span>
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

const LEGEND: [string, LucideIcon, string][] = [
  ['Source', Inbox, 'var(--muted-foreground)'],
  ['Extraction', ScanLine, 'var(--primary)'],
  ['Filter', SlidersHorizontal, 'var(--brand)'],
  ['LLM filter', Sparkles, 'var(--tertiary)'],
  ['Enricher', Wand2, '#b79cf7'],
  ['Triage', ListChecks, 'var(--primary)'],
  ['Auto-include', CircleCheckBig, 'var(--success)'],
  ['Drop', Ban, 'var(--destructive)'],
]

function FallbackTable({ graph }: { graph: PipelineGraph }) {
  const [open, setOpen] = useState(false)
  const nodeById: Record<number, PipelineNode> = {}
  graph.nodes.forEach((n) => {
    nodeById[n.id] = n
  })
  const thClass = 'h-auto px-3 py-[7px] font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground'
  const tdClass = 'px-3 py-[7px] align-middle text-[12.5px]'
  return (
    <div className="overflow-hidden rounded-[var(--radius-card)] border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-2 border-0 bg-transparent px-3.5 py-2.5 text-left text-foreground"
      >
        {open ? <ChevronDown size={15} className="text-muted-foreground" /> : <ChevronRight size={15} className="text-muted-foreground" />}
        <span className="font-mono uppercase tracking-[0.06em] text-muted-foreground" style={{ fontSize: 11 }}>
          Accessible table — {graph.nodes.length} nodes · {graph.edges.length} edges
        </span>
      </button>
      {open && (
        <div className="grid border-t border-border md:grid-cols-2">
          <div className="md:border-r md:border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={thClass}>Type</TableHead>
                  <TableHead className={thClass}>Label</TableHead>
                  <TableHead className={thClass}>Scope</TableHead>
                  <TableHead className={cn(thClass, 'text-right')}>On</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {graph.nodes.map((n) => {
                  const m = nodeMeta(n)
                  const Icon = pipelineIcon(m.icon)
                  return (
                    <TableRow key={n.id} tabIndex={0}>
                      <TableCell className={tdClass}>
                        <span className="inline-flex items-center gap-1.5">
                          <Icon size={12} style={{ color: m.tone }} />
                          <Mono style={{ fontSize: 11 }}>{n.type === 'sink' ? n.role : n.type}</Mono>
                        </span>
                      </TableCell>
                      <TableCell className={tdClass}>{n.label}</TableCell>
                      <TableCell className={tdClass}>
                        <Mono className="text-muted-foreground" style={{ fontSize: 11 }}>
                          {(n.source_scope || ['—']).join(', ')}
                        </Mono>
                      </TableCell>
                      <TableCell className={cn(tdClass, 'text-right')}>
                        {NODE_META[n.type].reserved ? '—' : n.enabled === false ? 'off' : 'on'}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
          <div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={cn(thClass, 'w-16')}>Edge</TableHead>
                  <TableHead className={thClass}>From → To</TableHead>
                  <TableHead className={thClass}>Predicate</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {graph.edges.map((e) => {
                  const isAlways = !e.predicate || ('op' in e.predicate && e.predicate.op === 'always')
                  return (
                    <TableRow key={e.id} tabIndex={0}>
                      <TableCell className={tdClass}>
                        <Mono className="font-bold" style={{ fontSize: 11, color: 'var(--brand)' }}>
                          E{e.id}
                        </Mono>{' '}
                        <Mono className="text-muted-foreground" style={{ fontSize: 10 }}>
                          ·{e.order_index}
                        </Mono>
                      </TableCell>
                      <TableCell className={tdClass}>
                        <Mono style={{ fontSize: 11 }}>
                          {nodeById[e.from_node]?.label} → {nodeById[e.to_node]?.label}
                        </Mono>
                      </TableCell>
                      <TableCell className={tdClass}>
                        <Mono style={{ fontSize: 11, color: isAlways ? 'var(--muted-foreground)' : 'var(--foreground)' }}>
                          {predicateBadgeText(e.predicate)}
                        </Mono>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  )
}

/* ---- the panel ---- */

export interface PipelinePanelProps {
  graph: PipelineGraph
  editable?: boolean
  interactive?: boolean
  variant?: EdgeVariant
  /** Persist hook — called with the current graph on Save. */
  onSave?: (graph: PipelineGraph) => void
}

interface DialogState {
  kind: DialogKind
  node?: PipelineNode | null
  edge?: PipelineEdge
  create?: boolean
}

export function PipelinePanel({
  graph: initialGraph,
  editable = false,
  interactive = true,
  variant = 'schematic',
  onSave,
}: PipelinePanelProps) {
  const auto = editable
  const [g, setG] = useState<PipelineGraph>(initialGraph)
  const [selId, setSelId] = useState<number | null>(null)
  const [selEdge, setSelEdge] = useState<number | null>(null)
  const [dirty, setDirty] = useState(false)
  const [dialog, setDialog] = useState<DialogState | null>(null)
  const [legend, setLegend] = useState(false)
  const [probOpen, setProbOpen] = useState(false)

  // auto-layout pass (recomputed whenever the graph mutates)
  const laid = useMemo(
    () =>
      auto
        ? layout(g)
        : { nodes: g.nodes, edges: g.edges, lanes: [], width: CANVAS_W, height: CANVAS_H },
    [g, auto],
  )
  const lgraph: PipelineGraph = { nodes: laid.nodes, edges: laid.edges }
  const nodeById: Record<number, PipelineNode> = {}
  laid.nodes.forEach((n) => {
    nodeById[n.id] = n
  })

  // live validation — derived from the real graph on every mutation
  const live = useMemo(() => validate(g), [g])

  const onToggle = (id: number, v: boolean) => {
    setG((gr) => ({ ...gr, nodes: gr.nodes.map((n) => (n.id === id ? { ...n, enabled: v } : n)) }))
    setDirty(true)
  }
  const openConfigFor = (node: PipelineNode) => {
    if (node.type === 'pre_filter') setDialog({ kind: 'prefilter', node })
    else if (node.type === 'rule_filter') setDialog({ kind: 'rule', node })
    else if (node.type === 'llm_filter') setDialog({ kind: 'llm', node })
    else if (node.type === 'enricher') setDialog({ kind: 'enricher', node })
  }
  const onSelect = (id: number | null) => {
    setSelEdge(null)
    setSelId(id)
  }
  const onSelectEdge = (id: number | null) => {
    setSelId(null)
    setSelEdge(id)
    if (id != null) {
      const e = g.edges.find((x) => x.id === id)
      if (e) setDialog({ kind: 'edge', edge: e })
    }
  }
  const closeDialog = () => setDialog(null)

  // editor mutations
  const onNodeMove = (id: number, x: number, y: number) => {
    setG((gr) => ({ ...gr, nodes: gr.nodes.map((n) => (n.id === id ? { ...n, ui_x: x, ui_y: y, pinned: true } : n)) }))
    setDirty(true)
  }
  const onPinToggle = (id: number) => {
    setG((gr) => ({ ...gr, nodes: gr.nodes.map((n) => (n.id === id ? { ...n, pinned: !n.pinned } : n)) }))
    setDirty(true)
  }
  const onDelete = (id: number) => {
    setG((gr) => deleteStage(gr, id))
    setSelId(null)
    setDirty(true)
  }
  const onDeleteEdge = (id: number) => {
    setG((gr) => ({ ...gr, edges: gr.edges.filter((e) => e.id !== id) }))
    setSelEdge(null)
    setDialog(null)
    setDirty(true)
  }
  const onConnect = (from: number, to: number) => {
    if (g.edges.some((e) => e.from_node === from && e.to_node === to)) return
    const eid = nextId(g.edges)
    const order = g.edges.filter((e) => e.from_node === from).length + 1
    const edge: PipelineEdge = { id: eid, from_node: from, to_node: to, predicate: { op: 'always' }, order_index: order }
    setG((gr) => ({ ...gr, edges: [...gr.edges, edge] }))
    setDirty(true)
    setSelId(null)
    setSelEdge(eid)
    setTimeout(() => setDialog({ kind: 'edge', edge }), 0)
  }
  const addStage = (type: NodeType) => {
    setG((gr) => {
      const res = insertStage(gr, type, selEdge)
      if (res._newId != null) {
        const nn = res.nodes.find((n) => n.id === res._newId)
        setSelId(res._newId)
        setSelEdge(null)
        if (nn) setTimeout(() => openConfigFor(nn), 0)
      }
      return res
    })
    setDirty(true)
  }
  const tidy = () => {
    setG((gr) => ({ ...gr, nodes: gr.nodes.map((n) => ({ ...n, pinned: false })) }))
    setDirty(true)
  }

  // dialog → graph persistence
  const patchNode = (id: number, patch: Partial<PipelineNode>) => {
    setG((gr) => ({ ...gr, nodes: gr.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)) }))
    setDirty(true)
  }
  const setEdgePredicate = (id: number, tree: ConditionTree) => {
    setG((gr) => ({ ...gr, edges: gr.edges.map((e) => (e.id === id ? { ...e, predicate: tree } : e)) }))
    setDirty(true)
  }

  // keyboard delete of the selected non-reserved node
  useEffect(() => {
    if (!editable) return undefined
    const k = (e: KeyboardEvent) => {
      if (dialog) return
      const t = e.target as HTMLElement | null
      if (t && /input|textarea|select/i.test(t.tagName)) return
      if ((e.key === 'Delete' || e.key === 'Backspace') && selId != null) {
        const n = nodeById[selId]
        if (n && !NODE_META[n.type].reserved) {
          e.preventDefault()
          onDelete(selId)
        }
      }
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editable, selId, dialog, laid])

  const pinnedCount = g.nodes.filter((n) => n.pinned).length

  return (
    <div className="grid gap-3.5">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2.5">
        <h2 className="m-0 font-semibold tracking-[-0.01em]" style={{ fontFamily: 'var(--font-display)', fontSize: 18 }}>
          Pipeline
        </h2>
        <span className="font-mono text-muted-foreground" style={{ fontSize: 11 }}>
          routing DAG
        </span>
        <ValidatePill problems={live.problems} open={probOpen} onToggle={() => setProbOpen((v) => !v)} />
        <div className="ml-auto flex items-center gap-2">
          {editable && (
            <button
              type="button"
              onClick={tidy}
              disabled={pinnedCount === 0}
              title="Re-run auto-layout & clear manual positions"
              className="wb-iconbtn h-[30px] gap-1.5 border border-border px-2.5 text-muted-foreground"
              style={{ width: 'auto', fontSize: 12, opacity: pinnedCount === 0 ? 0.5 : 1 }}
            >
              <LayoutGrid size={14} /> Tidy{pinnedCount ? ` (${pinnedCount})` : ''}
            </button>
          )}
          <button
            type="button"
            onClick={() => setLegend((v) => !v)}
            aria-pressed={legend}
            className="wb-iconbtn h-[30px] gap-1.5 border border-border px-2.5"
            style={{ width: 'auto', fontSize: 12, color: legend ? 'var(--foreground)' : 'var(--muted-foreground)' }}
          >
            <List size={14} /> Legend
          </button>
          <AddStageMenu onPick={(t) => addStage(t)} />
          <Button
            size="sm"
            disabled={!dirty}
            onClick={() => {
              setDirty(false)
              onSave?.(g)
            }}
          >
            <Check size={14} /> Save
          </Button>
        </div>
      </div>

      {legend && (
        <div className="flex flex-wrap gap-3.5 rounded-[var(--radius-card)] border border-border bg-card px-3.5 py-2.5">
          {LEGEND.map(([label, Icon, tone]) => (
            <span key={label} className="inline-flex items-center gap-1.5 text-muted-foreground" style={{ fontSize: 12 }}>
              <Icon size={13} style={{ color: tone }} />
              {label}
            </span>
          ))}
          <span className="ml-auto inline-flex items-center gap-1.5 text-muted-foreground" style={{ fontSize: 12 }}>
            {editable ? 'drag node to pin · drag its port to connect · hover edge for its rule · ' : ''}
            <span className="inline-block h-0 w-[18px]" style={{ borderTop: '2px dashed var(--tertiary)' }} /> conditional route
          </span>
        </div>
      )}

      <PipelineCanvas
        graph={lgraph}
        variant={variant}
        interactive={interactive}
        editable={editable}
        lanes={laid.lanes}
        canvasW={laid.width}
        canvasH={laid.height}
        selectedId={selId}
        selectedEdgeId={selEdge}
        onSelect={onSelect}
        onSelectEdge={onSelectEdge}
        onToggle={onToggle}
        onConfig={openConfigFor}
        onNodeMove={onNodeMove}
        onPinToggle={onPinToggle}
        onDelete={onDelete}
        onConnect={onConnect}
        errorNodes={live.errorNodes}
        errorEdges={live.errorEdges}
      />

      <FallbackTable graph={g} />

      {dialog?.kind === 'prefilter' && (
        <PreFilterDialog
          initialTree={(dialog.node?.config as { tree?: ConditionTree } | undefined)?.tree}
          onClose={closeDialog}
          onSave={(tree) => {
            if (dialog.node) patchNode(dialog.node.id, { config: { ...dialog.node.config, tree } })
          }}
        />
      )}
      {dialog?.kind === 'rule' && (
        <RuleBuilderDialog
          initialTree={(dialog.node?.config as { tree?: ConditionTree } | undefined)?.tree || sampleTree}
          segment="post"
          title={dialog.node ? dialog.node.label : 'Rule filter'}
          onClose={closeDialog}
          onSave={(tree, action) => {
            if (dialog.node) patchNode(dialog.node.id, { config: { ...dialog.node.config, tree, action } })
          }}
        />
      )}
      {dialog?.kind === 'llm' && (
        <LlmFilterDialog
          node={dialog.node ?? null}
          onClose={closeDialog}
          onSave={(config) => {
            if (dialog.node) patchNode(dialog.node.id, { config: { ...dialog.node.config, ...config } })
          }}
        />
      )}
      {dialog?.kind === 'enricher' && (
        <EnricherConfigDialog
          node={dialog.node ?? null}
          mode={dialog.create ? 'create' : 'edit'}
          onClose={closeDialog}
          onSave={(config, sourceScope, enabled) => {
            if (dialog.node) patchNode(dialog.node.id, { config: { ...dialog.node.config, ...config }, source_scope: sourceScope, enabled })
          }}
        />
      )}
      {dialog?.kind === 'edge' && dialog.edge && (
        <RuleBuilderDialog
          initialTree={toTree(dialog.edge.predicate, 'both')}
          segment="both"
          icon={Split}
          tone="var(--tertiary)"
          kicker="EDGE.PREDICATE"
          title="Route predicate"
          actionOptions={[{ value: 'route', label: 'Route' }]}
          onDelete={editable ? () => onDeleteEdge(dialog.edge!.id) : undefined}
          onClose={closeDialog}
          onSave={(tree) => setEdgePredicate(dialog.edge!.id, tree)}
          footerNote={`edge E${dialog.edge.id} · match #${dialog.edge.order_index} · first match wins`}
        />
      )}
    </div>
  )
}
