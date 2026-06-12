// feedback-store.test.ts — WBFeedback singleton tests.
//
// Covers: addOverride creates task via refinedPrompt, removeOverride clears +
// dismisses, autoApply updates promptPatches, promptFor fallback, subscribe/
// notify, localStorage roundtrip, cross-tab sync via storage event,
// localStorage fallback (in-memory when setItem throws).

import { describe, it, expect, beforeEach, vi } from 'vitest'

// We need a fresh module per test to reset the singleton state. vitest module
// isolation handles this via vi.resetModules() + dynamic import().

async function loadStore() {
  vi.resetModules()
  localStorage.clear()
  const mod = await import('./feedback-store')
  return mod
}

describe('WBFeedback', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  // -----------------------------------------------------------------------
  // addOverride
  // -----------------------------------------------------------------------

  it('addOverride creates an override and a matching tuning task', async () => {
    const { WBFeedback } = await loadStore()
    const ov = WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR #42 adds retry logic',
      filterId: 'f-1',
      filterPrompt: 'Drop low-value diffs.',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })

    expect(ov.id).toMatch(/^ovr_/)
    expect(ov.itemId).toBe('item-1')
    expect(WBFeedback.state.overrides).toHaveLength(1)
    expect(WBFeedback.state.tasks).toHaveLength(1)

    const task = WBFeedback.state.tasks[0]
    expect(task.id).toMatch(/^act_ft_/)
    expect(task.kind).toBe('filter-tuning')
    expect(task.status).toBe('open')
    expect(task.proposedPrompt).toContain('Drop low-value diffs')
    expect(task.proposedPrompt).toContain('PR #42 adds retry logic')
    expect(task.proposedPrompt).toContain('you corrected this')
    expect(task.proposedPrompt).toContain('kept and surfaced')
  })

  it('addOverride with "drop" toOutcome produces "dropped" in proposed prompt', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.addOverride({
      itemId: 'item-2',
      itemSummary: 'spam email',
      filterId: 'f-2',
      filterPrompt: 'Include newsletters.',
      fromOutcome: 'include',
      toOutcome: 'drop',
    })
    const task = WBFeedback.state.tasks[0]
    expect(task.proposedPrompt).toContain('dropped')
  })

  it('addOverride with "label" toOutcome includes the label in proposed prompt', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.addOverride({
      itemId: 'item-3',
      itemSummary: 'phishing attempt',
      filterId: 'f-3',
      filterPrompt: 'Include all emails.',
      fromOutcome: 'include',
      toOutcome: 'label',
      toLabel: 'phishing',
    })
    const task = WBFeedback.state.tasks[0]
    expect(task.proposedPrompt).toContain('labeled phishing')
  })

  it('addOverride replaces an existing override for the same item+filter', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR #42',
      filterId: 'f-1',
      filterPrompt: 'Drop low-value diffs.',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR #42 v2',
      filterId: 'f-1',
      filterPrompt: 'Drop low-value diffs.',
      fromOutcome: 'drop',
      toOutcome: 'pass',
    })

    expect(WBFeedback.state.overrides).toHaveLength(1)
    expect(WBFeedback.state.overrides[0].itemSummary).toBe('PR #42 v2')
    expect(WBFeedback.state.tasks).toHaveLength(1)
    expect(WBFeedback.state.tasks[0].proposedPrompt).toContain('left untouched')
  })

  // -----------------------------------------------------------------------
  // removeOverride
  // -----------------------------------------------------------------------

  it('removeOverride clears the override and dismisses the open task', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR',
      filterId: 'f-1',
      filterPrompt: 'prompt',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    expect(WBFeedback.state.overrides).toHaveLength(1)
    expect(WBFeedback.state.tasks).toHaveLength(1)

    WBFeedback.removeOverride('item-1', 'f-1')

    expect(WBFeedback.state.overrides).toHaveLength(0)
    expect(WBFeedback.state.tasks).toHaveLength(0)
  })

  it('removeOverride does not remove tasks that were already applied', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR',
      filterId: 'f-1',
      filterPrompt: 'prompt',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    const taskId = WBFeedback.state.tasks[0].id
    WBFeedback.autoApply(taskId)
    expect(WBFeedback.state.tasks[0].status).toBe('applied')

    WBFeedback.removeOverride('item-1', 'f-1')

    // Override is removed but applied task is preserved.
    expect(WBFeedback.state.overrides).toHaveLength(0)
    expect(WBFeedback.state.tasks).toHaveLength(1)
    expect(WBFeedback.state.tasks[0].status).toBe('applied')
  })

  // -----------------------------------------------------------------------
  // autoApply
  // -----------------------------------------------------------------------

  it('autoApply updates promptPatches and marks the task applied', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR',
      filterId: 'f-1',
      filterPrompt: 'Drop diffs.',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    const task = WBFeedback.state.tasks[0]
    WBFeedback.autoApply(task.id)

    expect(task.status).toBe('applied')
    expect(WBFeedback.state.promptPatches['f-1']).toBe(task.proposedPrompt)
  })

  it('autoApply is a no-op for unknown taskId', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.autoApply('nonexistent')
    expect(Object.keys(WBFeedback.state.promptPatches)).toHaveLength(0)
  })

  // -----------------------------------------------------------------------
  // dismissTask
  // -----------------------------------------------------------------------

  it('dismissTask marks the task as dismissed', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR',
      filterId: 'f-1',
      filterPrompt: 'prompt',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    const task = WBFeedback.state.tasks[0]
    WBFeedback.dismissTask(task.id)
    expect(task.status).toBe('dismissed')
  })

  // -----------------------------------------------------------------------
  // Lookups
  // -----------------------------------------------------------------------

  it('overrideFor returns null when no match', async () => {
    const { WBFeedback } = await loadStore()
    expect(WBFeedback.overrideFor('nope', 'nope')).toBeNull()
  })

  it('overrideFor returns the matching override', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR',
      filterId: 'f-1',
      filterPrompt: 'prompt',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    const result = WBFeedback.overrideFor('item-1', 'f-1')
    expect(result).not.toBeNull()
    expect(result!.itemId).toBe('item-1')
  })

  it('feedbackForFilter returns all overrides for a given filter', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR1',
      filterId: 'f-1',
      filterPrompt: 'prompt',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    WBFeedback.addOverride({
      itemId: 'item-2',
      itemSummary: 'PR2',
      filterId: 'f-1',
      filterPrompt: 'prompt',
      fromOutcome: 'drop',
      toOutcome: 'pass',
    })
    WBFeedback.addOverride({
      itemId: 'item-3',
      itemSummary: 'PR3',
      filterId: 'f-2',
      filterPrompt: 'other',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    expect(WBFeedback.feedbackForFilter('f-1')).toHaveLength(2)
    expect(WBFeedback.feedbackForFilter('f-2')).toHaveLength(1)
    expect(WBFeedback.feedbackForFilter('f-3')).toHaveLength(0)
  })

  it('openTasks returns only open tasks', async () => {
    const { WBFeedback } = await loadStore()
    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR1',
      filterId: 'f-1',
      filterPrompt: 'p',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    WBFeedback.addOverride({
      itemId: 'item-2',
      itemSummary: 'PR2',
      filterId: 'f-2',
      filterPrompt: 'p',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    WBFeedback.dismissTask(WBFeedback.state.tasks[0].id)
    expect(WBFeedback.openTasks()).toHaveLength(1)
    expect(WBFeedback.openTasks()[0].itemId).toBe('item-2')
  })

  it('promptFor returns the patched prompt or the fallback', async () => {
    const { WBFeedback } = await loadStore()
    expect(WBFeedback.promptFor('f-1', 'fallback')).toBe('fallback')

    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR',
      filterId: 'f-1',
      filterPrompt: 'Drop diffs.',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    WBFeedback.autoApply(WBFeedback.state.tasks[0].id)
    expect(WBFeedback.promptFor('f-1', 'fallback')).toContain('Drop diffs')
    expect(WBFeedback.promptFor('f-1', 'fallback')).not.toBe('fallback')
  })

  // -----------------------------------------------------------------------
  // subscribe / notify
  // -----------------------------------------------------------------------

  it('subscribe notifies listeners on state changes', async () => {
    const { WBFeedback } = await loadStore()
    const spy = vi.fn()
    const unsub = WBFeedback.subscribe(spy)

    WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR',
      filterId: 'f-1',
      filterPrompt: 'prompt',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    expect(spy).toHaveBeenCalledTimes(1)

    WBFeedback.removeOverride('item-1', 'f-1')
    expect(spy).toHaveBeenCalledTimes(2)

    unsub()
    WBFeedback.addOverride({
      itemId: 'item-2',
      itemSummary: 'PR2',
      filterId: 'f-2',
      filterPrompt: 'prompt',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })
    // No more calls after unsubscribe.
    expect(spy).toHaveBeenCalledTimes(2)
  })

  // -----------------------------------------------------------------------
  // localStorage roundtrip
  // -----------------------------------------------------------------------

  it('persists state to localStorage and restores on fresh load', async () => {
    const { WBFeedback: store1 } = await loadStore()
    store1.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR',
      filterId: 'f-1',
      filterPrompt: 'prompt',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })

    // Verify localStorage has the data.
    const raw = localStorage.getItem('wb:feedback')
    expect(raw).not.toBeNull()
    const parsed = JSON.parse(raw!)
    expect(parsed.overrides).toHaveLength(1)
    expect(parsed.tasks).toHaveLength(1)

    // Load a fresh module that reads from the same localStorage.
    vi.resetModules()
    const { WBFeedback: store2 } = await import('./feedback-store')
    expect(store2.state.overrides).toHaveLength(1)
    expect(store2.state.overrides[0].itemId).toBe('item-1')
    expect(store2.state.tasks).toHaveLength(1)
  })

  // -----------------------------------------------------------------------
  // Cross-tab sync via storage event
  // -----------------------------------------------------------------------

  it('syncs state across tabs via the storage event', async () => {
    const { WBFeedback } = await loadStore()
    const spy = vi.fn()
    WBFeedback.subscribe(spy)

    const crossTabState = {
      overrides: [
        {
          id: 'ovr_cross',
          itemId: 'cross-item',
          itemSummary: 'Cross-tab PR',
          filterId: 'f-cross',
          filterPrompt: 'prompt',
          fromOutcome: 'drop',
          toOutcome: 'include',
          at: Date.now(),
        },
      ],
      tasks: [],
      promptPatches: { 'f-cross': 'patched prompt' },
    }

    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'wb:feedback',
        newValue: JSON.stringify(crossTabState),
      }),
    )

    expect(WBFeedback.state.overrides).toHaveLength(1)
    expect(WBFeedback.state.overrides[0].itemId).toBe('cross-item')
    expect(WBFeedback.state.promptPatches['f-cross']).toBe('patched prompt')
    expect(spy).toHaveBeenCalled()
  })

  it('ignores storage events for other keys', async () => {
    const { WBFeedback } = await loadStore()
    const spy = vi.fn()
    WBFeedback.subscribe(spy)

    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'other-key',
        newValue: '{}',
      }),
    )

    expect(spy).not.toHaveBeenCalled()
  })

  // -----------------------------------------------------------------------
  // localStorage fallback (in-memory when setItem throws)
  // -----------------------------------------------------------------------

  it('falls back to in-memory storage when localStorage.setItem throws', async () => {
    const { WBFeedback } = await loadStore()

    // Make setItem throw to simulate storage full / blocked.
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })

    // Should not throw — falls back to in-memory.
    const ov = WBFeedback.addOverride({
      itemId: 'item-1',
      itemSummary: 'PR',
      filterId: 'f-1',
      filterPrompt: 'prompt',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })

    expect(ov.itemId).toBe('item-1')
    expect(WBFeedback.state.overrides).toHaveLength(1)

    vi.restoreAllMocks()
  })
})
