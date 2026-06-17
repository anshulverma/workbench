// SystemStatus page — full-page live system status diagram (v4).
//
// A left-to-right lane-based SVG diagram showing connectors, ingestion edge,
// core, services, and storage. Node cards show icon, label, status, ping, and
// utilization. Clicking a node opens a searchable log viewer dialog.

import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  ArrowLeftRight,
  Boxes,
  Brain,
  Chrome,
  Database,
  Github,
  GitPullRequestArrow,
  HardDrive,
  Hexagon,
  MessageCircle,
  Network,
  Pause,
  Play,
  Search,
  Sparkles,
  TriangleAlert,
  Workflow,
  X,
  type LucideIcon,
} from 'lucide-react'
import { StatCard } from '@/components/StatCard'
import { Mono } from '@/components/Mono'
import { Portal } from '@/components/Portal'
import { JsonHighlight } from '@/components/JsonHighlight'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useHealth } from '@/hooks/useStats'
import { ApiError } from '@/lib/api'

// ---- Status + role vocabularies (matching design prototype) ---- //

const SYS_STATUS: Record<string, { color: string; label: string }> = {
  healthy: { color: '#9ad08a', label: 'operational' },
  degraded: { color: '#f5a623', label: 'degraded' },
  unhealthy: { color: '#e5484d', label: 'down' },
  disabled: { color: '#71717a', label: 'paused' },
  planned: { color: '#71717a', label: 'planned' },
}

const ROLE_TONE: Record<string, string> = {
  connector: '#71d2ff',
  service: '#b79cf7',
  core: '#f5a623',
  storage: '#9ad08a',
}

// ---- Icon lookup by string name ---- //

const ICON_MAP: Record<string, LucideIcon> = {
  Activity,
  ArrowLeftRight,
  Boxes,
  Brain,
  Chrome,
  Database,
  Github,
  GitPullRequestArrow,
  HardDrive,
  Hexagon,
  MessageCircle,
  Network,
  Pause,
  Play,
  Search,
  Sparkles,
  Workflow,
  X,
}

function IconByName({ name, size }: { name: string; size: number }) {
  const Comp = ICON_MAP[name] ?? Activity
  return <Comp size={size} />
}

// ---- Data types ---- //

export interface SystemNode {
  id: string
  lane: number
  label: string
  icon: string
  role: string
  caps?: string[]
  status: string
  latency?: number | null
  util?: number | null
  lastPing?: number | null
  sub?: string
}

export interface SystemEdge {
  from: string
  to: string
  dir?: string
  kind?: string
}

export interface SystemStatusData {
  nodes: SystemNode[]
  edges: SystemEdge[]
  lanes: string[]
  summary: { version: string }
}

export interface LogLine {
  t: string
  level: string
  msg: string
}

export type SystemLogs = Record<string, LogLine[]>

// ---- Default mock data (used when no API is available) ---- //

const DEFAULT_SYSTEM_STATUS: SystemStatusData = {
  lanes: ['Connectors', 'Ingest', 'Core', 'Services', 'Storage'],
  summary: { version: '0.4.0' },
  nodes: [
    { id: 'phabricator', lane: 0, label: 'Phabricator', icon: 'GitPullRequestArrow', role: 'connector', caps: ['in', 'out'], status: 'healthy', latency: 120, util: 34, lastPing: 2 },
    { id: 'gchat', lane: 0, label: 'Google Chat', icon: 'MessageCircle', role: 'connector', caps: ['in', 'out'], status: 'healthy', latency: 85, util: 22, lastPing: 1 },
    { id: 'github', lane: 0, label: 'GitHub', icon: 'Github', role: 'connector', caps: ['in'], status: 'planned', latency: null, util: null, lastPing: null },
    { id: 'browser', lane: 0, label: 'Browser Ext', icon: 'Chrome', role: 'connector', caps: ['in'], status: 'planned', latency: null, util: null, lastPing: null },
    { id: 'ingest-queue', lane: 1, label: 'Ingest Queue', icon: 'Boxes', role: 'service', status: 'healthy', latency: 15, util: 41, lastPing: 1 },
    { id: 'scorer', lane: 1, label: 'Queue Scorer', icon: 'Sparkles', role: 'service', status: 'healthy', latency: 210, util: 58, lastPing: 3 },
    { id: 'workbench', lane: 2, label: 'WorkBench Core', icon: 'Hexagon', role: 'core', status: 'healthy', latency: 8, util: 27, lastPing: 1 },
    { id: 'llm', lane: 3, label: 'LLM Provider', icon: 'Sparkles', role: 'service', status: 'healthy', latency: 680, util: 72, lastPing: 2 },
    { id: 'memory', lane: 3, label: 'Memory (Zep)', icon: 'Brain', role: 'service', status: 'degraded', latency: 1200, util: 89, lastPing: 8 },
    { id: 'enrichment', lane: 3, label: 'Enrichment', icon: 'Workflow', role: 'service', status: 'healthy', latency: 340, util: 45, lastPing: 2 },
    { id: 'postgres', lane: 4, label: 'PostgreSQL', icon: 'Database', role: 'storage', status: 'healthy', latency: 4, util: 18, lastPing: 1 },
    { id: 'disk', lane: 4, label: 'Disk Cache', icon: 'HardDrive', role: 'storage', status: 'healthy', latency: 1, util: 12, lastPing: 1 },
  ],
  edges: [
    { from: 'phabricator', to: 'ingest-queue', dir: 'right' },
    { from: 'gchat', to: 'ingest-queue', dir: 'right' },
    { from: 'github', to: 'ingest-queue', dir: 'right' },
    { from: 'browser', to: 'ingest-queue', dir: 'right' },
    { from: 'ingest-queue', to: 'scorer', dir: 'down' },
    { from: 'scorer', to: 'workbench', dir: 'right' },
    { from: 'ingest-queue', to: 'workbench', dir: 'right' },
    { from: 'workbench', to: 'llm', dir: 'right' },
    { from: 'workbench', to: 'memory', dir: 'right' },
    { from: 'workbench', to: 'enrichment', dir: 'right' },
    { from: 'workbench', to: 'postgres', dir: 'right' },
    { from: 'workbench', to: 'disk', dir: 'right' },
    { from: 'workbench', to: 'gchat', dir: 'left', kind: 'reply' },
    { from: 'workbench', to: 'phabricator', dir: 'left', kind: 'reply' },
  ],
}

const DEFAULT_SYSTEM_LOGS: SystemLogs = {
  phabricator: [
    { t: '2026-06-10T09:00:01Z', level: 'INFO', msg: 'polling phabricator for new diffs' },
    { t: '2026-06-10T09:00:02Z', level: 'INFO', msg: 'fetched 12 diffs, 3 new since last run' },
    { t: '2026-06-10T09:00:03Z', level: 'WARN', msg: 'rate limit approaching: 80/100 calls used' },
  ],
  gchat: [
    { t: '2026-06-10T09:01:00Z', level: 'INFO', msg: 'connected to google chat webhook' },
    { t: '2026-06-10T09:01:05Z', level: 'INFO', msg: 'sent triage card to space "WorkBench"' },
  ],
  'ingest-queue': [
    { t: '2026-06-10T09:00:04Z', level: 'INFO', msg: 'enqueued 3 items from phabricator' },
    { t: '2026-06-10T09:00:05Z', level: 'INFO', msg: 'queue depth: 7 items' },
  ],
  scorer: [
    { t: '2026-06-10T09:00:06Z', level: 'INFO', msg: 'scored item phab-1234: urgency=0.82' },
    { t: '2026-06-10T09:00:07Z', level: 'INFO', msg: 'scored item phab-1235: urgency=0.31' },
  ],
  workbench: [
    { t: '2026-06-10T09:00:10Z', level: 'INFO', msg: 'processing batch of 3 items' },
    { t: '2026-06-10T09:00:12Z', level: 'INFO', msg: 'extraction complete: 2 action items, 1 informational' },
    { t: '2026-06-10T09:00:13Z', level: 'WARN', msg: 'enrichment budget exceeded for item phab-1236' },
  ],
  llm: [
    { t: '2026-06-10T09:00:11Z', level: 'INFO', msg: 'plugboard request: extraction prompt (680ms)' },
    { t: '2026-06-10T09:00:14Z', level: 'INFO', msg: 'plugboard request: triage prompt (520ms)' },
  ],
  memory: [
    { t: '2026-06-10T09:00:15Z', level: 'WARN', msg: 'zep server latency spike: 1200ms' },
    { t: '2026-06-10T09:00:16Z', level: 'ERROR', msg: 'failed to write preference fact: connection timeout' },
    { t: '2026-06-10T09:00:17Z', level: 'INFO', msg: 'queued write for retry (attempt 2/3)' },
  ],
  enrichment: [
    { t: '2026-06-10T09:00:18Z', level: 'INFO', msg: 'shallow enrichment for phab-1234 (340ms)' },
  ],
  postgres: [
    { t: '2026-06-10T09:00:19Z', level: 'INFO', msg: 'stored 2 items, 1 triage card created' },
  ],
  disk: [
    { t: '2026-06-10T09:00:20Z', level: 'INFO', msg: 'cache hit for diff hunks phab-1234' },
  ],
}

// ---- LLM Infra types + vocabularies ---- //
//
// Every call WorkBench makes to the AI layer is recorded here. Calls are
// BATCHED: one request can carry several items (sub-calls). `origin` = which
// funnel stage/feature triggered it; `purpose` = what it asked the model to do;
// `stage` = the pipeline stage (filter / enricher / triage / briefing /
// aggregate), which colors the row.

export interface LLMCall {
  id: string
  ts: string
  origin: string
  purpose: string
  stage: string
  model: string
  temperature: number
  status: string
  batch: number
  items: string[]
  tokens_in: number
  tokens_out: number | null
  latency_ms: number | null
}

export interface LLMSubCall {
  item: string
  prompt: string
  completion: string
  structured: Record<string, unknown> | null
  tokens_in: number
  tokens_out: number | null
}

export interface LLMCallDetailData {
  sysPrompt: string
  subcalls: LLMSubCall[]
}

const LLM_STATUS: Record<string, { color: string; label: string }> = {
  ok: { color: '#9ad08a', label: 'ok' },
  running: { color: '#71d2ff', label: 'running' },
  error: { color: '#e5484d', label: 'error' },
}

const LLM_STAGE_TONE: Record<string, string> = {
  filter: '#e5484d',
  enricher: '#71d2ff',
  triage: '#f5a623',
  briefing: '#b79cf7',
  aggregate: '#9a7af0',
}

// ---- Default mock LLM-call pool (used when no API is available) ---- //

function buildDefaultLLMCalls(): LLMCall[] {
  const now = Date.now()
  const MODELS = ['claude-opus-4-8', 'claude-haiku-4-2']
  const KIND = [
    { origin: 'fr_31', purpose: 'classify · drop-confidence', stage: 'filter', model: 1 },
    { origin: 'fr_29', purpose: 'classify · include-confidence', stage: 'filter', model: 1 },
    { origin: 'en_github', purpose: 'enrich · summarize diff', stage: 'enricher', model: 0 },
    { origin: 'triage', purpose: 'score · relevance + priority', stage: 'triage', model: 0 },
    { origin: 'en_email', purpose: 'enrich · extract entities', stage: 'enricher', model: 1 },
    { origin: 'briefing', purpose: 'summarize · morning briefing', stage: 'briefing', model: 0 },
    { origin: 'fr_09', purpose: 'label · noise vs signal', stage: 'filter', model: 1 },
    { origin: 'aggregate', purpose: 'merge · funnel verdict', stage: 'aggregate', model: 0 },
  ]
  const ITEM_POOL = ['D12871', 'D12863', 'eml_5521', 'cal_8841', 'chat_2207', 'itm_8841', 'eml_5488', 'itm_8829']
  const BATCHES = [1, 1, 3, 1, 5, 2, 1, 4]
  const calls: LLMCall[] = []
  for (let i = 0; i < 64; i++) {
    const k = KIND[i % KIND.length]
    const batchN = BATCHES[i % 8]
    const status = i % 19 === 5 ? 'error' : i % 11 === 3 ? 'running' : 'ok'
    const inTok = 320 + ((i * 137) % 5400)
    const outTok = 40 + ((i * 51) % 720)
    const ms = k.model === 0 ? 240 + ((i * 83) % 900) : 90 + ((i * 37) % 260)
    const items = Array.from({ length: batchN }, (_, j) => ITEM_POOL[(i + j) % ITEM_POOL.length])
    calls.push({
      id: 'llm_' + (94120 - i),
      ts: new Date(now - i * 7400 - (i % 4) * 1300).toISOString(),
      origin: k.origin,
      purpose: k.purpose,
      stage: k.stage,
      model: MODELS[k.model],
      temperature: k.stage === 'enricher' ? 0 : 0.2,
      status,
      batch: batchN,
      items,
      tokens_in: inTok,
      tokens_out: status === 'running' ? null : outTok,
      latency_ms: status === 'running' ? null : ms,
    })
  }
  return calls
}

const DEFAULT_LLM_CALLS = buildDefaultLLMCalls()

// Build the prompt / completion / structured-output detail for one batched call.
function llmCallDetail(call: LLMCall): LLMCallDetailData {
  const sysPrompt =
    {
      filter:
        'You are a noise filter. Given an item and a rule, return whether the rule fires and a calibrated confidence.',
      enricher:
        'You enrich an item with structured metadata. Resolve linked entities and return facts only — never a verdict.',
      triage:
        'You are a triage scorer. Return relevance (0-100) and an estimated priority P0–P3 with a one-line reason.',
      briefing:
        'You write a terse morning briefing. Operator voice, no marketing, lead with the highest-priority signal.',
      aggregate:
        'You merge per-rule signals into a single verdict. Resolve conflicts, weight independent agreement higher.',
    }[call.stage] || 'You assist the WorkBench triage pipeline.'

  const subcalls: LLMSubCall[] = call.items.map((itemId, j) => {
    const inT = Math.round(call.tokens_in / call.batch) + ((j * 13) % 40)
    const outT = call.tokens_out == null ? null : Math.round(call.tokens_out / call.batch) + ((j * 7) % 18)
    let structured: Record<string, unknown>
    if (call.stage === 'filter')
      structured = { rule: call.origin, item: itemId, fires: j % 2 === 0, confidence: 88 - j * 6 }
    else if (call.stage === 'enricher')
      structured = { item: itemId, entities: ['diff:' + itemId, 'author:alice'], ci_status: j % 2 ? 'passing' : 'failing' }
    else if (call.stage === 'triage')
      structured = { item: itemId, relevance: 94 - j * 11, priority: ['P0', 'P1', 'P2', 'P3'][j % 4] }
    else if (call.stage === 'aggregate')
      structured = { item: itemId, decision: j % 3 === 0 ? 'dropped' : 'triaged', priority: 'P1', confidence: 91 - j * 5 }
    else structured = { item: itemId, summary: 'one-line summary for ' + itemId }
    return {
      item: itemId,
      prompt: `[item ${itemId}]\n${call.purpose} — evaluate against context and return JSON.`,
      completion: call.status === 'error' ? '— (request failed)' : JSON.stringify(structured),
      structured: call.status === 'error' ? null : structured,
      tokens_in: inT,
      tokens_out: outT,
    }
  })
  return { sysPrompt, subcalls }
}

// ---- SystemDiagram component ---- //

function SystemDiagram({
  data,
  onSelect,
  selectedId,
}: {
  data: SystemStatusData
  onSelect: (id: string | null) => void
  selectedId: string | null
}) {
  const W = 1080
  const laneCount = data.lanes.length
  const padX = 90
  const padTop = 52
  const padBot = 24
  const rowH = 74
  const nodeW = 156
  const nodeH = 52

  const byLane = data.lanes.map((_, i) => data.nodes.filter((n) => n.lane === i))
  const maxRows = Math.max(...byLane.map((c) => c.length))
  const H = padTop + padBot + maxRows * rowH

  const laneX = (lane: number) =>
    padX + lane * ((W - padX * 2 - nodeW) / (laneCount - 1))

  const pos: Record<string, { x: number; y: number }> = {}
  byLane.forEach((col, lane) => {
    const colH = col.length * rowH
    const top = padTop + (maxRows * rowH - colH) / 2
    col.forEach((n, i) => {
      pos[n.id] = { x: laneX(lane), y: top + i * rowH + (rowH - nodeH) / 2 }
    })
  })

  const cy = (id: string) => pos[id].y + nodeH / 2
  const anchor = (id: string, side: 'l' | 'r') => ({
    x: pos[id].x + (side === 'r' ? nodeW : 0),
    y: cy(id),
  })

  const edgePath = (e: SystemEdge) => {
    const a = pos[e.from]
    const b = pos[e.to]
    const fromRight = a.x <= b.x
    const s = anchor(e.from, fromRight ? 'r' : 'l')
    const t = anchor(e.to, fromRight ? 'l' : 'r')
    const mx = (s.x + t.x) / 2
    return `M${s.x},${s.y} C${mx},${s.y} ${mx},${t.y} ${t.x},${t.y}`
  }

  const nodeStatus = (n: SystemNode) => SYS_STATUS[n.status] || SYS_STATUS.disabled

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height="auto"
      style={{ display: 'block' }}
      role="img"
      aria-label="WorkBench system diagram"
      data-testid="system-diagram"
    >
      {/* lane labels */}
      {data.lanes.map((lab, i) => (
        <text
          key={lab}
          x={laneX(i) + nodeW / 2}
          y={26}
          textAnchor="middle"
          fontFamily="var(--font-mono)"
          fontSize="11"
          fontWeight="700"
          letterSpacing="1.5"
          fill="var(--muted-foreground)"
          style={{ textTransform: 'uppercase' }}
        >
          {lab}
        </text>
      ))}

      {/* edges */}
      {data.edges.map((e, i) => {
        const d = edgePath(e)
        const reply = e.kind === 'reply'
        const dim = selectedId && e.from !== selectedId && e.to !== selectedId
        const stroke = reply ? '#b79cf7' : 'var(--border)'
        return (
          <g
            key={i}
            style={{
              opacity: dim ? 0.18 : 1,
              transition: 'opacity .15s ease',
            }}
          >
            <path
              d={d}
              fill="none"
              stroke={stroke}
              strokeWidth={reply ? 1.5 : 2}
              strokeDasharray={reply ? '5 4' : undefined}
              vectorEffect="non-scaling-stroke"
            />
          </g>
        )
      })}

      {/* nodes */}
      {data.nodes.map((n) => {
        const st = nodeStatus(n)
        const planned = n.status === 'planned'
        const off = n.status === 'disabled' || planned
        const sel = selectedId === n.id
        const tone = planned ? '#71717a' : (ROLE_TONE[n.role] || '#71d2ff')
        const p = pos[n.id]
        return (
          <g
            key={n.id}
            transform={`translate(${p.x},${p.y})`}
            style={{ cursor: 'pointer' }}
            onClick={() => onSelect(sel ? null : n.id)}
            data-testid={`system-node-${n.id}`}
            role="button"
            aria-label={`${n.label} node`}
          >
            <rect
              width={nodeW}
              height={nodeH}
              rx="8"
              fill="var(--card)"
              stroke={sel ? tone : 'var(--border)'}
              strokeWidth={sel ? 2 : 1}
              strokeDasharray={planned ? '4 3' : undefined}
              style={{ opacity: off ? 0.6 : 1 }}
            />
            <rect
              x="0"
              y="0"
              width="3"
              height={nodeH}
              rx="1.5"
              fill={st.color}
              style={{ opacity: off ? 0.6 : 1 }}
            />
            <foreignObject x="0" y="0" width={nodeW} height={nodeH}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  height: '100%',
                  padding: '0 11px 0 13px',
                  boxSizing: 'border-box',
                  opacity: off ? 0.7 : 1,
                }}
              >
                <span
                  style={{
                    flexShrink: 0,
                    width: 30,
                    height: 30,
                    borderRadius: 7,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: `color-mix(in srgb, ${tone} 16%, transparent)`,
                    color: tone,
                  }}
                >
                  <IconByName name={n.icon} size={16} />
                </span>
                <span
                  style={{
                    display: 'grid',
                    gap: 2,
                    minWidth: 0,
                    flex: 1,
                    lineHeight: 1.1,
                  }}
                >
                  <span
                    style={{
                      fontSize: 12.5,
                      fontWeight: 600,
                      color: 'var(--foreground)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {n.label}
                  </span>
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 9,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    <span
                      style={{
                        color: st.color,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '.03em',
                      }}
                    >
                      {st.label}
                    </span>
                    {!off && n.lastPing != null && (
                      <span style={{ color: 'var(--muted-foreground)' }}>
                        {' '}
                        · {n.lastPing}s · {n.util}%
                      </span>
                    )}
                  </span>
                </span>
                <span
                  style={{
                    flexShrink: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 3,
                  }}
                >
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: 9999,
                      background: st.color,
                    }}
                  />
                  {n.role === 'connector' && n.caps && n.caps.includes('out') && (
                    <span
                      title="bidirectional"
                      style={{ color: '#b79cf7', display: 'flex' }}
                    >
                      <ArrowLeftRight size={10} />
                    </span>
                  )}
                </span>
              </div>
            </foreignObject>
          </g>
        )
      })}
    </svg>
  )
}

// ---- SystemLogViewer component ---- //

const LVL_COLOR: Record<string, string> = {
  INFO: 'var(--muted-foreground)',
  DEBUG: 'var(--muted-foreground)',
  WARN: 'var(--brand)',
  ERROR: 'var(--destructive)',
}

function SystemLogViewer({
  node,
  logs,
  onClose,
}: {
  node: SystemNode | null
  logs: SystemLogs
  onClose: () => void
}) {
  const [q, setQ] = useState('')
  const [level, setLevel] = useState('all')
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scroller.current) {
      scroller.current.scrollTop = scroller.current.scrollHeight
    }
  }, [node])

  // Reset search/filter when node changes
  useEffect(() => {
    setQ('')
    setLevel('all')
  }, [node?.id])

  if (!node) return null

  const st = SYS_STATUS[node.status] || SYS_STATUS.disabled
  const tone = ROLE_TONE[node.role] || '#71d2ff'
  const raw = logs[node.id] || []
  const query = q.trim().toLowerCase()
  const lines = raw.filter(
    (l) =>
      (level === 'all' || l.level === level) &&
      (!query ||
        l.msg.toLowerCase().includes(query) ||
        l.level.toLowerCase().includes(query)),
  )
  const counts = raw.reduce<Record<string, number>>((a, l) => {
    a[l.level] = (a[l.level] || 0) + 1
    return a
  }, {})
  const fmt = (iso: string) =>
    new Date(iso).toLocaleTimeString([], { hour12: false })

  return (
    <Portal>
      <div
        className="wb-overlay"
        style={{ alignItems: 'center', paddingTop: 0, zIndex: 120 }}
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) onClose()
        }}
        data-testid="log-viewer-overlay"
      >
        <div
          className="wb-dialog-card"
          role="dialog"
          aria-modal="true"
          aria-label={`${node.label} logs`}
          style={{
            width: 'min(760px, 94vw)',
            padding: 0,
            overflow: 'hidden',
            maxHeight: '86vh',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* header */}
          <div
            style={{
              padding: '16px 18px',
              borderBottom: '1px solid var(--border)',
              display: 'grid',
              gap: 12,
            }}
          >
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 10 }}
            >
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 30,
                  height: 30,
                  borderRadius: 7,
                  background: `color-mix(in srgb, ${tone} 16%, transparent)`,
                  color: tone,
                }}
              >
                <IconByName name={node.icon} size={17} />
              </span>
              <div style={{ display: 'grid', lineHeight: 1.2 }}>
                <span style={{ fontSize: 15, fontWeight: 600 }}>
                  {node.label}{' '}
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11,
                      fontWeight: 400,
                      color: 'var(--muted-foreground)',
                    }}
                  >
                    logs
                  </span>
                </span>
                {node.sub && (
                  <span
                    style={{ fontSize: 11, color: 'var(--muted-foreground)' }}
                  >
                    {node.sub}
                  </span>
                )}
              </div>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  marginLeft: 'auto',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  color: st.color,
                }}
              >
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: 9999,
                    background: st.color,
                  }}
                />
                {st.label}
                {node.latency != null ? ` · ${node.latency}ms` : ''}
              </span>
              <button
                className="wb-iconbtn"
                style={{ width: 28, height: 28 }}
                aria-label="Close"
                onClick={onClose}
              >
                <X size={16} />
              </button>
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                flexWrap: 'wrap',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  flex: 1,
                  minWidth: 180,
                  padding: '6px 10px',
                  borderRadius: 'var(--radius-control,4px)',
                  border: '1px solid var(--border)',
                  background: 'var(--surface-lowest)',
                }}
              >
                <Search
                  size={14}
                  style={{ color: 'var(--muted-foreground)' }}
                />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Filter logs…"
                  aria-label="Filter logs"
                  data-testid="log-search-input"
                  style={{
                    flex: 1,
                    background: 'transparent',
                    border: 0,
                    outline: 'none',
                    color: 'var(--foreground)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 12,
                  }}
                />
                {q && (
                  <button
                    className="wb-iconbtn"
                    style={{ width: 22, height: 22 }}
                    aria-label="Clear"
                    onClick={() => setQ('')}
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
              <div style={{ display: 'flex', gap: 4 }} data-testid="level-tabs">
                {['all', 'INFO', 'WARN', 'ERROR'].map((lv) => (
                  <button
                    key={lv}
                    onClick={() => setLevel(lv)}
                    data-testid={`level-tab-${lv}`}
                    style={{
                      padding: '5px 9px',
                      cursor: 'pointer',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11,
                      borderRadius: 'var(--radius-control,4px)',
                      border: '1px solid',
                      borderColor:
                        level === lv
                          ? LVL_COLOR[lv] || 'var(--primary)'
                          : 'var(--border)',
                      background:
                        level === lv
                          ? `color-mix(in srgb, ${LVL_COLOR[lv] || 'var(--primary)'} 14%, transparent)`
                          : 'transparent',
                      color:
                        level === lv
                          ? LVL_COLOR[lv] || 'var(--foreground)'
                          : 'var(--muted-foreground)',
                    }}
                  >
                    {lv}
                    {lv !== 'all' && counts[lv] ? ` ${counts[lv]}` : ''}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* scrollable log body */}
          <div
            ref={scroller}
            className="wb-log"
            data-testid="log-lines"
            style={{
              flex: 1,
              height: 'auto',
              minHeight: 240,
              maxHeight: '58vh',
              border: 0,
              borderRadius: 0,
              overflow: 'auto',
              padding: '8px 18px',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
            }}
          >
            {lines.length === 0 ? (
              <div
                style={{
                  padding: 24,
                  textAlign: 'center',
                  color: 'var(--muted-foreground)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                }}
              >
                // no matching log lines
              </div>
            ) : (
              lines.map((l, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    gap: 12,
                    padding: '2px 0',
                    alignItems: 'baseline',
                  }}
                  data-testid="log-line"
                >
                  <span style={{ color: 'var(--muted-foreground)', flexShrink: 0 }}>
                    {fmt(l.t)}
                  </span>
                  <span
                    style={{
                      flexShrink: 0,
                      width: 44,
                      fontWeight: 700,
                      color: LVL_COLOR[l.level] || 'var(--muted-foreground)',
                    }}
                  >
                    {l.level}
                  </span>
                  <span
                    style={{
                      color:
                        l.level === 'ERROR'
                          ? 'var(--error-text)'
                          : 'var(--foreground)',
                    }}
                  >
                    {l.msg}
                  </span>
                </div>
              ))
            )}
          </div>

          {/* footer */}
          <div
            style={{
              padding: '8px 18px',
              borderTop: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--muted-foreground)',
            }}
            data-testid="log-footer"
          >
            <span>
              {lines.length} / {raw.length} lines
            </span>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 9999,
                  background: st.color,
                  animation: 'wb-pulse 1.6s ease infinite',
                }}
              />
              streaming
            </span>
          </div>
        </div>
      </div>
    </Portal>
  )
}

// ---- LLMCallDetail dialog ---- //
//
// Expanded view of a single LLM invocation. For batched calls a sub-call
// selector steps through each item's individual prompt / completion / structured
// output. Mirrors SystemLogViewer's dialog chrome.

function LLMCallDetail({
  call,
  onClose,
}: {
  call: LLMCall | null
  onClose: () => void
}) {
  const [openSub, setOpenSub] = useState(0)

  // Reset the sub-call selector when the open call changes.
  useEffect(() => {
    setOpenSub(0)
  }, [call?.id])

  if (!call) return null

  const st = LLM_STATUS[call.status] || LLM_STATUS.ok
  const detail = llmCallDetail(call)
  const sub = detail.subcalls[openSub] || detail.subcalls[0]

  return (
    <Portal>
      <div
        className="wb-overlay"
        style={{ alignItems: 'center', paddingTop: 0, zIndex: 120 }}
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) onClose()
        }}
        data-testid="llm-detail-overlay"
      >
        <div
          className="wb-dialog-card"
          role="dialog"
          aria-modal="true"
          aria-label={`${call.id} detail`}
          style={{
            width: 'min(760px, 95vw)',
            padding: 0,
            overflow: 'hidden',
            maxHeight: '88vh',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* header */}
          <div
            style={{
              padding: '16px 18px',
              borderBottom: '1px solid var(--border)',
              display: 'grid',
              gap: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  padding: '1px 8px',
                  borderRadius: 'var(--radius-chip,2px)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '.04em',
                  color: '#0e0e11',
                  background: LLM_STAGE_TONE[call.stage] || '#71d2ff',
                }}
                data-testid="llm-detail-stage"
              >
                {call.stage}
              </span>
              <Mono style={{ fontSize: 12, color: 'var(--foreground)' }}>{call.id}</Mono>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  color: st.color,
                }}
              >
                <span style={{ width: 7, height: 7, borderRadius: 9999, background: st.color }} />
                {st.label}
              </span>
              {call.batch > 1 && <Badge variant="secondary">batch ×{call.batch}</Badge>}
              <button
                className="wb-iconbtn"
                style={{ marginLeft: 'auto', width: 28, height: 28 }}
                aria-label="Close"
                onClick={onClose}
              >
                <X size={16} />
              </button>
            </div>
            <p style={{ margin: 0, fontSize: 15 }}>{call.purpose}</p>
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: '4px 18px',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--muted-foreground)',
              }}
            >
              <span>
                origin <span style={{ color: 'var(--tertiary)' }}>{call.origin}</span>
              </span>
              <span>
                model <span style={{ color: 'var(--foreground)' }}>{call.model}</span>
              </span>
              <span>temp {call.temperature}</span>
              <span>
                tok ↓{call.tokens_in} ↑{call.tokens_out ?? '—'}
              </span>
              <span>{call.latency_ms != null ? call.latency_ms + 'ms' : 'in flight'}</span>
              <span>{new Date(call.ts).toLocaleTimeString([], { hour12: false })}</span>
            </div>
          </div>

          {/* system prompt */}
          <div style={{ padding: '12px 18px', borderBottom: '1px solid var(--border)' }}>
            <span className="label-mono" style={{ fontSize: 10, display: 'block', marginBottom: 6 }}>
              System prompt
            </span>
            <p
              style={{
                margin: 0,
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                lineHeight: 1.5,
                color: 'var(--muted-foreground)',
              }}
            >
              {detail.sysPrompt}
            </p>
          </div>

          {/* sub-call selector (batched) */}
          {call.batch > 1 && (
            <div
              style={{
                display: 'flex',
                gap: 6,
                flexWrap: 'wrap',
                padding: '10px 18px',
                borderBottom: '1px solid var(--border)',
                background: 'var(--surface-lowest)',
              }}
              data-testid="llm-subcall-selector"
            >
              <span className="label-mono" style={{ fontSize: 10, alignSelf: 'center' }}>
                {call.batch} items batched:
              </span>
              {detail.subcalls.map((sc, i) => (
                <button
                  key={i}
                  onClick={() => setOpenSub(i)}
                  data-testid={`llm-subcall-${i}`}
                  style={{
                    padding: '3px 9px',
                    cursor: 'pointer',
                    borderRadius: 'var(--radius-control,4px)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    border: '1px solid',
                    borderColor: openSub === i ? 'var(--primary)' : 'var(--border)',
                    background:
                      openSub === i ? 'color-mix(in srgb, var(--primary) 12%, transparent)' : 'transparent',
                    color: openSub === i ? 'var(--foreground)' : 'var(--muted-foreground)',
                  }}
                >
                  {sc.item}
                </button>
              ))}
            </div>
          )}

          {/* body: input / completion / structured */}
          <div style={{ overflowY: 'auto', padding: 18, display: 'grid', gap: 14 }}>
            <div>
              <span className="label-mono" style={{ fontSize: 10, display: 'block', marginBottom: 6 }}>
                Input{call.batch > 1 ? ` · ${sub.item}` : ''}{' '}
                <span style={{ color: 'var(--muted-foreground)' }}>↓{sub.tokens_in} tok</span>
              </span>
              <pre
                style={{
                  margin: 0,
                  padding: 12,
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  lineHeight: 1.5,
                  background: 'var(--surface-lowest)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-card,6px)',
                  color: 'var(--foreground)',
                }}
              >
                {sub.prompt}
              </pre>
            </div>
            <div>
              <span className="label-mono" style={{ fontSize: 10, display: 'block', marginBottom: 6 }}>
                Completion <span style={{ color: 'var(--muted-foreground)' }}>↑{sub.tokens_out ?? '—'} tok</span>
              </span>
              <pre
                style={{
                  margin: 0,
                  padding: 12,
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  lineHeight: 1.5,
                  background: 'var(--surface-lowest)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-card,6px)',
                  color: call.status === 'error' ? 'var(--error-text)' : 'var(--foreground)',
                }}
              >
                {sub.completion}
              </pre>
            </div>
            <div>
              <span className="label-mono" style={{ fontSize: 10, display: 'block', marginBottom: 6 }}>
                Structured output
              </span>
              {sub.structured ? (
                <div
                  style={{
                    borderRadius: 'var(--radius-card,6px)',
                    border: '1px solid var(--border)',
                    overflow: 'hidden',
                  }}
                  data-testid="llm-structured-output"
                >
                  <JsonHighlight json={JSON.stringify(sub.structured, null, 2)} />
                </div>
              ) : (
                <p style={{ margin: 0, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--error-text)' }}>
                  // no structured output — call failed
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </Portal>
  )
}

// ---- LLMInfra component ---- //
//
// A live-tailing log of every LLM invocation, with stat rollups. New rows
// stream in (pausable) and flash on arrival; clicking a row opens its detail.

function LLMInfra({ pool = DEFAULT_LLM_CALLS }: { pool?: LLMCall[] }) {
  const [rows, setRows] = useState<LLMCall[]>(() => pool.slice(0, 14))
  const [live, setLive] = useState(true)
  const [detail, setDetail] = useState<LLMCall | null>(null)
  const [q, setQ] = useState('')
  const cursor = useRef(14)
  const scroller = useRef<HTMLDivElement>(null)

  // Stream a new synthetic row in every ~1.9s while live.
  useEffect(() => {
    if (!live) return undefined
    const id = setInterval(() => {
      setRows((prev) => {
        const base = pool[cursor.current % pool.length]
        cursor.current += 1
        const row: LLMCall = {
          ...base,
          id: 'llm_' + (94250 + cursor.current),
          ts: new Date().toISOString(),
        }
        return [...prev, row].slice(-80)
      })
    }, 1900)
    return () => clearInterval(id)
  }, [live, pool])

  // Auto-scroll to the newest row while live.
  useEffect(() => {
    const el = scroller.current
    if (el && live) el.scrollTop = el.scrollHeight
  }, [rows, live])

  const query = q.trim().toLowerCase()
  const shown = query
    ? rows.filter((c) =>
        (c.origin + ' ' + c.purpose + ' ' + c.stage + ' ' + c.items.join(' ') + ' ' + c.model)
          .toLowerCase()
          .includes(query),
      )
    : rows

  const withLatency = pool.filter((c) => c.latency_ms != null)
  const calls24 = pool.length * 47
  const errRate = Math.round((pool.filter((c) => c.status === 'error').length / pool.length) * 100)
  const avgMs = Math.round(
    withLatency.reduce((s, c) => s + (c.latency_ms ?? 0), 0) / Math.max(1, withLatency.length),
  )
  const batched = Math.round((pool.filter((c) => c.batch > 1).length / pool.length) * 100)
  const fmt = (iso: string) => new Date(iso).toLocaleTimeString([], { hour12: false })

  const COLS = '64px 88px minmax(0,1fr) 60px 96px 64px'

  return (
    <div style={{ display: 'grid', gap: 16 }} data-testid="llm-infra">
      <div
        className="grid grid-cols-4 gap-4"
        data-testid="llm-stat-cards"
      >
        <StatCard label="Calls (24h)" value={<Mono>{calls24.toLocaleString()}</Mono>} />
        <StatCard label="Avg Latency" value={<Mono>{avgMs}ms</Mono>} />
        <StatCard label="Error Rate" value={<Mono>{errRate}%</Mono>} danger={errRate > 3} />
        <StatCard label="Batched" value={<Mono>{batched}%</Mono>} />
      </div>

      <Card>
        <CardHeader
          divided
          className="flex flex-row items-center justify-between gap-2.5 px-4 py-3"
        >
          <CardTitle className="wb-section-h">LLM Invocation Log</CardTitle>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 7,
                padding: '4px 9px',
                borderRadius: 'var(--radius-control,4px)',
                border: '1px solid var(--border)',
                background: 'var(--surface-lowest)',
              }}
            >
              <Search size={13} style={{ color: 'var(--muted-foreground)' }} />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="filter…"
                aria-label="Filter LLM calls"
                data-testid="llm-search-input"
                style={{
                  width: 120,
                  background: 'transparent',
                  border: 0,
                  outline: 'none',
                  color: 'var(--foreground)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                }}
              />
            </div>
            <button
              onClick={() => setLive((v) => !v)}
              aria-pressed={live}
              data-testid="llm-live-toggle"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 10px',
                cursor: 'pointer',
                borderRadius: 'var(--radius-control,4px)',
                border: '1px solid var(--border)',
                background: live ? 'color-mix(in srgb, var(--success) 12%, transparent)' : 'transparent',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: live ? 'var(--success)' : 'var(--muted-foreground)',
              }}
            >
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: 9999,
                  background: live ? 'var(--success)' : 'var(--muted-foreground)',
                  animation: live ? 'wb-pulse 1.6s ease infinite' : 'none',
                }}
              />
              {live ? 'live' : 'paused'}
              {live ? <Pause size={11} /> : <Play size={11} />}
            </button>
          </div>
        </CardHeader>
        <CardContent style={{ padding: 0 }}>
          {/* column header */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: COLS,
              gap: 8,
              alignItems: 'center',
              padding: '8px 16px',
              borderBottom: '1px solid var(--border)',
              background: 'var(--surface-high)',
            }}
          >
            {['Time', 'Origin', 'Purpose', 'Batch', 'Tokens', 'Status'].map((h, i) => (
              <span key={h} className="label-mono" style={{ fontSize: 10, textAlign: i >= 3 ? 'right' : 'left' }}>
                {h}
              </span>
            ))}
          </div>
          <div
            ref={scroller}
            className="wb-log"
            data-testid="llm-log-lines"
            style={{ height: 360, padding: 0, border: 0, borderRadius: 0, fontFamily: 'var(--font-sans)' }}
          >
            {shown.length === 0 ? (
              <div
                style={{
                  padding: 24,
                  textAlign: 'center',
                  color: 'var(--muted-foreground)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                }}
              >
                // no matching LLM calls
              </div>
            ) : (
              shown.map((c, ri) => {
                const st = LLM_STATUS[c.status] || LLM_STATUS.ok
                const newest = ri === shown.length - 1
                return (
                  <button
                    key={c.id}
                    onClick={() => setDetail(c)}
                    className={newest && live ? 'wb-tail-new' : ''}
                    title={`Open ${c.id}`}
                    data-testid="llm-log-row"
                    style={{
                      display: 'grid',
                      gridTemplateColumns: COLS,
                      gap: 8,
                      alignItems: 'center',
                      width: '100%',
                      textAlign: 'left',
                      padding: '7px 16px',
                      background: 'transparent',
                      border: 0,
                      borderBottom: '1px solid color-mix(in srgb, var(--border) 55%, transparent)',
                      cursor: 'pointer',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'var(--accent)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'transparent'
                    }}
                  >
                    <Mono style={{ fontSize: 11, color: 'var(--muted-foreground)' }}>{fmt(c.ts)}</Mono>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, minWidth: 0 }}>
                      <span
                        style={{
                          width: 6,
                          height: 6,
                          borderRadius: 2,
                          background: LLM_STAGE_TONE[c.stage] || '#71d2ff',
                          flexShrink: 0,
                        }}
                      />
                      <Mono
                        style={{
                          fontSize: 11,
                          color: 'var(--tertiary)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {c.origin}
                      </Mono>
                    </span>
                    <span
                      style={{
                        fontSize: 13,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        color: 'var(--foreground)',
                      }}
                    >
                      {c.purpose}
                    </span>
                    <span style={{ textAlign: 'right' }}>
                      {c.batch > 1 ? (
                        <Mono style={{ fontSize: 11, color: 'var(--brand)' }}>×{c.batch}</Mono>
                      ) : (
                        <span style={{ color: 'var(--muted-foreground)' }}>—</span>
                      )}
                    </span>
                    <Mono style={{ fontSize: 11, textAlign: 'right', color: 'var(--muted-foreground)' }}>
                      ↓{c.tokens_in} ↑{c.tokens_out ?? '·'}
                    </Mono>
                    <span
                      style={{
                        justifySelf: 'end',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 5,
                        fontFamily: 'var(--font-mono)',
                        fontSize: 11,
                        color: st.color,
                      }}
                    >
                      <span style={{ width: 6, height: 6, borderRadius: 9999, background: st.color }} />
                      {st.label}
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </CardContent>
      </Card>

      <LLMCallDetail call={detail} onClose={() => setDetail(null)} />
    </div>
  )
}

// ---- Main page component ---- //

function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401
}

export function SystemStatus() {
  const health = useHealth()
  const [logNode, setLogNode] = useState<SystemNode | null>(null)
  const [tab, setTab] = useState<'diagram' | 'llm'>('diagram')

  // In a real implementation these would come from an API hook.
  // For now use the built-in defaults.
  const systemData = DEFAULT_SYSTEM_STATUS
  const systemLogs = DEFAULT_SYSTEM_LOGS

  // Derive page-level states from the health query
  const isUnauth = health.isError && isUnauthorized(health.error)

  if (isUnauth) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-10 text-center text-muted-foreground">
        <p className="text-lg font-medium">token unavailable</p>
        <p className="text-sm">
          Check that the SSH tunnel is up and the server is bound to loopback.
        </p>
      </div>
    )
  }

  if (health.isPending) {
    return (
      <div data-testid="system-loading" className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-96" />
      </div>
    )
  }

  if (health.isError) {
    const reqId =
      health.error instanceof ApiError ? health.error.requestId : null
    return (
      <div className="p-6 text-destructive" data-testid="system-error">
        <p>Failed to load system status: {(health.error as Error).message}</p>
        {reqId && (
          <p className="text-xs">Request ID: {reqId}</p>
        )}
      </div>
    )
  }

  const all = systemData.nodes
  const up = all.filter((n) => n.status === 'healthy').length
  const deg = all.filter((n) => n.status === 'degraded').length
  const down = all.filter((n) => n.status === 'unhealthy').length
  const live = all.filter((n) => n.status !== 'disabled' && n.status !== 'planned').length
  const overall = down > 0 ? 'unhealthy' : deg > 0 ? 'degraded' : 'healthy'
  const ov = SYS_STATUS[overall]
  const conns = all.filter((n) => n.role === 'connector')
  const isDegraded = deg > 0

  return (
    <div className="space-y-5 wb-enter" data-testid="system-status-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">System Status</h1>
          <p className="text-sm text-muted-foreground">
            Live map of every connector, service, and store. Data flows left
            &rarr; right into WorkBench; replies flow back out through two-way
            connectors.
          </p>
        </div>
        <span
          className="inline-flex items-center gap-2 rounded-md px-3 py-1.5"
          style={{
            border: `1px solid color-mix(in srgb, ${ov.color} 45%, transparent)`,
            background: `color-mix(in srgb, ${ov.color} 12%, transparent)`,
          }}
          data-testid="overall-status"
        >
          <span
            className="size-2 rounded-full"
            style={{
              background: ov.color,
              animation: 'wb-pulse 1.6s ease infinite',
            }}
          />
          <Mono className="text-xs font-bold uppercase tracking-wider" style={{ color: ov.color }}>
            {ov.label}
          </Mono>
        </span>
      </div>

      <div className="grid grid-cols-4 gap-4" data-testid="stat-cards">
        <StatCard label="Operational" value={`${up}/${live}`} />
        <StatCard label="Degraded" value={deg} danger={deg > 0} />
        <StatCard label="Connectors" value={conns.length} />
        <StatCard
          label="Config Version"
          value={<Mono>{systemData.summary.version}</Mono>}
        />
      </div>

      {/* Sub-view tabs: the system diagram vs the LLM infra invocation log. */}
      <div
        className="flex gap-1.5 border-b border-border"
        role="tablist"
        data-testid="system-tabs"
      >
        {([
          ['diagram', 'System Diagram', Network],
          ['llm', 'LLM Infra', Sparkles],
        ] as const).map(([key, label, IconComp]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            data-testid={`system-tab-${key}`}
            className="-mb-px inline-flex cursor-pointer items-center gap-1.5 border-0 bg-transparent px-3.5 py-2.5 font-mono text-xs font-semibold uppercase tracking-wider"
            style={{
              borderBottom: `2px solid ${tab === key ? 'var(--primary)' : 'transparent'}`,
              color: tab === key ? 'var(--foreground)' : 'var(--muted-foreground)',
            }}
          >
            <IconComp size={14} />
            {label}
          </button>
        ))}
      </div>

      {tab === 'llm' ? (
        <LLMInfra />
      ) : (
        <>
      {isDegraded && (
        <div
          role="status"
          className="flex items-center gap-2.5 rounded-md border px-3.5 py-2.5 text-sm"
          style={{
            borderColor: 'color-mix(in srgb, var(--primary) 45%, transparent)',
            background: 'color-mix(in srgb, var(--primary) 8%, transparent)',
          }}
          data-testid="degraded-banner"
        >
          <TriangleAlert size={15} style={{ color: 'var(--brand)' }} />
          <span>
            Memory layer (Zep) is degraded — preference-fact writes are queued.
            Triage and ingestion are unaffected.
          </span>
        </div>
      )}

      <Card>
        <CardHeader className="border-b border-border px-4 py-3.5">
          <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
            System Diagram
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4">
          <SystemDiagram
            data={systemData}
            onSelect={(id) =>
              setLogNode(id ? all.find((n) => n.id === id) ?? null : null)
            }
            selectedId={logNode?.id ?? null}
          />
          {/* Legend */}
          <div
            className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border pt-3"
            data-testid="diagram-legend"
          >
            {Object.entries(ROLE_TONE).map(([role, tone]) => (
              <span
                key={role}
                className="inline-flex items-center gap-1.5 text-[11px] capitalize text-muted-foreground"
              >
                <span
                  className="size-2.5 rounded-sm"
                  style={{ background: tone }}
                  data-testid={`legend-${role}`}
                />
                {role}
              </span>
            ))}
            <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span
                style={{
                  width: 14,
                  height: 0,
                  borderTop: '1.5px dashed #b79cf7',
                }}
              />
              reply path
            </span>
            <span
              className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground"
              data-testid="legend-planned"
            >
              <span
                className="size-2.5 rounded-sm"
                style={{ border: '1px dashed var(--muted-foreground)' }}
              />
              planned &middot; not live
            </span>
            <span className="ml-auto font-mono text-[11px] text-muted-foreground">
              click a node to view its logs
            </span>
          </div>
        </CardContent>
      </Card>
        </>
      )}

      <SystemLogViewer
        node={logNode}
        logs={systemLogs}
        onClose={() => setLogNode(null)}
      />
    </div>
  )
}

// ---- Compact summary widget for Overview page ---- //

export function SystemStatusSummary() {
  const systemData = DEFAULT_SYSTEM_STATUS

  const byRole: Record<string, { total: number; healthy: number }> = {}
  for (const n of systemData.nodes) {
    const lane = systemData.lanes[n.lane] ?? 'Other'
    if (!byRole[lane]) byRole[lane] = { total: 0, healthy: 0 }
    byRole[lane].total++
    if (n.status === 'healthy') byRole[lane].healthy++
  }

  return (
    <Card data-testid="system-summary-widget">
      <CardHeader className="pb-2">
        <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
          System Status
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-3">
          {Object.entries(byRole).map(([lane, { total, healthy }]) => (
            <span
              key={lane}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 font-mono text-xs"
            >
              <span
                className="size-1.5 rounded-full"
                style={{
                  background:
                    healthy === total ? '#9ad08a' : '#f5a623',
                }}
              />
              {lane}:{' '}
              <strong>
                {healthy}/{total}
              </strong>
            </span>
          ))}
        </div>
        <Link
          to="/system"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          data-testid="system-diagram-link"
        >
          View system diagram &rarr;
        </Link>
      </CardContent>
    </Card>
  )
}

// Re-export for testing
export {
  DEFAULT_SYSTEM_STATUS,
  DEFAULT_SYSTEM_LOGS,
  SYS_STATUS,
  ROLE_TONE,
  DEFAULT_LLM_CALLS,
  LLM_STATUS,
  LLM_STAGE_TONE,
  llmCallDetail,
  LLMInfra,
}
