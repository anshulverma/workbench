import type { StageOutcome } from './types/funnel'

export interface ActionMeta {
  label: string
  icon: string
  chipFg: string
  chipBg: string
  accent: string
}

export const ACTION_META: Record<string, ActionMeta> = {
  context: { label: 'add context', icon: 'Sparkles', chipFg: '#06303f', chipBg: '#71d2ff', accent: '#71d2ff' },
  drop: { label: 'auto-drop', icon: 'Filter', chipFg: '#ffb4ab', chipBg: 'color-mix(in srgb, #93000a 32%, transparent)', accent: '#e5484d' },
  include: { label: 'auto-include', icon: 'CircleCheckBig', chipFg: '#0e0e11', chipBg: 'var(--success)', accent: 'var(--success)' },
  label: { label: 'label', icon: 'Tag', chipFg: '#0e0e11', chipBg: '#b79cf7', accent: '#9a7af0' },
  loopback: { label: 'loop back', icon: 'RotateCcw', chipFg: '#0e0e11', chipBg: '#ffb59a', accent: '#f5a623' },
}

export const STAGE_META: Record<StageOutcome, ActionMeta> = {
  ...ACTION_META,
  pass: { label: 'passed', icon: 'Minus', chipFg: 'var(--muted-foreground)', chipBg: 'var(--surface-high)', accent: 'var(--border)' },
  skip: { label: 'skipped', icon: 'Ban', chipFg: 'var(--muted-foreground)', chipBg: 'transparent', accent: 'var(--border)' },
} as Record<StageOutcome, ActionMeta>

export const SRC_ICON: Record<string, string> = {
  github: 'Github',
  email: 'Mail',
  calendar: 'Calendar',
  chat: 'MessageCircle',
  phabricator: 'GitPullRequestArrow',
}

export const SOURCE_COLORS: Record<string, string> = {
  github: '#f5a623',
  email: '#71d2ff',
  calendar: '#ffb59a',
  chat: '#9ad08a',
}

export const OUTPUT_COLORS: Record<string, string> = {
  action_items: '#b79cf7',
  triage_queue: '#9a7af0',
  filtered_out: '#71717a',
  errors: '#e5484d',
}
