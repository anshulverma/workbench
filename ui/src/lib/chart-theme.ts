// Centralized, token-driven Recharts theme (ADR 0038, spec §5).
//
// Single source of truth for chart colors + Recharts defaults, replacing the
// per-page hardcoded `DONUT_COLORS` arrays that drifted from the theme tokens.
// Hex values mirror the two-orange palette (ADR 0033) and the contrast contract
// (ADR 0046): brand orange `#ff6a2b` is the chart primary, cyan `#71d2ff` the
// tertiary, plus AA-safe semantic hues for red/amber/blue/green series.

export const CHART_COLORS = {
  primary: '#ff6a2b',
  tertiary: '#71d2ff',
  red: '#ffb4ab',
  amber: '#ffb59a',
  blue: '#71d2ff',
  green: '#9ad08a',
} as const

// Ordered palette for multi-series charts (pies, stacked bars) so categorical
// series cycle through the harmonized hues instead of an ad-hoc array.
export const CHART_PALETTE = [
  CHART_COLORS.primary,
  CHART_COLORS.tertiary,
  CHART_COLORS.amber,
  CHART_COLORS.green,
  CHART_COLORS.red,
] as const

export const CHART_DEFAULTS = {
  // Hairline grid normalized to the border token (#26262C).
  grid: { stroke: '#26262C', strokeDasharray: '3 3' },
  // Axis lines/labels use the muted on-surface-variant outline color.
  axis: { stroke: '#a98a7f', fontSize: 12 },
  // Tooltip is a dark surface-container with a hairline border + mono body text
  // (contrast contract §13: never orange text on this elevated surface).
  tooltip: {
    background: '#1f1f22',
    border: '1px solid #26262C',
    color: '#e4e1e6',
    borderRadius: 6,
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
  },
  legend: { color: '#e4e1e6', fontSize: 12 },
} as const

// Recharts <Tooltip contentStyle> convenience object derived from CHART_DEFAULTS.
export const TOOLTIP_CONTENT_STYLE = {
  backgroundColor: CHART_DEFAULTS.tooltip.background,
  border: CHART_DEFAULTS.tooltip.border,
  borderRadius: CHART_DEFAULTS.tooltip.borderRadius,
  color: CHART_DEFAULTS.tooltip.color,
  fontFamily: CHART_DEFAULTS.tooltip.fontFamily,
  fontSize: CHART_DEFAULTS.tooltip.fontSize,
} as const
