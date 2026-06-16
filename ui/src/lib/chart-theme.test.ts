import { describe, it, expect } from 'vitest'
import { CHART_COLORS, CHART_DEFAULTS } from './chart-theme'

describe('chart-theme', () => {
  it('exposes the token-driven palette', () => {
    expect(CHART_COLORS.primary).toBe('#f5a623')
    expect(CHART_COLORS.tertiary).toBe('#71d2ff')
    expect(CHART_COLORS).toMatchObject({
      red: '#ffb4ab',
      blue: '#71d2ff',
      green: '#9ad08a',
    })
  })

  it('provides recharts grid/axis defaults', () => {
    expect(CHART_DEFAULTS.grid.stroke).toBe('#26262C')
    expect(CHART_DEFAULTS.axis.stroke).toBeTruthy()
  })

  it('provides a dark mono tooltip surface', () => {
    expect(CHART_DEFAULTS.tooltip.background).toBe('#1f1f22')
    expect(CHART_DEFAULTS.tooltip.border).toContain('#26262C')
  })
})
