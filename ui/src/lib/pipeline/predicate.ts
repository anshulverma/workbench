// predicate.ts — render predicates / condition-trees to text, plus the immutable
// tree-edit helpers the RuleBuilderDialog uses. Pure; no React.

import type { Condition, ConditionGroup, ConditionTree, EdgePredicate } from '../types/pipeline'
import { allowedFields, field, OP_LABEL } from './schema'

export function isGroup(n: ConditionTree | EdgePredicate | undefined): n is ConditionGroup {
  return !!n && 'op' in n && (n.op === 'AND' || n.op === 'OR' || n.op === 'NOT')
}

function valueText(v: unknown): string {
  if (Array.isArray(v)) return `[${v.join(', ')}]`
  if (typeof v === 'string') return v
  return String(v)
}

/** Short label for an edge badge or a leaf condition. */
export function predicateBadgeText(pred: EdgePredicate | undefined): string {
  if (!pred || (('op' in pred) && pred.op === 'always')) return 'always'
  if (isGroup(pred)) return condText(pred)
  const c = pred as Condition
  const f = field(c.field)
  const op = OP_LABEL[c.operator] || c.operator
  return `${f ? f.label : c.field} ${op} ${valueText(c.value)}`.trim()
}

/** Recursive plain-text rendering of a condition tree. */
export function condText(node: ConditionTree | EdgePredicate | undefined): string {
  if (!node) return ''
  if ('op' in node && node.op === 'always') return 'always'
  if (isGroup(node)) {
    if (node.op === 'NOT') return `not ${condText(node.children[0])}`
    const joiner = node.op === 'AND' ? ' and ' : ' or '
    return node.children
      .map((c) => (isGroup(c) ? `(${condText(c)})` : condText(c)))
      .join(joiner)
  }
  return predicateBadgeText(node as Condition)
}

export function ruleSentence(tree: ConditionTree, action: string): string {
  const verb = action === 'include' ? 'Include' : action === 'route' ? 'Route' : 'Drop'
  return `${verb} when ${condText(tree)}.`
}

// ---- immutable tree edits (path = array of child indices) ----
export function setAt(tree: ConditionTree, path: number[], fn: (n: ConditionTree) => ConditionTree): ConditionTree {
  if (!path.length) return fn(tree)
  if (!isGroup(tree)) return tree
  const [i, ...rest] = path
  const children = tree.children.slice()
  children[i] = setAt(children[i], rest, fn)
  return { ...tree, children }
}

export function removeAt(tree: ConditionTree, path: number[]): ConditionTree {
  const idx = path[path.length - 1]
  return setAt(tree, path.slice(0, -1), (g) =>
    isGroup(g) ? { ...g, children: g.children.filter((_, k) => k !== idx) } : g,
  )
}

export function newCondition(segment: 'pre' | 'post' | 'both'): Condition {
  const f = allowedFields(segment)[0]
  return { field: f.key, operator: f.operators[0], value: f.type === 'bool' ? true : '' }
}

/** Normalize an edge predicate to an editable tree (always → starter group). */
export function toTree(pred: EdgePredicate | undefined, segment: 'pre' | 'post' | 'both'): ConditionTree {
  if (!pred || ('op' in pred && pred.op === 'always')) return { op: 'AND', children: [newCondition(segment)] }
  if (isGroup(pred)) return pred
  return { op: 'AND', children: [pred as Condition] }
}

/** Collect every field key referenced anywhere in a predicate (for validation). */
export function collectFields(pred: EdgePredicate | ConditionTree | undefined, acc: string[] = []): string[] {
  if (!pred) return acc
  if ('op' in pred && pred.op === 'always') return acc
  if (isGroup(pred)) {
    pred.children.forEach((c) => collectFields(c, acc))
    return acc
  }
  const c = pred as Condition
  if (c.field) acc.push(c.field)
  return acc
}
