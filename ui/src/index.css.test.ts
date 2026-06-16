import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// Resolve from the Vitest working dir (the `ui/` package root) rather than
// import.meta.url: under the jsdom environment import.meta.url is not a file://
// URL, so fileURLToPath throws.
const root = process.cwd()
const css = readFileSync(resolve(root, 'src/index.css'), 'utf8')
const html = readFileSync(resolve(root, 'index.html'), 'utf8')
const mainTsx = readFileSync(resolve(root, 'src/main.tsx'), 'utf8')

describe('theme tokens (spec §1, contrast contract §13)', () => {
  it('authors tokens as raw hex, not oklch', () => {
    expect(css).not.toMatch(/oklch\(/)
  })

  it('defines the dark surface ladder hexes', () => {
    for (const hex of ['#0e0e11', '#131316', '#1b1b1e', '#1f1f22', '#2a2a2d', '#353438']) {
      expect(css.toLowerCase()).toContain(hex)
    }
  })

  it('maps the two-orange system to shadcn vars', () => {
    expect(css).toMatch(/--primary:\s*#f5a623/i)
    expect(css).toMatch(/--primary-foreground:\s*#0e0e11/i)
    expect(css).toMatch(/--ring:\s*#f5a623/i)
    // neutral hover, NOT orange
    expect(css).toMatch(/--accent:\s*#2a2a2d/i)
  })

  it('normalizes the hairline border to #26262C', () => {
    expect(css.toLowerCase()).toContain('--border: #26262c')
  })

  it('exposes extra surface + brand tokens via @theme inline', () => {
    expect(css).toMatch(/--color-surface-lowest:/)
    expect(css).toMatch(/--color-surface-low:/)
    expect(css).toMatch(/--color-surface-container:/)
    expect(css).toMatch(/--color-surface-high:/)
    expect(css).toMatch(/--color-surface-highest:/)
    expect(css).toMatch(/--brand:/)
    expect(css).toMatch(/--brand-fg:/)
  })

  it('sets the redesign radius to 0.375rem', () => {
    expect(css).toMatch(/--radius:\s*0\.375rem/)
  })

  it('keeps both a dark default palette and a :root light palette', () => {
    expect(css).toMatch(/:root\s*\{/)
    expect(css).toMatch(/\.dark\s*\{/)
  })

  it('keeps the .prio-P0..P3 priority classes', () => {
    for (const cls of ['.prio-P0', '.prio-P1', '.prio-P2', '.prio-P3']) {
      expect(css).toContain(cls)
    }
  })

  it('preserves the focus-visible outline contract (orange ring)', () => {
    expect(css).toMatch(/:focus-visible\b/)
    expect(css).toMatch(/outline:\s*2px solid var\(--ring\)/)
  })

  it('self-hosts fonts via @fontsource (no Google CDN)', () => {
    expect(css).toContain('@import "@fontsource-variable/space-grotesk"')
    expect(css).toContain('@import "@fontsource-variable/hanken-grotesk"')
    expect(css).toContain('@import "@fontsource-variable/jetbrains-mono"')
    expect(css).not.toMatch(/fonts\.googleapis\.com/)
    expect(css).not.toMatch(/fonts\.gstatic\.com/)
  })

  it('defines the font + type-scale tokens', () => {
    expect(css).toMatch(/--font-sans:\s*"Hanken Grotesk Variable"/)
    expect(css).toMatch(/--font-display:\s*"Space Grotesk Variable"/)
    expect(css).toMatch(/--font-mono:\s*"JetBrains Mono Variable"/)
    expect(css).toMatch(/--text-display-lg:\s*32px/)
    expect(css).toMatch(/--text-display-sm:\s*24px/)
    expect(css).toMatch(/--text-title-md:\s*18px/)
    expect(css).toMatch(/--text-body-md:\s*14px/)
    expect(css).toMatch(/--text-body-sm:\s*13px/)
    expect(css).toMatch(/--text-mono-label:\s*12px/)
    expect(css).toMatch(/--text-mono-data:\s*13px/)
  })

  it('sets base font-family on body and display on headings', () => {
    expect(css).toMatch(/body\s*\{[^}]*font-family:\s*var\(--font-sans\)/s)
    expect(css).toMatch(/h1,\s*h2,\s*h3\s*\{[^}]*font-family:\s*var\(--font-display\)/s)
  })

  it('removes the hardcoded dark class from index.html', () => {
    expect(html).not.toMatch(/<html[^>]*class="dark"/)
  })

  it('mounts the next-themes ThemeProvider (class attr, dark default)', () => {
    expect(mainTsx).toMatch(/from ['"]next-themes['"]/)
    expect(mainTsx).toMatch(/<ThemeProvider/)
    expect(mainTsx).toMatch(/attribute=["']class["']/)
    // Dark is the design baseline (the prototype ships <html class="dark">), so
    // the app defaults to dark rather than following the OS preference.
    expect(mainTsx).toMatch(/defaultTheme=["']dark["']/)
    expect(mainTsx).toMatch(/enableSystem/)
  })
})
