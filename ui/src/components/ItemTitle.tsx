// ItemTitle — renders an item summary as a readable title with emphasis: the
// leading source ref (e.g. "Diff D109114293") and the trailing status clause
// (the part after the last " is ") are bolded. For diffs, " by you" is appended
// to the status clause when absent — every ingested diff is one the user either
// authored or is reviewing, so the queue is always "awaiting … by you".

export interface TitleSegment {
  text: string
  bold: boolean
}

const DIFF_REF = /^(Diff\s+D\d+)/i

/** Split a summary into emphasis segments. Pure + exported for testing. */
export function splitTitle(summary: string, kind?: string): TitleSegment[] {
  const segments: TitleSegment[] = []
  let rest = summary

  const ref = rest.match(DIFF_REF)
  if (ref) {
    segments.push({ text: ref[1], bold: true })
    rest = rest.slice(ref[1].length)
  }

  // Bold the trailing status clause introduced by the last " is ".
  const idx = rest.lastIndexOf(' is ')
  if (idx >= 0) {
    const before = rest.slice(0, idx + 4) // keep " is " unbolded
    let clause = rest.slice(idx + 4)
    if (kind === 'diff' && clause.trim() && !/by you\b/i.test(clause)) {
      clause = clause.replace(/[\s.]*$/, '') + ' by you'
    }
    segments.push({ text: before, bold: false })
    segments.push({ text: clause, bold: true })
  } else if (rest) {
    segments.push({ text: rest, bold: false })
  }

  return segments
}

/** Plain-text form (status clause normalized, "by you" applied) — for the
 *  accessible DialogTitle name and tooltips. */
export function titleText(summary: string, kind?: string): string {
  return splitTitle(summary, kind)
    .map((s) => s.text)
    .join('')
}

export function ItemTitle({
  summary,
  kind,
  className,
}: {
  summary: string
  kind?: string
  className?: string
}) {
  const segments = splitTitle(summary, kind)
  return (
    <span className={className}>
      {segments.map((s, i) =>
        s.bold ? (
          <strong key={i} className="font-semibold">
            {s.text}
          </strong>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </span>
  )
}
