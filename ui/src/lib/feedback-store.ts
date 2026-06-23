// feedback-store.ts — client-side feedback correction store.
//
// A module-scoped singleton (WBFeedback) with pub/sub, localStorage persistence
// (with in-memory fallback), and cross-tab sync via the storage event. React
// views subscribe via useFeedbackStore() in hooks/useFeedback.ts.
//
// Override/task 1:1 relationship: addOverride creates a tuning task,
// removeOverride dismisses the open task.

import type { FeedbackOverride, FilterTuningTask } from '@/lib/types/feedback'
import type { StageOutcome } from '@/lib/types/funnel'
import { refinedPrompt } from '@/lib/funnel-helpers'

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

export interface FeedbackState {
  overrides: FeedbackOverride[]
  tasks: FilterTuningTask[]
  promptPatches: Record<string, string>
}

const STORAGE_KEY = 'wb:feedback'

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

function uid(prefix: string): string {
  return prefix + Math.random().toString(36).slice(2, 7)
}

// ---------------------------------------------------------------------------
// localStorage helpers (in-memory fallback when storage throws)
// ---------------------------------------------------------------------------

let storageAvailable = true

function tryLoad(): FeedbackState | null {
  if (!storageAvailable) return null
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as FeedbackState
  } catch {
    return null
  }
}

function trySave(state: FeedbackState): void {
  if (!storageAvailable) return
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // Storage full or blocked — fall back to in-memory only.
    storageAvailable = false
  }
}

// ---------------------------------------------------------------------------
// Singleton
// ---------------------------------------------------------------------------

const state: FeedbackState = tryLoad() ?? { overrides: [], tasks: [], promptPatches: {} }
const listeners = new Set<() => void>()

function emit(): void {
  trySave(state)
  listeners.forEach((fn) => fn())
}

export interface AddOverrideInput {
  itemId: string
  itemSummary: string
  filterId: string
  filterPrompt: string
  fromOutcome: StageOutcome
  fromLabel?: string
  toOutcome: StageOutcome
  toLabel?: string
}

export interface WBFeedbackAPI {
  readonly state: FeedbackState

  /** Subscribe to state changes; returns an unsubscribe function. */
  subscribe(fn: () => void): () => void

  /** Get the snapshot (for useSyncExternalStore). */
  getSnapshot(): FeedbackState

  /** Lookup a single override by item+filter. */
  overrideFor(itemId: string, filterId: string): FeedbackOverride | null

  /** All overrides for a given filter. */
  feedbackForFilter(filterId: string): FeedbackOverride[]

  /** All tasks with status === 'open'. */
  openTasks(): FilterTuningTask[]

  /** Return the patched prompt for a filter, or the fallback. */
  promptFor(filterId: string, fallback: string): string

  /** Add (or replace) an override and create the matching tuning task. */
  addOverride(input: AddOverrideInput): FeedbackOverride

  /** Remove an override and dismiss its open task. */
  removeOverride(itemId: string, filterId: string): void

  /** Apply a tuning task: update promptPatches and mark the task applied. */
  autoApply(taskId: string): void

  /** Dismiss a tuning task without applying. */
  dismissTask(taskId: string): void
}

export const WBFeedback: WBFeedbackAPI = {
  state,

  subscribe(fn: () => void): () => void {
    listeners.add(fn)
    return () => {
      listeners.delete(fn)
    }
  },

  getSnapshot(): FeedbackState {
    return state
  },

  overrideFor(itemId: string, filterId: string): FeedbackOverride | null {
    return (
      state.overrides.find((o) => o.itemId === itemId && o.filterId === filterId) ?? null
    )
  },

  feedbackForFilter(filterId: string): FeedbackOverride[] {
    return state.overrides.filter((o) => o.filterId === filterId)
  },

  openTasks(): FilterTuningTask[] {
    return state.tasks.filter((t) => t.status === 'open')
  },

  promptFor(filterId: string, fallback: string): string {
    return state.promptPatches[filterId] || fallback
  },

  addOverride(input: AddOverrideInput): FeedbackOverride {
    const { itemId, itemSummary, filterId, filterPrompt, fromOutcome, fromLabel, toOutcome, toLabel } = input

    // Remove any existing override for this item+filter pair.
    state.overrides = state.overrides.filter(
      (o) => !(o.itemId === itemId && o.filterId === filterId),
    )

    const ov: FeedbackOverride = {
      id: uid('ovr_'),
      itemId,
      itemSummary,
      filterId,
      filterPrompt,
      fromOutcome,
      fromLabel,
      toOutcome,
      toLabel,
      at: Date.now(),
    }
    state.overrides.push(ov)

    // (Re)create the matching tuning task.
    state.tasks = state.tasks.filter(
      (t) => !(t.itemId === itemId && t.filterId === filterId),
    )
    state.tasks.push({
      id: uid('act_ft_'),
      kind: 'filter-tuning',
      status: 'open',
      itemId,
      itemSummary,
      filterId,
      filterPrompt,
      fromOutcome,
      fromLabel,
      toOutcome,
      toLabel,
      proposedPrompt: refinedPrompt(filterPrompt, itemSummary, toOutcome, toLabel),
      at: Date.now(),
    })

    emit()
    return ov
  },

  removeOverride(itemId: string, filterId: string): void {
    state.overrides = state.overrides.filter(
      (o) => !(o.itemId === itemId && o.filterId === filterId),
    )
    // Dismiss open tasks for this item+filter pair (remove them).
    state.tasks = state.tasks.filter(
      (t) => !(t.itemId === itemId && t.filterId === filterId && t.status === 'open'),
    )
    emit()
  },

  autoApply(taskId: string): void {
    const t = state.tasks.find((x) => x.id === taskId)
    if (!t) return
    state.promptPatches[t.filterId] = t.proposedPrompt
    t.status = 'applied'
    emit()
  },

  dismissTask(taskId: string): void {
    const t = state.tasks.find((x) => x.id === taskId)
    if (t) {
      t.status = 'dismissed'
      emit()
    }
  },
}

// ---------------------------------------------------------------------------
// Cross-tab sync
// ---------------------------------------------------------------------------

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e: StorageEvent) => {
    if (e.key !== STORAGE_KEY) return
    const loaded = e.newValue ? (JSON.parse(e.newValue) as FeedbackState) : null
    if (loaded) {
      state.overrides = loaded.overrides
      state.tasks = loaded.tasks
      state.promptPatches = loaded.promptPatches
      // Notify listeners but do NOT re-save (the other tab already saved).
      listeners.forEach((fn) => fn())
    }
  })

  // Expose for debugging.
  ;(window as unknown as Record<string, unknown>).WBFeedback = WBFeedback
}
