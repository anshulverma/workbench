import { describe, expect, it } from 'vitest'
import { ACTION_META, STAGE_META, SRC_ICON } from './funnel-constants'

describe('ACTION_META', () => {
  it('has all five action types', () => {
    expect(Object.keys(ACTION_META).sort()).toEqual(['context', 'drop', 'include', 'label', 'loopback'])
  })

  it('each entry has label, icon, chipFg, chipBg, accent', () => {
    for (const [, meta] of Object.entries(ACTION_META)) {
      expect(meta).toHaveProperty('label')
      expect(meta).toHaveProperty('icon')
      expect(meta).toHaveProperty('chipFg')
      expect(meta).toHaveProperty('chipBg')
      expect(meta).toHaveProperty('accent')
    }
  })

  it('has correct labels', () => {
    expect(ACTION_META.context.label).toBe('add context')
    expect(ACTION_META.drop.label).toBe('auto-drop')
    expect(ACTION_META.include.label).toBe('auto-include')
    expect(ACTION_META.label.label).toBe('label')
    expect(ACTION_META.loopback.label).toBe('loop back')
  })
})

describe('STAGE_META', () => {
  it('has all seven stage outcomes', () => {
    expect(Object.keys(STAGE_META).sort()).toEqual(
      ['context', 'drop', 'include', 'label', 'loopback', 'pass', 'skip'],
    )
  })

  it('pass and skip have correct labels', () => {
    expect(STAGE_META.pass.label).toBe('passed')
    expect(STAGE_META.skip.label).toBe('skipped')
  })
})

describe('SRC_ICON', () => {
  it('covers all known sources', () => {
    expect(SRC_ICON.github).toBe('Github')
    expect(SRC_ICON.email).toBe('Mail')
    expect(SRC_ICON.calendar).toBe('Calendar')
    expect(SRC_ICON.chat).toBe('MessageCircle')
    expect(SRC_ICON.phabricator).toBe('GitPullRequestArrow')
  })
})
