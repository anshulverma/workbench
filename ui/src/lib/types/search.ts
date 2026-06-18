import type { FunnelStage, Verdict } from './funnel'

export type ItemKind = 'diff' | 'pr' | 'email' | 'meeting' | 'chat'

export type ItemState = 'triaged' | 'pending_triage' | 'action_item' | 'dropped' | 'archived'

export interface DiffContext {
  type: 'diff'
  author: string
  team: string
  status: string
  url: string
  hunks: Array<{
    file: string
    header: string
    rank: number
    annotation?: string
    code: string
  }>
}

export interface EmailContext {
  type: 'email'
  from: string
  to: string
  when: string
  body: string
}

export interface MeetingContext {
  type: 'meeting'
  when: string
  duration: string
  location: string
  attendees: string[]
  agenda: string | null
}

export interface ChatContext {
  type: 'chat'
  channel: string
  messages: Array<{
    who: string
    text: string
    when: string
  }>
}

export type ItemContext = DiffContext | EmailContext | MeetingContext | ChatContext

export interface SearchItem {
  id: number
  kind: ItemKind
  path?: string
  summary: string
  source: string
  priority: string | null
  state: ItemState
  relevance: number
  tags: string[]
  created_at: string
  llm_summary: string
  context: ItemContext | null
  stages: FunnelStage[]
  verdict: Verdict
}
