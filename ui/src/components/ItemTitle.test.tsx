import { describe, expect, it } from 'vitest'
import { splitTitle, titleText } from './ItemTitle'

describe('splitTitle', () => {
  it('bolds the diff ref and the trailing status clause, appends "by you" for diffs', () => {
    const segs = splitTitle(
      'Diff D109114293 addressing the check in mitra is awaiting review/publication',
      'diff',
    )
    expect(segs[0]).toEqual({ text: 'Diff D109114293', bold: true })
    // last segment is the bold status clause with " by you" appended
    const last = segs[segs.length - 1]
    expect(last.bold).toBe(true)
    expect(last.text).toBe('awaiting review/publication by you')
    expect(titleText(
      'Diff D109114293 addressing the check in mitra is awaiting review/publication',
      'diff',
    )).toBe(
      'Diff D109114293 addressing the check in mitra is awaiting review/publication by you',
    )
  })

  it('does not duplicate "by you" when already present', () => {
    const segs = splitTitle('Diff D1 thing is awaiting review by you', 'diff')
    expect(segs[segs.length - 1].text).toBe('awaiting review by you')
  })

  it('does not append "by you" for non-diff items', () => {
    const segs = splitTitle('Task T1 is blocked', 'task')
    expect(segs[segs.length - 1]).toEqual({ text: 'blocked', bold: true })
  })

  it('handles a summary with no diff ref and no status clause', () => {
    const segs = splitTitle('just a plain summary', 'diff')
    expect(segs).toEqual([{ text: 'just a plain summary', bold: false }])
  })
})
