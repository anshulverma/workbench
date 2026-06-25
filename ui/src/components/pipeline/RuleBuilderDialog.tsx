// RuleBuilderDialog — the nested AND/OR/NOT condition-tree builder, reused for
// rule_filter, pre_filter, and edge predicates. Field/operator/value controls
// are driven by FIELD_SCHEMA; a live plain-English preview comes from
// ruleSentence(). Tree edits use the immutable helpers in lib/pipeline/predicate.

import { useState, type ReactNode } from 'react'
import { FolderPlus, MessageSquareText, Plus, Trash2, type LucideIcon } from 'lucide-react'
import { SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { allowedFields, field, OP_LABEL } from '@/lib/pipeline/schema'
import { isGroup, newCondition, removeAt, ruleSentence, setAt } from '@/lib/pipeline/predicate'
import type { Condition, ConditionGroup, ConditionTree } from '@/lib/types/pipeline'
import { Field, PanelShell, PipelineDialog, Segmented, type SegmentedOption } from './DialogShell'

type Segment = 'pre' | 'post' | 'both'

/* ---- adaptive value input ---- */
function ValueInput({
  cond,
  onChange,
  invalid,
}: {
  cond: Condition
  onChange: (v: unknown) => void
  invalid?: boolean
}) {
  const f = field(cond.field)
  if (!f) return null
  const t = f.type
  const op = cond.operator
  if (t === 'bool' || op === 'exists') {
    return <span className="self-center text-muted-foreground" style={{ fontSize: 12 }}>—</span>
  }
  if (f.enum_values && (op === 'in' || op === 'not_in')) {
    const sel = Array.isArray(cond.value) ? (cond.value as string[]) : []
    return (
      <div className="flex flex-wrap gap-1">
        {f.enum_values.map((v) => {
          const on = sel.includes(v)
          return (
            <button
              key={v}
              type="button"
              onClick={() => onChange(on ? sel.filter((x) => x !== v) : [...sel, v])}
              className="cursor-pointer rounded-[var(--radius-chip)] px-2 py-[2px] font-mono"
              style={{
                fontSize: 11,
                border: `1px solid ${on ? 'var(--primary)' : invalid ? 'var(--destructive)' : 'var(--border)'}`,
                background: on ? 'color-mix(in srgb, var(--primary) 20%, transparent)' : 'var(--surface-lowest)',
                color: on ? 'var(--brand)' : 'var(--muted-foreground)',
              }}
            >
              {v}
            </button>
          )
        })}
      </div>
    )
  }
  if (f.enum_values) {
    const val = typeof cond.value === 'string' && cond.value ? cond.value : undefined
    return (
      <Select value={val} onValueChange={(v) => onChange(v)}>
        <SelectTrigger className={cn('h-8', invalid && 'border-destructive ring-1 ring-destructive')}>
          <SelectValue placeholder="choose…" />
        </SelectTrigger>
        <SelectContent>
          {f.enum_values.map((v) => (
            <SelectItem key={v} value={v}>
              {v}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }
  if (t === 'int' || t === 'float' || op === 'within_hours' || op === 'len_gt') {
    return (
      <Input
        type="number"
        mono
        value={(cond.value as number | string) ?? ''}
        className={cn('h-8', invalid && 'border-destructive ring-1 ring-destructive')}
        placeholder={op === 'within_hours' ? 'hours' : '0'}
        onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
      />
    )
  }
  return (
    <Input
      value={(cond.value as string) ?? ''}
      className={cn('h-8', op === 'matches' && 'font-mono', invalid && 'border-destructive ring-1 ring-destructive')}
      placeholder={op === 'matches' ? '/regex/' : 'value'}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

/* ---- a single leaf condition row: field · operator · value · remove ---- */
function ConditionRow({
  cond,
  segment,
  path,
  onEdit,
  onRemove,
  invalid,
}: {
  cond: Condition
  segment: Segment
  path: number[]
  onEdit: (path: number[], value: Condition) => void
  onRemove: (path: number[]) => void
  invalid?: boolean
}) {
  const f = field(cond.field)
  const fields = allowedFields(segment)
  const uni = fields.filter((x) => x.segment === 'both')
  const stg = fields.filter((x) => x.segment !== 'both')
  const changeField = (key: string) => {
    const nf = field(key)
    if (!nf) return
    onEdit(path, { field: key, operator: nf.operators[0], value: nf.type === 'bool' ? true : '' })
  }
  const ops = f ? f.operators : []
  return (
    <div
      className="grid items-center gap-1.5"
      style={{ gridTemplateColumns: 'minmax(96px,1fr) auto minmax(120px,1.2fr) auto' }}
    >
      <Select value={cond.field} onValueChange={changeField}>
        <SelectTrigger className="h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Universal</SelectLabel>
            {uni.map((x) => (
              <SelectItem key={x.key} value={x.key}>
                {x.label}
              </SelectItem>
            ))}
          </SelectGroup>
          {stg.length > 0 && (
            <SelectGroup>
              <SelectLabel>Stage fields</SelectLabel>
              {stg.map((x) => (
                <SelectItem key={x.key} value={x.key}>
                  {x.label}
                </SelectItem>
              ))}
            </SelectGroup>
          )}
        </SelectContent>
      </Select>
      <Select value={cond.operator} onValueChange={(v) => onEdit(path, { ...cond, operator: v })}>
        <SelectTrigger className="h-8 min-w-16">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ops.map((o) => (
            <SelectItem key={o} value={o}>
              {OP_LABEL[o] || o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <ValueInput cond={cond} invalid={invalid} onChange={(v) => onEdit(path, { ...cond, value: v })} />
      <button className="wb-iconbtn" onClick={() => onRemove(path)} aria-label="Remove condition" style={{ width: 28, height: 28 }}>
        <Trash2 size={14} />
      </button>
    </div>
  )
}

/* ---- a boolean group (AND/OR/NOT) with its children ---- */
function GroupNode({
  group,
  segment,
  path,
  onEdit,
  onRemove,
  depth,
  errors,
}: {
  group: ConditionGroup
  segment: Segment
  path: number[]
  onEdit: (path: number[], fn: (n: ConditionTree) => ConditionTree) => void
  onRemove: (path: number[]) => void
  depth: number
  errors?: Set<string>
}) {
  const isNot = group.op === 'NOT'
  const accent = group.op === 'AND' ? 'var(--primary)' : group.op === 'OR' ? 'var(--tertiary)' : 'var(--brand)'
  return (
    <div
      className="grid gap-2"
      style={{
        padding: depth ? '10px 10px 10px 12px' : 0,
        borderLeft: depth ? `2px solid ${accent}` : 'none',
        borderRadius: depth ? 6 : 0,
        background: depth ? 'color-mix(in srgb, var(--card) 60%, transparent)' : 'transparent',
        marginLeft: depth ? 4 : 0,
      }}
    >
      <div className="flex items-center gap-2">
        <Segmented
          value={group.op}
          onChange={(op) =>
            onEdit(path, (g) => {
              const grp = g as ConditionGroup
              if (op === 'NOT') return { op, children: [grp.children[0] || newCondition(segment)] }
              return { op: op as 'AND' | 'OR', children: grp.children }
            })
          }
          options={[
            { value: 'AND', label: 'All' },
            { value: 'OR', label: 'Any' },
            { value: 'NOT', label: 'Not' },
          ]}
        />
        <span className="text-muted-foreground" style={{ fontSize: 11 }}>
          {group.op === 'AND' ? 'match every rule' : group.op === 'OR' ? 'match any rule' : 'invert the rule'}
        </span>
        {depth > 0 && (
          <button className="wb-iconbtn ml-auto" onClick={() => onRemove(path)} aria-label="Remove group" style={{ width: 26, height: 26 }}>
            <Trash2 size={14} />
          </button>
        )}
      </div>
      <div className="grid gap-[7px]">
        {group.children.map((c, i) => {
          const cp = [...path, i]
          const key = cp.join('-')
          return (
            <div key={key} className="grid gap-[7px]">
              {i > 0 && (
                <span className="font-mono uppercase tracking-[0.08em] pl-0.5" style={{ fontSize: 9.5, color: accent }}>
                  {group.op === 'OR' ? 'or' : group.op === 'NOT' ? '' : 'and'}
                </span>
              )}
              {isGroup(c) ? (
                <GroupNode group={c} segment={segment} path={cp} onEdit={onEdit} onRemove={onRemove} depth={depth + 1} errors={errors} />
              ) : (
                <ConditionRow
                  cond={c}
                  segment={segment}
                  path={cp}
                  invalid={errors?.has(key)}
                  onEdit={(p, v) => onEdit(p, () => v)}
                  onRemove={onRemove}
                />
              )}
            </div>
          )
        })}
      </div>
      {!(isNot && group.children.length >= 1) && (
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={() => onEdit(path, (g) => ({ ...(g as ConditionGroup), children: [...(g as ConditionGroup).children, newCondition(segment)] }))}
            className="inline-flex cursor-pointer items-center gap-[5px] rounded border border-dashed border-border bg-transparent px-[9px] py-1 text-muted-foreground"
            style={{ fontSize: 12 }}
          >
            <Plus size={13} /> Condition
          </button>
          {!isNot && (
            <button
              type="button"
              onClick={() =>
                onEdit(path, (g) => ({
                  ...(g as ConditionGroup),
                  children: [...(g as ConditionGroup).children, { op: 'OR', children: [newCondition(segment)] } as ConditionGroup],
                }))
              }
              className="inline-flex cursor-pointer items-center gap-[5px] rounded border border-dashed border-border bg-transparent px-[9px] py-1 text-muted-foreground"
              style={{ fontSize: 12 }}
            >
              <FolderPlus size={13} /> Group
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export interface RuleBuilderDialogProps {
  initialTree?: ConditionTree
  action?: string
  actionOptions?: SegmentedOption[]
  segment?: Segment
  title?: string
  kicker?: string
  icon?: LucideIcon
  tone?: string
  banner?: ReactNode
  onClose: () => void
  onSave?: (tree: ConditionTree, action: string) => void
  onDelete?: () => void
  errors?: Set<string>
  footerNote?: string
  bodyMax?: string
}

export function RuleBuilderDialog({
  initialTree,
  action = 'drop',
  actionOptions,
  segment = 'post',
  title = 'Rule filter',
  kicker = 'RULE.FILTER',
  icon = SlidersHorizontal,
  tone = 'var(--brand)',
  banner,
  onClose,
  onSave,
  onDelete,
  errors,
  footerNote,
  bodyMax,
}: RuleBuilderDialogProps) {
  const [tree, setTree] = useState<ConditionTree>(
    initialTree || ({ op: 'AND', children: [newCondition(segment)] } as ConditionGroup),
  )
  const [act, setAct] = useState(action)
  const edit = (path: number[], fn: (n: ConditionTree) => ConditionTree) =>
    setTree((t) => setAt(t, path, (n) => fn(n)))
  const remove = (path: number[]) => {
    if (!path.length) return
    setTree((t) => removeAt(t, path))
  }
  const opts = actionOptions || [
    { value: 'drop', label: 'Drop' },
    { value: 'include', label: 'Include' },
  ]
  const hasErr = !!errors && errors.size > 0
  const rootGroup = isGroup(tree) ? tree : ({ op: 'AND', children: [tree] } as ConditionGroup)

  return (
    <PipelineDialog width={560} onClose={onClose}>
      <PanelShell
        icon={icon}
        tone={tone}
        kicker={kicker}
        title={title}
        banner={banner}
        bodyMax={bodyMax}
        footer={
          <>
            {footerNote && (
              <span
                className="mr-auto font-mono"
                style={{ fontSize: 11, color: hasErr ? 'var(--error-text)' : 'var(--muted-foreground)' }}
              >
                {footerNote}
              </span>
            )}
            {onDelete && (
              <Button variant="ghost" size="sm" onClick={onDelete}>
                <span className="inline-flex items-center gap-[5px]" style={{ color: 'var(--error-text)' }}>
                  <Trash2 size={13} /> Delete route
                </span>
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" disabled={hasErr} onClick={() => { onSave?.(tree, act); onClose() }}>
              Save rule
            </Button>
          </>
        }
      >
        {opts.length > 1 && (
          <Field label="Action" hint="what happens when the rule matches">
            <Segmented value={act} onChange={setAct} options={opts} />
          </Field>
        )}
        <Field label="Conditions">
          <GroupNode group={rootGroup} segment={segment} path={[]} onEdit={edit} onRemove={remove} depth={0} errors={errors} />
        </Field>
        <div className="flex items-start gap-2 rounded-md border border-border bg-[var(--surface-lowest)] px-3 py-2.5">
          <MessageSquareText size={14} style={{ color: 'var(--tertiary)', marginTop: 2, flexShrink: 0 }} />
          <p className="m-0 leading-[1.5] text-foreground" style={{ fontSize: 13 }}>
            {ruleSentence(rootGroup, act)}
          </p>
        </div>
      </PanelShell>
    </PipelineDialog>
  )
}
