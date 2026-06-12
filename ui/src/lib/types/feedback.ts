import type { StageOutcome } from './funnel'

export interface FeedbackOverride {
  id: string
  itemId: string
  itemSummary: string
  filterId: string
  filterPrompt: string
  fromOutcome: StageOutcome
  fromLabel?: string
  toOutcome: StageOutcome
  toLabel?: string
  at: number
}

export type TuningTaskStatus = 'open' | 'applied' | 'dismissed'

export interface FilterTuningTask {
  id: string
  kind: 'filter-tuning'
  status: TuningTaskStatus
  itemId: string
  itemSummary: string
  filterId: string
  filterPrompt: string
  fromOutcome: StageOutcome
  fromLabel?: string
  toOutcome: StageOutcome
  toLabel?: string
  proposedPrompt: string
  at: number
}
