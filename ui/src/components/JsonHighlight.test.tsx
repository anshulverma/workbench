// JsonHighlight unit tests (spec §12).
//
// JsonHighlight is a PURE function: given a JSON string it tokenizes into React
// <span>s (keys/strings/numbers/booleans/null/punctuation) with token classes,
// NEVER dangerouslySetInnerHTML. Valid JSON tokenizes; invalid/huge JSON
// degrades gracefully to a single plain-text node.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { JsonHighlight } from './JsonHighlight'

describe('JsonHighlight', () => {
  it('tokenizes keys/strings/numbers into spans (no dangerouslySetInnerHTML)', () => {
    const { container } = render(
      <JsonHighlight json={'{"name":"workbench","port":8421}'} />,
    )
    expect(screen.getByText(/"name"/)).toBeInTheDocument()
    expect(screen.getByText('8421')).toBeInTheDocument()
    // No raw HTML injection anywhere.
    expect(container.querySelector('[dangerouslySetInnerHTML]')).toBeNull()
    expect(container.innerHTML).not.toContain('<script')
    expect(container.querySelectorAll('span').length).toBeGreaterThan(1)
  })

  it('tags each token kind with a distinct class', () => {
    const { container } = render(
      <JsonHighlight
        json={'{"name":"wb","flag":true,"empty":null,"n":3.14}'}
      />,
    )
    expect(container.querySelector('.tok-key')).not.toBeNull()
    expect(container.querySelector('.tok-string')).not.toBeNull()
    expect(container.querySelector('.tok-boolean')).not.toBeNull()
    expect(container.querySelector('.tok-null')).not.toBeNull()
    expect(container.querySelector('.tok-number')).not.toBeNull()
  })

  it('distinguishes string keys from string values', () => {
    const { container } = render(
      <JsonHighlight json={'{"k":"v"}'} />,
    )
    // The key "k" is a tok-key; the value "v" is a tok-string.
    const key = screen.getByText('"k"')
    const val = screen.getByText('"v"')
    expect(key.className).toContain('tok-key')
    expect(val.className).toContain('tok-string')
    expect(container.querySelectorAll('.tok-key').length).toBe(1)
  })

  it('does not inject HTML from string contents (XSS-safe)', () => {
    const { container } = render(
      <JsonHighlight json={'{"x":"<img src=x onerror=alert(1)>"}'} />,
    )
    // The angle brackets survive as text, not as a real <img> element.
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
  })

  it('degrades gracefully to plain text on invalid JSON', () => {
    const { container } = render(<JsonHighlight json={'{not valid json'} />)
    // No crash; the raw text is preserved.
    expect(container.textContent).toContain('{not valid json')
    // No token spans were produced for unparseable input.
    expect(container.querySelector('.tok-key')).toBeNull()
  })

  it('renders an empty string without crashing', () => {
    const { container } = render(<JsonHighlight json={''} />)
    expect(container).toBeTruthy()
  })
})
