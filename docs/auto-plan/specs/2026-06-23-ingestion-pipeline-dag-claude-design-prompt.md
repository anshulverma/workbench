# Claude Design prompt — Ingestion Pipeline DAG builder & diagram

Paste the block below into the Claude Design tool. It is self-contained: it describes the
product, the exact components to design, their props/states, the data shapes, and the visual
system. Companion spec (for engineers, not needed by the designer):
`docs/auto-plan/specs/2026-06-23-ingestion-pipeline-dag-design.md`.

---

## PROMPT START

Design a **Pipeline** sub-tab for the "Ingestion" page of **Workbench**, a single-user
personal intelligence-feed dashboard. The tab is both a **live visualization** and an
**editor** for a routing DAG that controls how incoming items (diffs, tasks, emails, chat,
calendar, GitHub) flow through filtering and enrichment before reaching triage.

### Visual system (match the existing app exactly)
- **Dark mode**, shadcn/ui components, Tailwind v4, React 19, lucide-react icons.
- Muted, dense, information-rich "mission control" aesthetic; monospace for numbers/IDs.
- Existing primitives to reuse: Card, Dialog, Select, Switch, Badge, Button, Tabs, Table,
  DropdownMenu, Tooltip, Input, Label, Skeleton, Sonner (toasts). Existing app components:
  StatCard, Mono, SectionHeader, ConfidenceBar, SourceChip, EmptyState, Breadcrumb.
- Diagrams in this app are **hand-rolled SVG** (no React Flow / D3 / mermaid). Design the
  canvas as SVG nodes + edges, styleable with Tailwind classes / CSS variables.

### Information architecture
The Ingestion page gains a `Tabs` header: **Overview** (existing content) | **Pipeline**
(new). Design only the **Pipeline** tab. It contains, top to bottom:
1. A toolbar row: title, a "validate" status pill, "Add stage" button, "Save" button
   (disabled until dirty), and a legend toggle.
2. The **PipelineCanvas** (the DAG), filling most of the tab.
3. A collapsible **accessible fallback table** below (nodes + edges + predicates), for a11y
   and quick scanning.

### Components to design (give each: layout, all states, and how props render)

**1. PipelineCanvas** — left-to-right SVG DAG.
- Lanes/zones (subtle vertical bands with labels): **Source** → **Pre-extraction**
  (pre_filter nodes) → **Extraction** (the mandatory articulation node every path crosses)
  → **Post-extraction** (rule/llm/enricher nodes, can diverge & re-converge) → **Sinks**
  (Triage, Auto-include, Drop).
- Nodes positioned by stored `ui_x`/`ui_y`; edges are curved connectors. Show diverge
  (one node → many edges) and converge (many → one) cleanly, including re-divergence after a
  shared node.
- Interactions: select a node (highlight + open its config dialog), drag a node to reposition,
  drag from a node's output port to another node to create an edge, click an edge to edit its
  predicate / reorder / delete, pan + zoom. Hovering a node dims unrelated nodes/edges
  (focus mode, like the app's existing SourceFlow). Reduced-motion friendly.
- States: loading (skeleton graph), empty/default-graph, valid, **invalid** (validation
  errors overlaid on offending nodes/edges with red outlines + a problems popover), dirty
  (unsaved), read-only reserved nodes.

**2. StageNode** — one component, variants by `type`:
`source`, `extraction`, `sink` (roles: drop/auto_include/triage), `pre_filter`,
`rule_filter`, `llm_filter`, `enricher`. (A `loopback` variant exists but is **disabled /
"coming soon"** — show it greyed in the Add-stage menu only.)
- Each node card shows: a type icon, a label, an enabled Switch (hidden/locked on reserved
  nodes), `source_scope` chips (e.g. "diff", "task", or "all"), and **live funnel counts**:
  entered / dropped / passed (small monospace, with a sparkline-ish micro bar optional).
- Reserved nodes (source/extraction/sinks) look distinct (heavier border, lock glyph, no
  delete, no source_scope, always-on).
- States: default, selected, hovered, disabled (enabled=false → dimmed), error (red ring),
  reserved (locked). Sinks are color-coded: Triage (amber/neutral), Auto-include (green),
  Drop (red/muted).

**3. EdgePredicateBadge** — a small pill on each edge showing its route predicate, e.g.
`type == diff`, `relevance < 40`, or `always` (default edge, rendered subtly). Clicking
opens the predicate editor (a condition-tree builder, same as RuleBuilderDialog but for an
edge). Show edge evaluation order (1, 2, 3 …) since first-match-wins.

**4. RuleBuilderDialog** — the nested boolean condition-tree builder (the centerpiece). Used
for `rule_filter`, `pre_filter`, and edge predicates.
- A tree of **groups** (AND / OR / NOT) containing **conditions** (`field` `operator`
  `value`) and nested sub-groups. NOT has exactly one child.
- Each condition row: a **Field** Select (populated from a backend field schema — group
  options by "Universal" vs the source type's fields; show field type as a hint), an
  **Operator** Select (filtered to operators valid for the chosen field's type), and a
  **Value** input that adapts to the field type (text, number, boolean toggle, enum
  multi-select for `in`/`not_in`, a regex input for `matches`, an hours number for
  `within_hours`).
- Controls: add condition, add sub-group, switch a group's AND/OR/NOT, remove, drag to
  reorder. Visual nesting with indentation + connector lines + AND/OR labels between rows.
- A live **plain-English preview** of the rule (e.g. "Drop when type is diff AND status is
  draft AND author is one of [foo, bar]").
- An **action** selector at the top: for rule_filter → Drop / Include; for pre_filter →
  Drop only (Include hidden); edges have no action (they route).
- States: empty (one starter condition), valid, invalid (inline field/operator/value errors
  + a disabled Save), loading the field schema, server 422 → map errors back to rows.

**5. EnricherConfigDialog** — configure an `enricher` node: provider Select (from the
registry), `source_scope` multi-select, **depth** (Shallow / Deep segmented control),
**budget** (max API calls number, max seconds number), enabled Switch. Show a small note of
recent run stats (avg ms, calls) if available. States: create vs edit, valid/invalid, saving.

**6. PreFilterDialog** — a thin wrapper around RuleBuilderDialog scoped to the
pre-extraction field set (only fields available before extraction), action locked to Drop,
with a banner: "Runs before any LLM call — drops here cost nothing."

**7. LlmFilterDialog** — configure an `llm_filter` node: optional threshold overrides
(include / drop / confidence sliders or number inputs, defaulting to global 70 / 30 / 70),
and an optional prompt-override textarea. States: defaults vs overridden, valid/invalid.

**8. Accessible fallback table** — rows = nodes (type, label, scope, enabled, counts) and a
nested or adjacent edges table (from → to, predicate, order). Sortable, keyboard navigable;
this is the non-SVG representation of the same graph.

**9. Add-stage menu / palette** — choose a stage type to add (Pre-filter, Rule filter,
LLM filter, Enricher; Loopback shown disabled "coming soon"). Placing a pre_filter is only
allowed in the pre-extraction zone; rule/llm/enricher only post-extraction — reflect this
(e.g. disabled drop targets / inline hint).

### Data shapes (for realistic mock content)
```ts
type NodeType = 'source'|'extraction'|'sink'|'pre_filter'|'rule_filter'|'llm_filter'|'enricher'|'loopback'
type SinkRole = 'drop'|'auto_include'|'triage'
interface PipelineNode { id:number; type:NodeType; role?:SinkRole; label:string;
  source_scope:string[]|null; config:Record<string,unknown>; enabled:boolean; ui_x:number; ui_y:number }
interface PipelineEdge { id:number; from_node:number; to_node:number;
  predicate: ConditionTree | {op:'always'}; order_index:number }
type ConditionTree = { op:'AND'|'OR'|'NOT'; children:ConditionTree[] }
  | { field:string; operator:string; value:unknown }
interface FieldSpec { key:string; label:string;
  type:'enum'|'string'|'int'|'float'|'bool'|'datetime'|'list'; operators:string[];
  enum_values?:string[]; segment:'pre'|'post'|'both'; description?:string }
interface NodeStats { node_id:number; entered:number; dropped:number; passed:number }
```
Example operators by type: enum/string → eq, neq, in, not_in, contains, matches, exists;
int/float → eq, gt, gte, lt, lte; bool → is_true, is_false; datetime → before, after,
within_hours; list → contains, len_gt.

### Mock the canonical default graph (use this for the hero mock)
`Source` → (by source_type) → `Extraction` → `LLM filter` → splits to `Auto-include`,
`Drop`, and (on triage) → `Enricher (default, deep for diffs)` → `Triage`. Then show an
**edited** variation in a second frame: a `Pre-filter "Drop draft diffs"` in the
pre-extraction zone, a diff branch `Enricher(diff-meta)` → `Rule filter "author in [..] AND
files > 50 → drop"` → shared `LLM filter`, and a task branch `Rule filter "priority == low →
drop"` converging on the same `LLM filter`, then re-diverging to type-specific enrichers
before `Triage`. This demonstrates diverge → converge → re-diverge and interleaved
filters+enrichers.

Deliver: the Pipeline tab (default-graph hero + edited variation), the StageNode variant
sheet (all types + all states), RuleBuilderDialog (empty / filled-nested / error), and
EnricherConfigDialog. Dark theme, shadcn, dense, monospace numerics.

## PROMPT END
