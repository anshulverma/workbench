// CSS-only +/- diff renderer with per-file expand. No syntax-highlight or diff
// library (ADR 0028). The highest-rank (rank 1) hunk auto-expands; others start
// collapsed.
import { useState } from 'react'

export interface Hunk {
  file: string
  header: string
  code: string
  annotation?: string
  rank: number
}

function lineClass(line: string): string {
  if (line.startsWith('+')) return 'diff-add bg-green-950/40 text-green-300'
  if (line.startsWith('-')) return 'diff-del bg-red-950/40 text-red-300'
  return 'diff-ctx text-muted-foreground'
}

function HunkBlock({ hunk, defaultOpen }: { hunk: Hunk; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded border border-border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between p-2 text-left font-mono text-sm"
      >
        <span>
          {hunk.file} <span className="text-muted-foreground">{hunk.header}</span>
        </span>
        <span>{open ? '−' : '+'}</span>
      </button>
      {open && (
        <pre className="overflow-x-auto p-2 text-xs">
          {hunk.code.split('\n').map((line, i) => (
            <div key={i} className={lineClass(line)}>
              {line || ' '}
            </div>
          ))}
        </pre>
      )}
    </div>
  )
}

export function DiffHunks({ hunks, maxHunks }: { hunks: Hunk[]; maxHunks: number }) {
  const sorted = [...hunks].sort((a, b) => a.rank - b.rank).slice(0, maxHunks)
  const topRank = sorted.length ? sorted[0].rank : -1
  return (
    <div className="space-y-2">
      {sorted.map((h) => (
        <HunkBlock key={`${h.file}-${h.rank}`} hunk={h} defaultOpen={h.rank === topRank} />
      ))}
    </div>
  )
}
