# Workbench Mission Control UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reskin all eight dashboard pages and the shell to the Stitch two-orange dark/light/auto theme, add an icon-rail shell + ⌘K command palette, and back every metric/widget with seven new honest backend endpoints — preserving the five-state taxonomy, ADR contracts, and WCAG AA.

**Architecture:** A `next-themes` ThemeProvider toggles `.dark` on `<html>`; `index.css` holds raw-hex `:root`/`.dark` token ladders exposed to Tailwind v4 via `@theme inline`. A CSS-grid `AppShell` renders a 64px icon rail + sticky top bar + ⌘K palette; pages call TanStack-Query hooks → `lib/api.ts` → bearer-authed `/api`. New FastAPI routers (`search`, `topology`) and additive blocks on `stats`/`actions`/`triage`/`memory`/`sources` derive metrics from real Postgres tables via asyncpg; charts re-theme from `lib/chart-theme.ts`.

**Tech Stack:** React 19 + TypeScript + Vite 7 + Tailwind v4 + shadcn/Radix + TanStack Query 5 + Recharts 3 + lucide-react + next-themes + cmdk; FastAPI + asyncpg + Pydantic; Vitest + RTL + MSW (frontend), pytest (backend).

**Test commands:**
- All frontend tests: `make ui-test` (== `cd ui && npm run test` == `vitest run`).
- Single frontend test file: `cd ui && npx vitest run src/pages/Overview.test.tsx`.
- Single frontend test by name: `cd ui && npx vitest run -t "renders the hot feed"`.
- All backend tests: `make test` (== `python -m pytest tests/ -v --tb=short`).
- Single backend test: `python -m pytest tests/test_search_api.py -v --tb=short`.
- Keep `make ui-test` (and `make test` once backend tasks start) green at every commit.

---

## File Structure

### Frontend — new files (`ui/src/...`)
| File | Responsibility |
|---|---|
| `components/Mono.tsx` | `font-mono tabular-nums` wrapper for numbers/IDs/timestamps. |
| `lib/chart-theme.ts` | `CHART_COLORS` + `CHART_DEFAULTS` token-driven Recharts config. |
| `components/Sparkline.tsx` | Recharts area sparkline + degenerate (empty/single-point) states. |
| `components/LogStream.tsx` | Mono auto-scroll terminal log pane. |
| `components/ui/tooltip.tsx` | Vendored shadcn Radix tooltip primitive. |
| `components/ui/command.tsx` | Vendored shadcn cmdk primitive. |
| `components/TopBar.tsx` | Sticky top app bar (brand, mono context label, ⌘K trigger, sync, theme toggle, user). |
| `components/ThemeToggle.tsx` | Three-state light/dark/auto toggle (next-themes). |
| `components/CommandPalette.tsx` | cmdk palette, global ⌘K listener, local nav Commands, `/api/search` results. |
| `components/Topology.tsx` | 2D SVG node-link graph + visually-hidden a11y table. |
| `components/JsonHighlight.tsx` | Regex → React-span JSON syntax highlighter. |
| `hooks/useSearch.ts` | `GET /api/search` (debounced). |
| `hooks/useMetrics.ts` | Typing for `/api/stats/overview#metrics` + `useStatsTimeseries`. |
| `hooks/useTopology.ts` | `GET /api/topology` (poll 15s). |
| `hooks/useWorkMode.ts` | localStorage + `storage`-event view preference. |
| `test/handlers.ts` | Shared MSW handlers for the new endpoints. |

> `hooks/useActivity` and `useCreateAction` already have natural homes: `useActivity` exists in `hooks/useStats.ts`; `useCreateAction` is added to `hooks/useActions.ts`.

### Frontend — modified files (`ui/src/...`)
| File | Change |
|---|---|
| `index.html` | Remove hardcoded `class="dark"`. |
| `main.tsx` | Mount `next-themes` ThemeProvider. |
| `index.css` | Replace OKLCH tokens with hex two-orange ladder + `@theme inline` + font imports. |
| `components/AppShell.tsx` | flex → CSS grid; mount TopBar + CommandPalette. |
| `components/AppSidebar.tsx` | 64px icon rail, lucide icons, tooltips, orange active bar. |
| `components/StatCard.tsx` | Mono value + optional `delta?`/`sub?`. |
| `components/DataTable.tsx` | `Column.mono?` opt-in. |
| `components/ui/{card,button,badge,input}.tsx` | Token restyle; badge `p0..p3` variants. |
| `components/EmptyState.tsx` | Terminal `// End of feed` aesthetic. |
| `pages/Overview.tsx` | Hero region; drop `DONUT_COLORS` for chart-theme. |
| `pages/Triage.tsx` | 3-column + keyboard cards + client filters + LLM Insight. |
| `pages/ActionItems.tsx` | Grouped sections + FAB + throughput + Work Mode. |
| `pages/Sources.tsx` | Card grid + config drawer + relevance thresholds. |
| `pages/Ingestion.tsx` | Restyle + LIVE log. |
| `pages/Knowledge.tsx` | Add Fact + growth velocity StatCard. |
| `pages/Settings.tsx` | JSON highlighter + drop Runtime Metadata. |
| `pages/Messenger.tsx` | Token restyle. |
| `hooks/useActions.ts` | Add `useCreateAction`. |
| `hooks/useStats.ts` | Extend `StatsOverview` with `metrics`; add timeseries types. |
| `a11y.test.tsx` + each `pages/*.test.tsx`, `components/SourceForm.test.tsx` | Extend for new shell/palette/endpoints. |

### Backend — new/modified files (`src/workbench/...`)
| File | Change |
|---|---|
| `api/search.py` | **NEW** `GET /api/search`. |
| `api/topology.py` | **NEW** `GET /api/topology`. |
| `api/stats.py` | Add `metrics` block to `/overview`; add `GET /api/stats/timeseries`. |
| `api/actions.py` | Add `POST /api/actions` (manual Action Item). |
| `migrations/versions/007_triage_created_at.py` | **NEW** add `triage_cards.created_at` column (down_revision `006`). |
| `models.py` | Add `created_at` field to `TriageCard`. |
| `storage/postgres/triage.py` | Persist + read `created_at` in `save_card`/`_row_to_card`. |
| `api/triage.py` | Serialize `created_at` in `/triage/pending` payload. |
| `api/memory.py` | Add `POST /api/memory/facts` (501 under NoopMemory). |
| `api/sources.py` | Per-source `relevance` threshold fields in PATCH + hot-reload. |
| `main.py` | Register `search` + `topology` routers. |
| `storage/postgres/items.py` | `created_timeseries`, `completed_timeseries`, `auto_resolved_counts`. |
| `storage/postgres/triage.py` | `avg_triage_seconds`. |
| `storage/ingestion_runs.py` | `success_rate`. |
| `memory/base.py` + `memory/noop.py` + `memory/http.py` | `add_fact` (raises `NotImplementedError` on noop). |
| `tests/test_*` | Cover all new endpoints + derivations. |

---

## Phase 1 — Theme tokens & contrast contract (index.css)

### Task 1: Hex two-orange token ladder + remove `class="dark"` + mount ThemeProvider
**Files:**
- Modify: `ui/src/index.css`, `ui/index.html`, `ui/src/main.tsx`
- Test: `ui/src/index.css.test.ts` (Create)

- [ ] Step 1: Write the failing test. Create `ui/src/index.css.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const css = readFileSync(fileURLToPath(new URL('./index.css', import.meta.url)), 'utf8')
const html = readFileSync(
  fileURLToPath(new URL('../index.html', import.meta.url)),
  'utf8',
)

describe('theme tokens (spec §1, contrast contract §13)', () => {
  it('authors tokens as raw hex, not oklch', () => {
    expect(css).not.toMatch(/oklch\(/)
  })
  it('defines the dark surface ladder hexes', () => {
    for (const hex of ['#0e0e11', '#131316', '#1b1b1e', '#1f1f22', '#2a2a2d', '#353438']) {
      expect(css.toLowerCase()).toContain(hex)
    }
  })
  it('maps the two-orange system to shadcn vars', () => {
    expect(css).toMatch(/--primary:\s*#ff6a2b/i)
    expect(css).toMatch(/--primary-foreground:\s*#0e0e11/i)
    expect(css).toMatch(/--ring:\s*#ff6a2b/i)
    expect(css).toMatch(/--accent:\s*#2a2a2d/i) // neutral hover, NOT orange
  })
  it('normalizes the hairline border to #26262C', () => {
    expect(css.toLowerCase()).toContain('--border: #26262c')
  })
  it('exposes extra surface + brand tokens via @theme inline', () => {
    expect(css).toMatch(/--color-surface-lowest:/)
    expect(css).toMatch(/--brand:/)
  })
  it('removes the hardcoded dark class from index.html', () => {
    expect(html).not.toMatch(/<html[^>]*class="dark"/)
  })
})
```
- [ ] Step 2: Run test to verify it fails. `cd ui && npx vitest run src/index.css.test.ts` — Expected failure: `oklch(` still present; `#ff6a2b` not found.
- [ ] Step 3: Write minimal implementation. In `index.css` replace the `:root`/`.dark` OKLCH blocks with raw-hex dark ladder per spec §1 (`--background #131316`, `--card #1b1b1e`, `--popover #1f1f22`, `--primary #ff6a2b`, `--primary-foreground #0e0e11`, `--secondary #1f1f22`, `--muted #1b1b1e`, `--accent #2a2a2d`, `--destructive #93000a`, `--border #26262C`, `--input #0e0e11`, `--ring #ff6a2b`, `--foreground #e4e1e6`) and a `:root` light block grounded in `stitch-design-light.html` with the same `--primary`/`--ring`. Add `--radius: 0.375rem`. Extend `@theme inline` with `--color-surface-{lowest,low,container,high,highest}`, `--brand`, `--brand-fg`, mapped to the new vars. Retune `.prio-P0..P3` to harmonize (keep AA pairs). In `index.html` change `<html lang="en" class="dark">` → `<html lang="en">`. In `main.tsx` wrap `<App/>` with `<ThemeProvider attribute="class" defaultTheme="system" enableSystem>` from `next-themes`.
- [ ] Step 4: Run test to verify it passes. `cd ui && npx vitest run src/index.css.test.ts` — Expected: PASS. Then `make ui-test` — Expected: PASS (whole suite green).
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): hex two-orange theme tokens + next-themes provider, drop hardcoded dark"`

---

## Phase 2 — Fonts + Mono

### Task 2: Self-hosted offline fonts + type scale
**Files:**
- Modify: `ui/package.json`, `ui/src/index.css`
- Test: `ui/src/index.css.test.ts` (Modify)

- [ ] Step 1: Add to the existing `describe` in `ui/src/index.css.test.ts`:
```ts
it('self-hosts fonts via @fontsource (no Google CDN)', () => {
  expect(css).toContain('@import "@fontsource-variable/space-grotesk"')
  expect(css).toContain('@import "@fontsource-variable/hanken-grotesk"')
  expect(css).toContain('@import "@fontsource-variable/jetbrains-mono"')
  expect(css).not.toMatch(/fonts\.googleapis\.com/)
  expect(css).not.toMatch(/fonts\.gstatic\.com/)
})
it('defines the font + type-scale tokens', () => {
  expect(css).toMatch(/--font-sans:\s*"Hanken Grotesk Variable"/)
  expect(css).toMatch(/--font-display:\s*"Space Grotesk Variable"/)
  expect(css).toMatch(/--font-mono:\s*"JetBrains Mono Variable"/)
  expect(css).toMatch(/--text-display-lg:\s*32px/)
})
```
- [ ] Step 2: Run test to verify it fails. `cd ui && npx vitest run src/index.css.test.ts` — Expected failure: `@import "@fontsource-variable/...` not found.
- [ ] Step 3: Implementation. `cd ui && npm install @fontsource-variable/space-grotesk @fontsource-variable/hanken-grotesk @fontsource-variable/jetbrains-mono`. Add the three `@import` lines at the top of `index.css` (after `@import "tailwindcss"`). Add to `@theme inline`: `--font-sans`, `--font-display`, `--font-mono`, and the `--text-*` scale tokens per spec §2. Add a base layer rule: `body { font-family: var(--font-sans) } h1,h2,h3 { font-family: var(--font-display) }` and `font-display: swap`.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/index.css.test.ts` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): self-host Space Grotesk + Hanken + JetBrains Mono offline + type scale"`

### Task 3: `<Mono>` wrapper component
**Files:**
- Create: `ui/src/components/Mono.tsx`, `ui/src/components/Mono.test.tsx`

- [ ] Step 1: Write `ui/src/components/Mono.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Mono } from './Mono'

describe('Mono', () => {
  it('renders children with font-mono + tabular-nums classes', () => {
    render(<Mono>WRK-9402</Mono>)
    const el = screen.getByText('WRK-9402')
    expect(el.className).toContain('font-mono')
    expect(el.className).toContain('tabular-nums')
  })
  it('merges an extra className', () => {
    render(<Mono className="text-destructive">404</Mono>)
    expect(screen.getByText('404').className).toContain('text-destructive')
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/Mono.test.tsx` — Expected failure: cannot resolve `./Mono`.
- [ ] Step 3: Implementation. Create `Mono.tsx`:
```tsx
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn('font-mono tabular-nums', className)}>{children}</span>
}
```
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/Mono.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): add Mono wrapper (font-mono tabular-nums)"`

---

## Phase 3 — Primitives / shared components & chart-theme

### Task 4: `lib/chart-theme.ts`
**Files:**
- Create: `ui/src/lib/chart-theme.ts`, `ui/src/lib/chart-theme.test.ts`

- [ ] Step 1: Write `ui/src/lib/chart-theme.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { CHART_COLORS, CHART_DEFAULTS } from './chart-theme'

describe('chart-theme', () => {
  it('exposes the token-driven palette', () => {
    expect(CHART_COLORS.primary).toBe('#ff6a2b')
    expect(CHART_COLORS.tertiary).toBe('#71d2ff')
    expect(CHART_COLORS).toMatchObject({ red: '#ffb4ab', blue: '#71d2ff', green: '#9ad08a' })
  })
  it('provides recharts grid/axis defaults', () => {
    expect(CHART_DEFAULTS.grid.stroke).toBe('#26262C')
    expect(CHART_DEFAULTS.axis.stroke).toBeTruthy()
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/lib/chart-theme.test.ts` — Expected failure: cannot resolve `./chart-theme`.
- [ ] Step 3: Implementation. Create `chart-theme.ts`:
```ts
export const CHART_COLORS = {
  primary: '#ff6a2b', tertiary: '#71d2ff',
  red: '#ffb4ab', amber: '#ffb59a', blue: '#71d2ff', green: '#9ad08a',
} as const

export const CHART_DEFAULTS = {
  grid: { stroke: '#26262C', strokeDasharray: '3 3' },
  axis: { stroke: '#a98a7f', fontSize: 12 },
  tooltip: { background: '#1f1f22', border: '1px solid #26262C', color: '#e4e1e6' },
} as const
```
- [ ] Step 4: Run test. `cd ui && npx vitest run src/lib/chart-theme.test.ts` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): chart-theme module (CHART_COLORS + CHART_DEFAULTS)"`

### Task 5: Vendored Radix tooltip primitive
**Files:**
- Create: `ui/src/components/ui/tooltip.tsx`, `ui/src/components/ui/tooltip.test.tsx`

- [ ] Step 1: Write `ui/src/components/ui/tooltip.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent } from './tooltip'

describe('tooltip', () => {
  it('shows content on focus', async () => {
    const user = userEvent.setup()
    render(
      <TooltipProvider>
        <Tooltip><TooltipTrigger>Trigger</TooltipTrigger>
          <TooltipContent>Overview</TooltipContent></Tooltip>
      </TooltipProvider>,
    )
    await user.tab()
    expect(await screen.findByText('Overview')).toBeInTheDocument()
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/ui/tooltip.test.tsx` — Expected failure: cannot resolve `./tooltip`.
- [ ] Step 3: Implementation. `cd ui && npm install @radix-ui/react-tooltip`. Create `tooltip.tsx` vendoring the shadcn tooltip (re-export `TooltipProvider`, `Tooltip`, `TooltipTrigger`, and a styled `TooltipContent` using `bg-popover text-popover-foreground rounded-md border px-2 py-1 text-xs` — popover surface per contrast contract §13, never orange text). Gate the open/close animation behind `motion-reduce:transition-none`.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/ui/tooltip.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): vendor shadcn Radix tooltip primitive"`

### Task 6: Restyle Card / Button / Badge / Input + `p0..p3` badge variants
**Files:**
- Modify: `ui/src/components/ui/card.tsx`, `button.tsx`, `badge.tsx`, `input.tsx`
- Test: `ui/src/components/ui/badge.test.tsx` (Create)

- [ ] Step 1: Write `ui/src/components/ui/badge.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Badge } from './badge'

describe('Badge', () => {
  it('is mono by default', () => {
    render(<Badge>github</Badge>)
    expect(screen.getByText('github').className).toContain('font-mono')
  })
  it('renders a p0 priority variant (tinted bg + border)', () => {
    render(<Badge variant="p0">P0</Badge>)
    const el = screen.getByText('P0')
    expect(el.className).toMatch(/border/)
  })
  it('supports p1/p2/p3 variants', () => {
    for (const v of ['p1', 'p2', 'p3'] as const) {
      const { unmount } = render(<Badge variant={v}>{v}</Badge>)
      expect(screen.getByText(v)).toBeInTheDocument()
      unmount()
    }
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/ui/badge.test.tsx` — Expected failure: `p0` variant not in CVA config.
- [ ] Step 3: Implementation. `badge.tsx`: add `font-mono` to the base CVA string; add `p0` (15% red bg + solid red border + `#ffb4ab` text), `p1`, `p2`, `p3` variants harmonized with `.prio-*` and AA-safe. `button.tsx`: default = solid `bg-primary text-primary-foreground` (near-black on orange) + `focus-visible:ring-ring`; outline = `border border-border font-mono`. `card.tsx`: `rounded-md`, remove drop shadow, optional `border-b` divided header. `input.tsx`: `bg-[#0e0e11] border border-border`.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/ui/badge.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): token restyle Card/Button/Badge/Input + p0..p3 badge variants"`

### Task 7: StatCard mono value + `delta?`/`sub?`
**Files:**
- Modify: `ui/src/components/StatCard.tsx`
- Test: `ui/src/components/StatCard.test.tsx` (Create)

- [ ] Step 1: Write `ui/src/components/StatCard.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatCard } from './StatCard'

describe('StatCard', () => {
  it('renders an uppercase mono label and a mono value', () => {
    render(<StatCard label="Pending Triage" value={42} />)
    expect(screen.getByText('42').className).toContain('font-mono')
  })
  it('applies danger styling', () => {
    render(<StatCard label="Dead Letters" value={3} danger />)
    expect(screen.getByText('3').className).toContain('text-destructive')
  })
  it('renders an optional delta and sub slot', () => {
    render(<StatCard label="Throughput" value={7} delta="+2" sub={<span>spark</span>} />)
    expect(screen.getByText('+2')).toBeInTheDocument()
    expect(screen.getByText('spark')).toBeInTheDocument()
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/StatCard.test.tsx` — Expected failure: `delta`/`sub` props rejected; value not mono.
- [ ] Step 3: Implementation. Extend props with `delta?: ReactNode; sub?: ReactNode`. Wrap value in `<Mono className="text-2xl ...">`; uppercase the label (`uppercase tracking-wide`, mono-label size); render `delta` next to value and `sub` below; keep `danger → text-destructive`.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/StatCard.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): StatCard mono value + delta/sub slots"`

### Task 8: DataTable `Column.mono?` opt-in
**Files:**
- Modify: `ui/src/components/DataTable.tsx`
- Test: `ui/src/components/DataTable.test.tsx` (Create)

- [ ] Step 1: Write `ui/src/components/DataTable.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DataTable, type Column } from './DataTable'

type Row = { id: string; name: string }
const rows: Row[] = [{ id: 'WRK-1', name: 'alpha' }]

describe('DataTable mono columns', () => {
  it('adds font-mono tabular-nums to mono cells only', () => {
    const cols: Column<Row>[] = [
      { key: 'id', header: 'ID', render: (r) => r.id, mono: true },
      { key: 'name', header: 'Name', render: (r) => r.name },
    ]
    render(<DataTable columns={cols} rows={rows} rowKey={(r) => r.id} />)
    expect(screen.getByText('WRK-1').closest('td')!.className).toContain('font-mono')
    expect(screen.getByText('alpha').closest('td')!.className).not.toContain('font-mono')
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/DataTable.test.tsx` — Expected failure: `mono` not on `Column`.
- [ ] Step 3: Implementation. Add `mono?: boolean` to `Column<T>`; apply `className={c.mono ? 'font-mono tabular-nums' : undefined}` on the `<TableCell>`.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/DataTable.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): DataTable Column.mono opt-in"`

### Task 9: Sparkline component (+ degenerate states)
**Files:**
- Create: `ui/src/components/Sparkline.tsx`, `ui/src/components/Sparkline.test.tsx`

- [ ] Step 1: Write `ui/src/components/Sparkline.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Sparkline } from './Sparkline'

describe('Sparkline', () => {
  it('renders an em-dash placeholder when empty', () => {
    render(<Sparkline data={[]} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })
  it('renders an svg region for multi-point data', () => {
    const { container } = render(<Sparkline data={[{ count: 1 }, { count: 5 }, { count: 3 }]} />)
    expect(container.querySelector('svg')).toBeTruthy()
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/Sparkline.test.tsx` — Expected failure: cannot resolve `./Sparkline`.
- [ ] Step 3: Implementation. `Sparkline.tsx` takes `data: { count: number }[]`. Empty → flat baseline + `<span>—</span>`; single point → a dot; else a Recharts `<AreaChart>` in a `<ResponsiveContainer>` using `CHART_COLORS.primary` and no axes/tooltip. Wrap in a fixed-height div.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/Sparkline.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): Sparkline component with degenerate states"`

### Task 10: LogStream component
**Files:**
- Create: `ui/src/components/LogStream.tsx`, `ui/src/components/LogStream.test.tsx`

- [ ] Step 1: Write `ui/src/components/LogStream.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LogStream } from './LogStream'

describe('LogStream', () => {
  it('renders mono log lines', () => {
    render(<LogStream lines={[{ id: '1', text: 'github poll ok' }]} />)
    const el = screen.getByText('github poll ok')
    expect(el.closest('[data-logstream]')).toBeTruthy()
  })
  it('renders an empty terminal state', () => {
    render(<LogStream lines={[]} />)
    expect(screen.getByText(/no activity/i)).toBeInTheDocument()
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/LogStream.test.tsx` — Expected failure: cannot resolve `./LogStream`.
- [ ] Step 3: Implementation. `LogStream.tsx` takes `lines: { id: string; text: string }[]`. Render a `font-mono text-body-sm` scroll pane (`data-logstream`, `role="log"`, `aria-live="polite"`), auto-scroll to bottom via a ref `useEffect` gated by `prefers-reduced-motion`; empty → `// no activity` terminal line.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/LogStream.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): LogStream auto-scroll terminal pane"`

### Task 11: EmptyState terminal aesthetic
**Files:**
- Modify: `ui/src/components/EmptyState.tsx`
- Test: `ui/src/components/EmptyState.test.tsx` (Create)

- [ ] Step 1: Write `ui/src/components/EmptyState.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EmptyState } from './EmptyState'

describe('EmptyState', () => {
  it('renders the message in a mono terminal frame', () => {
    render(<EmptyState message="No cards" />)
    expect(screen.getByText('No cards')).toBeInTheDocument()
    expect(screen.getByText(/\/\/ end of feed/i)).toBeInTheDocument()
  })
  it('renders an optional cta', () => {
    render(<EmptyState message="x" cta={<button>Add</button>} />)
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument()
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/EmptyState.test.tsx` — Expected failure: `// End of feed` text absent.
- [ ] Step 3: Implementation. Keep the `{ message, cta }` props; add a `font-mono text-muted-foreground` footer line `// End of feed`. Preserve existing centered layout.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/EmptyState.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): EmptyState terminal aesthetic"`

---

## Phase 4 — Shell (icon rail → top bar → theme toggle → ⌘K + /api/search)

### Task 12: 64px icon rail (AppSidebar)
**Files:**
- Modify: `ui/src/components/AppSidebar.tsx`
- Test: `ui/src/a11y.test.tsx` (Modify)

- [ ] Step 1: Add to `a11y.test.tsx` (keep existing tests; the existing landmark/aria-current tests already cover the rail — extend with aria-label + icon-only naming). Append inside `describe('accessibility', ...)`:
```ts
it('rail links are icon-only with accessible names (aria-label)', () => {
  renderWithRouter(<AppSidebar />)
  // names come from aria-label, not visible text
  for (const name of ['Overview', 'Triage', 'Action Items', 'Sources', 'Settings']) {
    expect(screen.getByRole('link', { name })).toBeInTheDocument()
  }
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/a11y.test.tsx` — Expected failure: "Action Items" link not found by accessible name once visible text is removed (or already passes if labels retained — verify the rail still names via aria-label after refactor).
- [ ] Step 3: Implementation. Rewrite `AppSidebar` to a 64px rail: `nav aria-label="Primary"` with `w-16`, `row-span-2`. Map each NAV item to its lucide icon (`LayoutDashboard`, `ListChecks`, `CircleCheckBig`, `Workflow`, `Database`, `BookOpen`, `MessageSquare`, `Settings`) at 20px; each `NavLink` carries `aria-label={n.label}`, wrapped in a `<Tooltip>` (Task 5) with the label as content. Active = 2px `border-l-2 border-primary` + `text-primary` icon; keep `end={n.to==='/'}` (preserves `aria-current="page"`). Gate hover transition behind `motion-reduce:transition-none`.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/a11y.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): 64px icon rail with lucide icons + tooltips + active bar"`

### Task 13: AppShell CSS grid + TopBar + ThemeToggle
**Files:**
- Modify: `ui/src/components/AppShell.tsx`
- Create: `ui/src/components/TopBar.tsx`, `ui/src/components/ThemeToggle.tsx`, `ui/src/components/AppShell.test.tsx`

- [ ] Step 1: Write `ui/src/components/AppShell.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from 'next-themes'
import { AppShell } from './AppShell'

function renderShell(initial = '/actions') {
  return render(
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <MemoryRouter initialEntries={[initial]}>
        <AppShell><div>page-body</div></AppShell>
      </MemoryRouter>
    </ThemeProvider>,
  )
}

describe('AppShell', () => {
  it('renders the brand, a banner top bar, the rail, and children', () => {
    renderShell()
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: /primary/i })).toBeInTheDocument()
    expect(screen.getByText('page-body')).toBeInTheDocument()
    expect(screen.getByText(/workbench/i)).toBeInTheDocument()
  })
  it('renders a mono route context label', () => {
    renderShell('/actions')
    expect(screen.getByText(/ACTION_ITEMS/)).toBeInTheDocument()
  })
  it('exposes a theme toggle', () => {
    renderShell()
    expect(screen.getByRole('button', { name: /theme/i })).toBeInTheDocument()
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/AppShell.test.tsx` — Expected failure: no `banner`, no theme toggle.
- [ ] Step 3: Implementation. `ThemeToggle.tsx`: three-state cycle (light/dark/system) via `useTheme()` from `next-themes`, lucide `Sun`/`Moon`/`Monitor`, `aria-label="Toggle theme"`. `TopBar.tsx`: `<header role="banner" className="sticky top-0 z-20 ...">` with brand `W` + "Workbench", a mono route→context label map (`/` → `OVERVIEW`, `/actions` → `ACTION_ITEMS.LOG`, etc.) via `useLocation`, a `⌘K` trigger slot (button, wired in Task 15), a sync-status dot (derived from `useHealth`), `<ThemeToggle/>`, and a user chip. NO "Deploy" button. `AppShell.tsx`: replace flex with `grid min-h-screen grid-cols-[64px_1fr] grid-rows-[auto_1fr]`; `<AppSidebar className="row-span-2 z-30" />`, `<TopBar/>`, `<main className="overflow-y-auto p-6">{children}</main>`.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/AppShell.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): grid AppShell + sticky TopBar + three-state ThemeToggle"`

### Task 14: Backend `GET /api/search` (ILIKE, grouped, facts-degraded)
**Files:**
- Create: `src/workbench/api/search.py`, `tests/test_search_api.py`
- Modify: `src/workbench/main.py`

- [ ] Step 1: Write `tests/test_search_api.py` (mirror the `app_with_state`/`client`/`stores` fixtures from `tests/test_stats_api.py`):
```python
import pytest

@pytest.mark.asyncio
async def test_search_groups_items_actions_sources(client, stores):
    from workbench.models import Item, ItemCategory, ItemOrigin, ItemStatus, Priority, SourceConfig
    await stores.sources.upsert_source(SourceConfig(adapter_type="github", config={}, schedule="* * * * *"))
    await stores.items.save_item(Item(source_type="github", source_id="1", summary="RDS failover alert",
        category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.INGESTED, priority=Priority.P0, status=ItemStatus.PENDING_TRIAGE))
    r = await client.get("/api/search?q=rds")
    assert r.status_code == 200
    body = r.json()
    assert body["q"] == "rds"
    assert any(h["label"].startswith("RDS") for h in body["groups"]["items"])
    assert body["groups"]["items"][0]["kind"] == "item"
    # pending_triage item routes to /triage
    assert body["groups"]["items"][0]["route"] == "/triage"

@pytest.mark.asyncio
async def test_search_escapes_ilike_wildcards(client, stores):
    from workbench.models import Item, ItemCategory, ItemOrigin, Priority
    await stores.items.save_item(Item(source_type="github", source_id="2", summary="literal percent test",
        category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.INGESTED, priority=Priority.P2))
    r = await client.get("/api/search?q=%25")  # url-encoded '%'
    assert r.status_code == 200
    assert r.json()["groups"]["items"] == []  # '%' is escaped, not a wildcard

@pytest.mark.asyncio
async def test_search_omits_facts_group_under_noop_memory(client):
    r = await client.get("/api/search?q=anything")
    assert "facts" not in r.json()["groups"]  # NoopMemoryLayer → degraded

@pytest.mark.asyncio
async def test_search_caps_limit_at_50(client):
    r = await client.get("/api/search?q=ab&limit=999")
    assert r.status_code == 200
```
- [ ] Step 2: Run test. `python -m pytest tests/test_search_api.py -v --tb=short` — Expected failure: 404 (router not registered).
- [ ] Step 3: Implementation. Create `api/search.py` with `router = APIRouter(prefix="/api", tags=["search"])` and `GET /search?q&limit`. Cap `limit` at 50 (default 20). Escape `%`, `_`, `\` in `q` (`q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')`) and use parameterized `ILIKE '%' || $1 || '%' ESCAPE '\'` over `items.summary`, `actions.summary` (items where `action_source IS NOT NULL`), and `source_configs` id/adapter_type via `stores.*.pool.fetch`. Build `SearchHit` dicts `{id,kind,label,sublabel?,route}` — item route `/triage` when `status='pending_triage'` else `/`; action route `/actions`; source route `/sources`. Rank exact→prefix→substring→recency in Python. Facts: read `request.app.state.memory`; if `is_available()` and not noop, proxy `list_facts()` filtered by `q` into a `facts` group; otherwise OMIT the `facts` key entirely. Return `{"q", "groups", "truncated"}`. Register in `main.py`: import `search` and add `search.router` to the include list.
- [ ] Step 4: Run test. `python -m pytest tests/test_search_api.py -v --tb=short` — Expected: PASS. `make test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(api): GET /api/search (ILIKE grouped search, facts-degraded under noop)"`

### Task 15: Command palette + useSearch + global ⌘K
**Files:**
- Create: `ui/src/components/ui/command.tsx`, `ui/src/components/CommandPalette.tsx`, `ui/src/hooks/useSearch.ts`, `ui/src/components/CommandPalette.test.tsx`
- Modify: `ui/src/components/AppShell.tsx`, `ui/src/a11y.test.tsx`

- [ ] Step 1: Write `ui/src/components/CommandPalette.test.tsx` (MSW-driven):
```ts
import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { CommandPalette } from './CommandPalette'
import { _resetToken } from '@/lib/api'

const handlers = [
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/search', () =>
    HttpResponse.json({ q: 'rds', truncated: false, groups: {
      items: [{ id: 'WRK-1', kind: 'item', label: 'RDS alert', sublabel: 'github · P0', route: '/triage' }],
      actions: [], sources: [],
    } })),
]
const server = setupServer(...handlers)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(...handlers); _resetToken() })
afterAll(() => server.close())

function renderPalette() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><CommandPalette open onOpenChange={() => {}} /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CommandPalette', () => {
  it('shows nav Commands when the query is empty', async () => {
    renderPalette()
    expect(await screen.findByText('Overview')).toBeInTheDocument()
    expect(screen.getByText(/toggle theme/i)).toBeInTheDocument()
  })
  it('queries /api/search and groups hits (debounced, min 2 chars)', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'rds')
    expect(await screen.findByText('RDS alert')).toBeInTheDocument()
  })
})
```
  Also append to `a11y.test.tsx`:
```ts
it('command palette exposes combobox + listbox roles', async () => {
  // render CommandPalette open with a QueryClient + Router (helper above);
  expect(screen.getByRole('combobox')).toBeInTheDocument()
  expect(screen.getByRole('listbox')).toBeInTheDocument()
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/CommandPalette.test.tsx` — Expected failure: cannot resolve `./CommandPalette`.
- [ ] Step 3: Implementation. `cd ui && npm install cmdk`. Vendor `components/ui/command.tsx` (shadcn cmdk wrapper over Radix Dialog, with a visually-hidden `DialogTitle`, `combobox` input + `listbox`). `hooks/useSearch.ts`: `useSearch(q)` — `enabled: q.length >= 2`, queries `/api/search?q=...&limit=20`, typed envelope. `CommandPalette.tsx`: controlled `open`/`onOpenChange`; debounce input 200ms (min 2 chars); empty query → 8 nav Commands + "Toggle theme" + "Poll source"; non-empty → grouped Items/Actions/Sources/(Facts if present) with the five internal states (loading/empty/error+X-Request-ID/unauthorized/degraded); selecting a hit `navigate(hit.route)` + close; restore focus to trigger on close (Radix default). In `AppShell.tsx` add `const [open,setOpen]=useState(false)`, a `(meta|ctrl)+k` keydown listener (`useEffect`, gated to not fire in inputs), wire the TopBar ⌘K trigger to `setOpen(true)`, and mount `<CommandPalette open={open} onOpenChange={setOpen} />`.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/CommandPalette.test.tsx src/a11y.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): cmdk command palette + global ⌘K + useSearch"`

---

## Phase 5 — Backend endpoints (+ shared MSW handlers)

### Task 16: `metrics` block on `/api/stats/overview`
**Files:**
- Modify: `src/workbench/api/stats.py`, `src/workbench/storage/postgres/items.py`, `src/workbench/storage/postgres/triage.py`, `src/workbench/storage/ingestion_runs.py`
- Modify/Create test: `tests/test_stats_api.py`

- [ ] Step 1: Add to `tests/test_stats_api.py`:
```python
@pytest.mark.asyncio
async def test_overview_metrics_block_present(client):
    body = (await client.get("/api/stats/overview")).json()
    assert "metrics" in body
    for k in ["signal_velocity", "throughput", "efficiency_peak", "auto_resolved_pct",
              "avg_triage_seconds", "growth_velocity", "ingestion_success_rate"]:
        assert k in body["metrics"]

@pytest.mark.asyncio
async def test_overview_metrics_null_on_empty_denominator(client):
    m = (await client.get("/api/stats/overview")).json()["metrics"]
    # no triage cards, no runs, noop memory → n/a fields are None, never fabricated
    assert m["avg_triage_seconds"] is None
    assert m["ingestion_success_rate"] is None
    assert m["growth_velocity"] is None  # NoopMemoryLayer
```
- [ ] Step 2: Run test. `python -m pytest tests/test_stats_api.py -k metrics -v --tb=short` — Expected failure: `metrics` key absent.
- [ ] Step 3: Implementation. Add repo methods: `items.count_created_since(hours)` and `auto_resolved_counts(window_hours)` (`auto_included` vs total); `triage.avg_triage_seconds()` = `AVG(EXTRACT(EPOCH FROM (responded_at - sent_at)))` where both non-null (returns `None` if none); `ingestion_runs.success_rate(days)` = `success/total` (`None` when total 0). In `stats.overview` build `metrics` dict: `signal_velocity` (items created last hour), `throughput` (action items with `completed_at`/done last hour — compute via items done-lifecycle or `None` if unavailable), `efficiency_peak` (max bucket close rate as a float ratio 0..1 = completed/created in the busiest bucket, or `None` when no created items), `auto_resolved_pct`, `avg_triage_seconds`, `growth_velocity` (`None` when `memory.memory_type=="noop"`), `ingestion_success_rate`. Any zero-denominator → `None`.
- [ ] Step 4: Run test. `python -m pytest tests/test_stats_api.py -k metrics -v --tb=short` — Expected: PASS. `make test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(api): honest metrics block on /api/stats/overview"`

### Task 17: `GET /api/stats/timeseries` (zero-filled buckets)
**Files:**
- Modify: `src/workbench/api/stats.py`, `src/workbench/storage/postgres/items.py`
- Modify test: `tests/test_stats_api.py`

- [ ] Step 1: Add:
```python
@pytest.mark.asyncio
async def test_timeseries_signal_velocity_zero_filled(client):
    r = await client.get("/api/stats/timeseries?metric=signal_velocity&window=24&bucket=hour")
    assert r.status_code == 200
    series = r.json()
    assert len(series) == 24  # full bucket array, empty buckets count:0 not omitted
    assert all(set(p) == {"bucket", "count"} for p in series)
    assert all(p["count"] == 0 for p in series)  # no items yet

@pytest.mark.asyncio
async def test_timeseries_rejects_unknown_metric(client):
    r = await client.get("/api/stats/timeseries?metric=bogus&window=24&bucket=hour")
    assert r.status_code == 422
```
- [ ] Step 2: Run test. `python -m pytest tests/test_stats_api.py -k timeseries -v --tb=short` — Expected failure: 404.
- [ ] Step 3: Implementation. Add `GET /stats/timeseries?metric=&window=&bucket=` validating `metric ∈ {signal_velocity, throughput}` (else 422) and `bucket ∈ {hour, day}`. Add `items.created_timeseries(window, bucket)` and `items.completed_timeseries(window, bucket)` (`date_trunc` like `ingestion_runs.timeseries`). Generate the full bucket axis in Python (`window` buckets back from now), left-join the grouped counts, fill missing with `0`, return `[{"bucket": iso, "count": int}]`.
- [ ] Step 4: Run test. `python -m pytest tests/test_stats_api.py -k timeseries -v --tb=short` — Expected: PASS. `make test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(api): GET /api/stats/timeseries with zero-filled buckets"`

### Task 18: `GET /api/topology`
**Files:**
- Create: `src/workbench/api/topology.py`, `tests/test_topology_api.py`
- Modify: `src/workbench/main.py`

- [ ] Step 1: Write `tests/test_topology_api.py`:
```python
import pytest

@pytest.mark.asyncio
async def test_topology_composes_app_storage_memory(client):
    body = (await client.get("/api/topology")).json()
    ids = {n["id"] for n in body["nodes"]}
    assert {"app", "pg", "memory"} <= ids
    app_node = next(n for n in body["nodes"] if n["id"] == "app")
    assert app_node["kind"] == "app"
    pg = next(n for n in body["nodes"] if n["id"] == "pg")
    assert pg["status"] == "healthy"  # storage probe ok in test DB
    mem = next(n for n in body["nodes"] if n["id"] == "memory")
    assert mem["status"] == "not_configured"  # NoopMemoryLayer; neo4j folded in
    assert {"from": "app", "to": "pg", "kind": "connection"} in body["edges"]
```
- [ ] Step 2: Run test. `python -m pytest tests/test_topology_api.py -v --tb=short` — Expected failure: 404.
- [ ] Step 3: Implementation. Create `api/topology.py` with `router = APIRouter(prefix="/api", tags=["topology"])` and `GET /topology`. Reuse `health._check_storage(stores)` for the `pg` node status; map `memory.memory_type=="noop"` → `not_configured`, else probe `is_available()` → healthy/unhealthy. Build `app` node (always healthy), `pg` (storage), `memory` (memory_service, neo4j folded in), optional per-configured-adapter nodes (`kind="adapter"`) and a `messenger` node if configured. Edges `app→pg`, `app→memory`, `app→each adapter`. Register `topology.router` in `main.py`.
- [ ] Step 4: Run test. `python -m pytest tests/test_topology_api.py -v --tb=short` — Expected: PASS. `make test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(api): GET /api/topology composed from health probes"`

### Task 19: `POST /api/actions` (manual Action Item)
**Files:**
- Modify: `src/workbench/api/actions.py`
- Modify test: `tests/test_actions_api.py`

- [ ] Step 1: Add to `tests/test_actions_api.py` (use that file's existing fixtures):
```python
@pytest.mark.asyncio
async def test_post_manual_action_item(client):
    r = await client.post("/api/actions", json={"summary": "Call vendor", "priority": "P1", "action_category": "ops"})
    assert r.status_code in (200, 201)
    row = r.json()
    assert row["summary"] == "Call vendor"
    assert row["priority"] == "P1"
    assert row["action_source"] == "manual"
    # it now appears in GET /api/actions
    listing = (await client.get("/api/actions")).json()
    assert listing["total"] >= 1

@pytest.mark.asyncio
async def test_post_manual_action_rejects_bad_priority(client):
    r = await client.post("/api/actions", json={"summary": "x", "priority": "P9"})
    assert r.status_code == 422
```
- [ ] Step 2: Run test. `python -m pytest tests/test_actions_api.py -k manual -v --tb=short` — Expected failure: 405 (no POST on `/api/actions`).
- [ ] Step 3: Implementation. Add a `CreateActionBody(BaseModel)` with `summary: str`, `priority: Priority`, `action_category: str | None = None`, then `@router.post("")` that builds an `Item(category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL, action_source="manual", action_category=..., priority=..., status=ItemStatus.ACTIVE, summary=...)` (`ItemOrigin.MANUAL == "manual"`, models.py:34), saves via `stores.items.save_item`, and returns the created row (`id, summary, priority, action_source, action_category, created_at`).
- [ ] Step 4: Run test. `python -m pytest tests/test_actions_api.py -k manual -v --tb=short` — Expected: PASS. `make test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(api): POST /api/actions for manual action items"`

### Task 20: `triage_cards.created_at` migration + model field + `/api/triage/pending` payload
**Files:**
- Create: `src/workbench/migrations/versions/007_triage_created_at.py`
- Modify: `src/workbench/models.py` (`TriageCard`), `src/workbench/storage/postgres/triage.py`, `src/workbench/api/triage.py`
- Modify test: `tests/test_triage_web.py`

> **Why a migration (not just a payload field):** `triage_cards` has only `sent_at`/`expires_at`/`responded_at`/`deferred_until` — no row-birth timestamp. The Time-Window filter needs the card's age, so we add a real `created_at` column once (avoids a future migration). There is no `queued_at` column: the queue lifecycle is `queued → sent → responded/expired` (CONTEXT.md "Triage Queue"), so a card's "queued" age is its `created_at`. Latest existing migration is `006` (`006_change_monitoring_indexes.py`, revision `006` / down_revision `005`), so the new revision is `007` with `down_revision = "006"`.

- [ ] Step 1: Add to `tests/test_triage_web.py` (reuse its fixtures; seed a card via `stores.triage.save_card`):
```python
@pytest.mark.asyncio
async def test_pending_includes_created_at(client, stores):
    from workbench.models import TriageCard, TriageOption
    card = TriageCard(card_content={"summary": "x", "source_type": "github"},
                      options=[TriageOption(label="Add", action="add_todo")], status="sent")
    await stores.triage.save_card(card)
    pending = (await client.get("/api/triage/pending")).json()
    assert len(pending) >= 1
    c = pending[0]
    assert "created_at" in c and c["created_at"]  # ISO timestamp, used by the Time-Window filter
```
- [ ] Step 2: Run test. `python -m pytest tests/test_triage_web.py -k created_at -v --tb=short` — Expected failure: key absent.
- [ ] Step 3: Implementation.
  1. **Migration** `007_triage_created_at.py` (mirror `003_phase1d_columns.py` style):
```python
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column(
        "triage_cards",
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_triage_created_at", "triage_cards", ["created_at"])

def downgrade() -> None:
    op.drop_index("idx_triage_created_at", table_name="triage_cards")
    op.drop_column("triage_cards", "created_at")
```
  2. **Model** — add to `TriageCard` in `models.py`:
```python
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```
  3. **Repo** `storage/postgres/triage.py` — add `created_at` to the `save_card` INSERT column list + `$15` value (`card.created_at`) and to the `ON CONFLICT` set (`created_at = EXCLUDED.created_at`); read it back in `_row_to_card`: `created_at=row["created_at"]`.
  4. **API** `api/triage.py` — `get_pending` returns Pydantic `TriageCard` models; serialize each so `created_at` is in the payload: `return [c.model_dump(mode="json") for c in await stores.triage.get_pending()]` (preserves all existing fields the web Triage page reads).
- [ ] Step 4: Run test. `python -m pytest tests/test_triage_web.py -k created_at -v --tb=short` — Expected: PASS. `make test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(api): add triage_cards.created_at column + expose on /api/triage/pending"`

### Task 21: `POST /api/memory/facts` (manual fact, 501 under noop)
**Files:**
- Modify: `src/workbench/api/memory.py`, `src/workbench/memory/base.py`, `src/workbench/memory/noop.py`, `src/workbench/memory/http.py`
- Modify test: `tests/test_memory_api.py`

- [ ] Step 1: Add to `tests/test_memory_api.py`:
```python
@pytest.mark.asyncio
async def test_post_manual_fact_501_under_noop(client):
    r = await client.post("/api/memory/facts", json={"content": "prefers async", "source": "manual"})
    assert r.status_code == 501  # NoopMemoryLayer
```
  (If that file has a configured-memory fixture, add a 200 case with an AsyncMock `add_fact`.)
- [ ] Step 2: Run test. `python -m pytest tests/test_memory_api.py -k manual_fact -v --tb=short` — Expected failure: 405/404.
- [ ] Step 3: Implementation. Add abstract `async def add_fact(self, content: str, source: str | None) -> Fact` to `memory/base.py`; in `noop.py` implement it to `raise NotImplementedError`; in `http.py` POST to the memory service. Add `class CreateFactBody(BaseModel): content: str; source: str | None = None` and `@router.post("/memory/facts")` calling `memory.add_fact(...)`, catching `NotImplementedError` → `HTTPException(501, "memory layer not configured")`, else return the created fact (manual origin distinct from learned, coexists with ADR0019 tombstones).
- [ ] Step 4: Run test. `python -m pytest tests/test_memory_api.py -k manual_fact -v --tb=short` — Expected: PASS. `make test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(api): POST /api/memory/facts manual fact (501 under noop)"`

### Task 22: Per-source `relevance` thresholds on PATCH `/api/sources/{id}`
**Files:**
- Modify: `src/workbench/api/sources.py`, `src/workbench/models.py` (SourceConfig/Update if needed)
- Modify test: `tests/test_sources_api.py`

- [ ] Step 1: Add to `tests/test_sources_api.py` (reuse its create/patch fixtures + config-write-back mocks):
```python
@pytest.mark.asyncio
async def test_patch_source_relevance_thresholds(client, stores):
    # create a github source first (per the file's existing create helper), then:
    src = (await client.get("/api/sources")).json()[0]
    r = await client.patch(f"/api/sources/{src['id']}", json={
        "relevance": {"auto_include_threshold": 0.8, "triage_threshold": 0.5, "drop_below": 0.2}})
    assert r.status_code == 200
    assert r.json()["config"]["relevance"]["auto_include_threshold"] == 0.8
```
- [ ] Step 2: Run test. `python -m pytest tests/test_sources_api.py -k relevance -v --tb=short` — Expected failure: `relevance` ignored / rejected.
- [ ] Step 3: Implementation. Accept a `relevance` block on the PATCH body and merge it into the source `config` dict (validated `0..1` floats: `auto_include_threshold`, `triage_threshold`, `drop_below`) so it flows through the existing `_validate_config` → `yaml_write_source` (Config Write-Back) → live-adapter swap (Targeted Hot-Reload) path. Round-trip the merged config into the response.
- [ ] Step 4: Run test. `python -m pytest tests/test_sources_api.py -k relevance -v --tb=short` — Expected: PASS. `make test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(api): per-source relevance thresholds write-back + hot-reload"`

### Task 23: Shared MSW handlers module
**Files:**
- Create: `ui/src/test/handlers.ts`, `ui/src/test/handlers.test.ts`

- [ ] Step 1: Write `ui/src/test/handlers.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { newEndpointHandlers } from './handlers'

describe('shared MSW handlers', () => {
  it('covers every new endpoint', () => {
    const paths = newEndpointHandlers().map((h) => (h as any).info.path)
    for (const p of ['/api/search', '/api/stats/timeseries', '/api/topology',
                     '/api/actions', '/api/memory/facts']) {
      expect(paths.some((x: string) => x.includes(p))).toBe(true)
    }
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/test/handlers.test.ts` — Expected failure: cannot resolve `./handlers`.
- [ ] Step 3: Implementation. Create `handlers.ts` exporting `newEndpointHandlers()` → array of `http.*` handlers (msw) returning realistic fixtures for `/api/auth/token`, `/api/search`, `/api/stats/overview` (with `metrics`), `/api/stats/timeseries`, `/api/topology`, `POST /api/actions`, `POST /api/memory/facts`, PATCH `/api/sources/:id` (relevance), and `/api/triage/pending` (with `created_at`). Each page test can spread these into its local `setupServer`.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/test/handlers.test.ts` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "test(ui): shared MSW handlers for new endpoints"`

---

## Phase 6 — Pages (Overview → Triage → Action Items → Sources → Ingestion → Knowledge → Settings → Messenger)

### Task 24: Overview hero region + chart-theme swap
**Files:**
- Modify: `ui/src/pages/Overview.tsx`, `ui/src/hooks/useStats.ts`
- Create: `ui/src/hooks/useMetrics.ts`, `ui/src/hooks/useTopology.ts`
- Modify test: `ui/src/pages/Overview.test.tsx`

- [ ] Step 1: Add to `Overview.test.tsx` (extend MSW with metrics + topology + items hot-feed; assert via shared handlers):
```ts
it('renders the attention header + hot feed + initiate-triage CTA', async () => {
  renderOverview() // local helper, MSW returns metrics + a P0 pending item
  expect(await screen.findByText(/hot feed/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /initiate triage/i })).toBeInTheDocument()
})
it('renders the ingestion-success-rate tile (never a literal 99.98%)', async () => {
  renderOverview()
  expect(await screen.findByText(/ingestion success/i)).toBeInTheDocument()
  expect(screen.queryByText('99.98%')).toBeNull()
})
it('renders the infrastructure topology panel', async () => {
  renderOverview()
  expect(await screen.findByText(/infrastructure/i)).toBeInTheDocument()
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/pages/Overview.test.tsx` — Expected failure: hero text absent.
- [ ] Step 3: Implementation. Extend `StatsOverview` with `metrics`. Add `useMetrics.ts` (`useStatsTimeseries(metric, window, bucket)`) and `useTopology.ts` (poll 15s). In `Overview.tsx`: delete `DONUT_COLORS`, import `CHART_COLORS`/`CHART_DEFAULTS`. Keep the 6 StatCards + 4 charts + Recent Jobs. Add a hero region: attention header (P0 active + pending triage), HOT FEED (`GET /api/items?priority=P0|P1&status=pending_triage`), INITIATE TRIAGE button → `/triage` w/ pending count, ingestion-success-rate tile (`metrics.ingestion_success_rate`, "n/a" when null), `<Topology/>` panel, Queue Ingestion Status table (reuse `useSourcesRollup`), dismissible System Alert banner (only on real degraded). Each hero widget fails soft inline; preserve page-level five-state gate. Apply Work Mode hiding in Task 26.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/pages/Overview.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): Overview hero region + chart-theme + topology panel"`

### Task 25: Triage 3-column + keyboard cards + filters + LLM Insight
**Files:**
- Modify: `ui/src/pages/Triage.tsx`, `ui/src/hooks/useTriage.ts`
- Modify test: `ui/src/pages/Triage.test.tsx`

- [ ] Step 1: Add to `Triage.test.tsx`:
```ts
it('renders the left filter rail with source checkboxes + time window', async () => {
  renderTriage() // MSW pending cards include created_at
  expect(await screen.findByText(/last 24h/i)).toBeInTheDocument()
})
it('renders numbered card options [1][2][3] and a free-text reply input', async () => {
  renderTriage()
  expect(await screen.findByText('[1]')).toBeInTheDocument()
  expect(screen.getByPlaceholderText(/press enter/i)).toBeInTheDocument()
})
it('shows the inbox-zero empty state when there are no cards', async () => {
  renderTriageEmpty()
  expect(await screen.findByText(/system harmony|inbox zero/i)).toBeInTheDocument()
})
it('shows a distinct empty state when filters exclude all cards', async () => {
  renderTriage()
  // toggle a filter to exclude all → 'No cards match filters'
  expect(await screen.findByText(/no cards match filters/i)).toBeInTheDocument()
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/pages/Triage.test.tsx` — Expected failure: 3-column + filters absent.
- [ ] Step 3: Implementation. Rebuild `Triage.tsx` as 3 columns. Left: Sources checkboxes+counts, Priority filter, Time Window quad (LAST 1H/24H/7D/ALL) — all client-side filters over the fetched pending cards (Time Window uses the new `created_at`). Center: keyboard card feed — each card shows Item ID + relevance (Mono), `[1][2][3]` options, free-text reply input ("Press Enter to execute"), `J`/`K` nav (keydown), priority/relevance colored left border; preserve ADR0027 free-text replies + the destructive-action confirm round-trip (`/triage/respond` → `awaiting_confirmation` → `/triage/confirm`). Right: Signal Velocity `<Sparkline>` (`useStatsTimeseries('signal_velocity',24,'hour')`), Automation Stats (`auto_resolved_pct`, `avg_triage_seconds`), LLM Insight panel rendered ONLY when per-option `suggestion_reason`/`confidence` present. Two empties: inbox-zero vs no-match.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/pages/Triage.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): Triage 3-column keyboard cards + client filters + LLM insight"`

### Task 26: Work Mode hook + Action Items grouped sections + FAB
**Files:**
- Create: `ui/src/hooks/useWorkMode.ts`, `ui/src/hooks/useWorkMode.test.ts`
- Modify: `ui/src/pages/ActionItems.tsx`, `ui/src/hooks/useActions.ts`, `ui/src/pages/Overview.tsx`
- Modify test: `ui/src/pages/ActionItems.test.tsx`

- [ ] Step 1: Write `ui/src/hooks/useWorkMode.test.ts`:
```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWorkMode } from './useWorkMode'

describe('useWorkMode', () => {
  beforeEach(() => localStorage.clear())
  it('defaults off and toggles, persisting to localStorage', () => {
    const { result } = renderHook(() => useWorkMode())
    expect(result.current.workMode).toBe(false)
    act(() => result.current.setWorkMode(true))
    expect(result.current.workMode).toBe(true)
    expect(localStorage.getItem('workbench.workMode')).toBe('true')
  })
})
```
  Add to `ActionItems.test.tsx`:
```ts
it('groups items into ACTIVE NOW / TODAY / LATER', async () => {
  renderActions() // MSW returns mixed-priority/age items
  expect(await screen.findByText(/active now/i)).toBeInTheDocument()
  expect(screen.getByText(/today/i)).toBeInTheDocument()
  expect(screen.getByText(/later/i)).toBeInTheDocument()
})
it('creates a manual action via the FAB (POST /api/actions)', async () => {
  const user = userEvent.setup()
  renderActions() // MSW POST /api/actions returns the created row
  await user.click(screen.getByRole('button', { name: /new action/i }))
  await user.type(screen.getByLabelText(/summary/i), 'Call vendor')
  await user.click(screen.getByRole('button', { name: /create/i }))
  await waitFor(() => expect(screen.getByText(/action created/i)).toBeInTheDocument())
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/hooks/useWorkMode.test.ts src/pages/ActionItems.test.tsx` — Expected failure: hook missing; groups/FAB absent.
- [ ] Step 3: Implementation. `useWorkMode.ts`: read/write `localStorage['workbench.workMode']`, subscribe to the `storage` event for cross-tab sync; return `{ workMode, setWorkMode }`. `useActions.ts`: add `useCreateAction()` mutation → `apiPost('/api/actions', body)`, invalidate `['actions']`, toast "Action created". `ActionItems.tsx`: replace the flat DataTable with grouped sections ACTIVE NOW = P0 or (P1 & age<24h); TODAY = remaining P1 + P2 age<7d; LATER = P3 + older/snoozed; priority left-border rows; preserve category filter + set-priority + done/snooze. Add throughput bar + efficiency_peak card (metrics) + Work Mode card. Orange FAB → dialog form → `useCreateAction`. In `Overview.tsx`, consume `useWorkMode` to hide non-critical hero widgets when ON.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/hooks/useWorkMode.test.ts src/pages/ActionItems.test.tsx src/pages/Overview.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): Work Mode hook + Action Items grouped sections + manual-action FAB"`

### Task 27: Topology SVG component (+ a11y table fallback)
**Files:**
- Create: `ui/src/components/Topology.tsx`, `ui/src/components/Topology.test.tsx`

- [ ] Step 1: Write `ui/src/components/Topology.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Topology } from './Topology'

const data = {
  nodes: [{ id: 'app', label: 'Workbench', kind: 'app', status: 'healthy' },
          { id: 'pg', label: 'PostgreSQL', kind: 'storage', status: 'healthy' },
          { id: 'memory', label: 'Memory Service', kind: 'memory_service', status: 'not_configured' }],
  edges: [{ from: 'app', to: 'pg', kind: 'connection' }],
}

describe('Topology', () => {
  it('renders an svg labelled as an image', () => {
    render(<Topology data={data} />)
    expect(screen.getByRole('img', { name: /topology/i })).toBeInTheDocument()
  })
  it('renders a visually-hidden a11y table of node statuses', () => {
    render(<Topology data={data} />)
    expect(screen.getByText('PostgreSQL')).toBeInTheDocument()
    expect(screen.getByText('not_configured')).toBeInTheDocument()
  })
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/Topology.test.tsx` — Expected failure: cannot resolve `./Topology`.
- [ ] Step 3: Implementation. `Topology.tsx` takes `{ data }` (typed from `useTopology`). Hand-roll a 2D SVG node-link graph (`role="img"`, `aria-label="Infrastructure topology"`), techy styling, status-colored nodes (healthy=green/cyan, degraded=amber, unhealthy=red, not_configured/unknown=muted), `<line>` edges; NO react-three-fiber/reactflow. Add a `sr-only` `<table>` of nodes (label + status) for a11y. Wire into the Overview INFRASTRUCTURE panel via `useTopology`.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/Topology.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): 2D SVG Topology component + a11y table fallback"`

### Task 28: Sources card grid + relevance-threshold config drawer
**Files:**
- Modify: `ui/src/pages/Sources.tsx`, `ui/src/hooks/useSources.ts`
- Modify test: `ui/src/pages/Sources.test.tsx`

- [ ] Step 1: Add to `Sources.test.tsx`:
```ts
it('renders one card per real adapter + a Connect New Source card', async () => {
  renderSources() // MSW returns a github source rollup
  expect(await screen.findByText('github')).toBeInTheDocument()
  expect(screen.getByText(/connect new source/i)).toBeInTheDocument()
})
it('opens the config drawer with relevance-threshold sliders', async () => {
  const user = userEvent.setup()
  renderSources()
  await user.click(await screen.findByRole('button', { name: /configure github/i }))
  expect(await screen.findByText(/noise filter|auto.?include/i)).toBeInTheDocument()
})
it('never renders mockup adapter names', async () => {
  renderSources()
  await screen.findByText('github')
  for (const m of ['Jira', 'Slack', 'PagerDuty', 'Linear']) {
    expect(screen.queryByText(m)).toBeNull()
  }
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/pages/Sources.test.tsx` — Expected failure: card grid / drawer absent.
- [ ] Step 3: Implementation. Rebuild `Sources.tsx` as a card grid: one card per configured adapter (github/email/calendar/chat only) with `HealthBadge`, last sync = `last_run`, volume `<Sparkline>` from `items_stored`, enable `Switch`, kebab Edit/Poll/Enable/Delete (confirm). Dashed "Connect New Source" card → existing 2-step `SourceForm` wizard (cron preview). Top StatCards: Active Pipes, Ingestion Volume, Errors. Per-source Config Drawer (Radix Dialog/sheet) with relevance-threshold sliders (auto_include/triage/drop_below) → `useUpdateSource` PATCH with `{ relevance }` (Task 22), round-tripped to `config.yml` + hot-reload.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/pages/Sources.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): Sources card grid + relevance-threshold config drawer"`

### Task 29: Ingestion restyle + LIVE log
**Files:**
- Modify: `ui/src/pages/Ingestion.tsx`
- Modify test: `ui/src/pages/Ingestion.test.tsx`

- [ ] Step 1: Add to `Ingestion.test.tsx`:
```ts
it('renders the LIVE ingestion log via LogStream', async () => {
  renderIngestion() // MSW /api/activity returns a couple of rows
  expect(await screen.findByText(/live.*log/i)).toBeInTheDocument()
  expect(screen.getByRole('log')).toBeInTheDocument()
})
it('drops the System Latency widget', async () => {
  renderIngestion()
  await screen.findByText(/live.*log/i)
  expect(screen.queryByText(/system latency/i)).toBeNull()
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/pages/Ingestion.test.tsx` — Expected failure: LIVE log absent.
- [ ] Step 3: Implementation. Restyle existing panels (Recent Activity, Job History filter+pagination, Queue Health StatCards+bar, Dead Letters Retry/Purge confirm) to tokens. Add a LIVE INGESTION LOG section wiring `useActivity()` (15s poll, already in `useStats.ts`) → `<LogStream lines={...}>`. Remove the System Latency widget; show last-sync age instead. Errors = erroring-source count proxy.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/pages/Ingestion.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): Ingestion restyle + LIVE log, drop System Latency"`

### Task 30: Knowledge — Add Fact + growth velocity + StatCards
**Files:**
- Modify: `ui/src/pages/Knowledge.tsx`, `ui/src/hooks/useFacts.ts`
- Modify test: `ui/src/pages/Knowledge.test.tsx`

- [ ] Step 1: Add to `Knowledge.test.tsx`:
```ts
it('renders Total Facts / Active Sources / Growth Velocity stat cards', async () => {
  renderKnowledge() // available=true, facts present
  expect(await screen.findByText(/total facts/i)).toBeInTheDocument()
  expect(screen.getByText(/growth velocity/i)).toBeInTheDocument()
})
it('renders n/a growth velocity under noop memory (not a fake number)', async () => {
  renderKnowledgeNoop() // available=false, memory_type=noop
  expect(await screen.findByText(/n\/a/i)).toBeInTheDocument()
})
it('creates a manual fact via Add Fact (POST /api/memory/facts)', async () => {
  const user = userEvent.setup()
  renderKnowledge() // MSW POST returns created fact
  await user.click(screen.getByRole('button', { name: /add fact/i }))
  await user.type(screen.getByLabelText(/content/i), 'prefers async standups')
  await user.click(screen.getByRole('button', { name: /save/i }))
  await waitFor(() => expect(screen.getByText(/fact added/i)).toBeInTheDocument())
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/pages/Knowledge.test.tsx` — Expected failure: Add Fact / growth velocity absent.
- [ ] Step 3: Implementation. `useFacts.ts`: add `useCreateFact()` → `apiPost('/api/memory/facts', body)`, handle 501 (disable when noop). `Knowledge.tsx`: StatCards Total Facts (`facts.length`), Active Sources (`sources_enabled`), Growth Velocity (the **scalar** `metrics.growth_velocity` from `useStats`/`useMetrics` — a single StatCard number, render "n/a" under noop; there is NO facts timeseries, `/api/stats/timeseries` only serves `signal_velocity|throughput`); facts TABLE with source pills + date (`Fact.timestamp`, em-dash when null) and a GROUP BY SOURCE toggle; "Add Fact" button → dialog form → `useCreateFact` (disabled/501 under noop). Preserve edit/delete + degraded states. (Knowledge.tsx has no Overview/Metrics/Logs tabs — nothing to drop; net-new work is Add Fact + Growth Velocity + StatCards.)
- [ ] Step 4: Run test. `cd ui && npx vitest run src/pages/Knowledge.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): Knowledge Add Fact + growth velocity + StatCards"`

### Task 31: Settings — JSON highlighter + drop Runtime Metadata
**Files:**
- Create: `ui/src/components/JsonHighlight.tsx`, `ui/src/components/JsonHighlight.test.tsx`
- Modify: `ui/src/pages/Settings.tsx`
- Modify test: `ui/src/pages/Settings.test.tsx`

- [ ] Step 1: Write `ui/src/components/JsonHighlight.test.tsx`:
```ts
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { JsonHighlight } from './JsonHighlight'

describe('JsonHighlight', () => {
  it('tokenizes keys/strings/numbers into spans (no dangerouslySetInnerHTML)', () => {
    const { container } = render(<JsonHighlight json={'{"name":"workbench","port":8421}'} />)
    expect(screen.getByText(/"name"/)).toBeInTheDocument()
    expect(screen.getByText('8421')).toBeInTheDocument()
    expect(container.querySelector('[dangerouslySetInnerHTML]')).toBeNull()
    expect(container.querySelectorAll('span').length).toBeGreaterThan(1)
  })
})
```
  Add to `Settings.test.tsx`:
```ts
it('drops the vanity Runtime Metadata block', async () => {
  renderSettings()
  await screen.findByText(/app version/i)
  for (const m of [/kernel/i, /network latency/i]) {
    expect(screen.queryByText(m)).toBeNull()
  }
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/components/JsonHighlight.test.tsx src/pages/Settings.test.tsx` — Expected failure: component missing; Runtime Metadata present.
- [ ] Step 3: Implementation. `JsonHighlight.tsx`: pretty-print the JSON, regex-split into tokens, map keys→`#ffb59a`, strings→`#71d2ff`, numbers→`on-surface`, punctuation→`on-surface-variant` as `<span>`s (NO `dangerouslySetInnerHTML`). `Settings.tsx`: keep App Version (`health.version`) + Config Version + Subsystem Health badges; render config blocks (pipeline/scheduler/retention/alerting) through `<JsonHighlight>`; keep CONFIG_SECRETS locked (ADR0017); DOWNLOAD BACKUP = client `Blob` of redacted `GET /api/debug/config`. Drop the Runtime Metadata block (keep process Uptime only if a real start-time is exposed, else drop).
- [ ] Step 4: Run test. `cd ui && npx vitest run src/components/JsonHighlight.test.tsx src/pages/Settings.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): Settings JSON highlighter + drop vanity Runtime Metadata"`

### Task 32: Messenger token restyle
**Files:**
- Modify: `ui/src/pages/Messenger.tsx`
- Modify test: `ui/src/pages/Messenger.test.tsx`

- [ ] Step 1: Add a guard test to `Messenger.test.tsx` (the page already covers read + edit + degraded; add a restyle/no-regression assertion):
```ts
it('still renders non-secret config + reachability badge after restyle', async () => {
  renderMessenger() // configured messenger via MSW
  expect(await screen.findByText(/space_id/i)).toBeInTheDocument()
  expect(screen.getByText(/timeout_seconds/i)).toBeInTheDocument()
})
it('shows the no-messenger degraded state', async () => {
  renderMessengerUnconfigured()
  expect(await screen.findByText(/no messenger|not configured/i)).toBeInTheDocument()
})
```
- [ ] Step 2: Run test. `cd ui && npx vitest run src/pages/Messenger.test.tsx` — Expected: PASS or fail depending on existing copy; adjust assertions to match current labels first, then proceed.
- [ ] Step 3: Implementation. Restyle `Messenger.tsx` to the new tokens (Card/Badge/Input primitives, Mono for IDs/timeouts). Preserve the non-secret-only read (space_id, timeout_seconds), reachability `HealthBadge`, RHF/Zod edit form, and the "no messenger" degraded state. No new endpoints.
- [ ] Step 4: Run test. `cd ui && npx vitest run src/pages/Messenger.test.tsx` — Expected: PASS. `make ui-test` — Expected: PASS. Final full sweep: `make ui-test && make test` — Expected: both PASS.
- [ ] Step 5: Commit. `git add -A && git commit -m "feat(ui): Messenger token restyle"`

---

## Final verification (run before declaring done)
- `make ui-test` and `make test` both green.
- `cd ui && npm run build` succeeds (Tailwind `@theme` compiles; fonts bundle offline — no `fonts.googleapis.com`/`cdn.tailwindcss.com` references in `dist/`).
- Manual sweep against spec §Verification 1–15: theme toggle (orange `--ring` constant both themes), offline fonts, icon rail a11y, ⌘K grouped search (facts omitted under noop), metrics block null→"n/a", zero-filled timeseries, topology SVG + a11y table, Work Mode cross-tab sync, Overview hero, Triage keyboard cards, Action Items groups + FAB, Sources thresholds write-back, Ingestion LIVE log, Knowledge Add Fact (501 under noop), Settings highlighter + locked secrets, every dropped hollow widget absent, no orange text on surfaces > `#2a2a2d`.
