import type { ReactElement, ReactNode } from 'react'

/**
 * JsonHighlight — a PURE function that tokenizes a JSON string into React
 * <span>s (spec §12). NO shiki/prismjs, NO `dangerouslySetInnerHTML`: every
 * token is a real React text node, so string contents (even `<img onerror>`)
 * are escaped by React and can never inject HTML.
 *
 * Token classes (re-themed from the design's low-contrast colors to AA-safe
 * tokens on the dark code surface):
 *   keys        -> .tok-key      (#ffb59a, --brand)
 *   strings     -> .tok-string   (#71d2ff, --tertiary)
 *   numbers     -> .tok-number   (on-surface foreground)
 *   booleans    -> .tok-boolean  (on-surface foreground)
 *   null        -> .tok-null     (muted foreground)
 *   punctuation -> .tok-punct    (muted foreground)
 *
 * Invalid/unparseable JSON degrades gracefully to a single plain-text node.
 */

// One regex pass over pretty-printed JSON. Order matters: a quoted token
// followed by optional whitespace + `:` is a key; any other quoted token is a
// string value. Numbers, booleans, null, and punctuation follow.
const TOKEN_RE =
  /("(?:\\.|[^"\\])*")(\s*:)|("(?:\\.|[^"\\])*")|(\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|(\btrue\b|\bfalse\b)|(\bnull\b)|([{}[\],:])/g

function Tok({
  cls,
  children,
}: {
  cls: string
  children: ReactNode
}): ReactElement {
  return <span className={cls}>{children}</span>
}

export function JsonHighlight({ json }: { json: string }): ReactElement {
  // Pretty-print if it parses; otherwise fall through to graceful plain text.
  let source = json
  let parsed = false
  try {
    source = JSON.stringify(JSON.parse(json), null, 2)
    parsed = true
  } catch {
    parsed = false
  }

  if (!parsed) {
    // Degrade gracefully: render the raw text, no tokenization.
    return (
      <pre className="whitespace-pre-wrap break-all font-mono text-xs text-foreground">
        {json}
      </pre>
    )
  }

  const nodes: ReactNode[] = []
  let last = 0
  let key = 0
  let m: RegExpExecArray | null
  TOKEN_RE.lastIndex = 0
  while ((m = TOKEN_RE.exec(source)) !== null) {
    if (m.index > last) {
      // Untokenized run (whitespace / newlines) — preserved verbatim.
      nodes.push(source.slice(last, m.index))
    }
    const [, keyName, colon, str, num, bool, nul, punct] = m
    if (keyName !== undefined) {
      nodes.push(
        <Tok key={key++} cls="tok-key">
          {keyName}
        </Tok>,
      )
      // The colon (with any inter-whitespace) is punctuation.
      nodes.push(
        <Tok key={key++} cls="tok-punct">
          {colon}
        </Tok>,
      )
    } else if (str !== undefined) {
      nodes.push(
        <Tok key={key++} cls="tok-string">
          {str}
        </Tok>,
      )
    } else if (num !== undefined) {
      nodes.push(
        <Tok key={key++} cls="tok-number">
          {num}
        </Tok>,
      )
    } else if (bool !== undefined) {
      nodes.push(
        <Tok key={key++} cls="tok-boolean">
          {bool}
        </Tok>,
      )
    } else if (nul !== undefined) {
      nodes.push(
        <Tok key={key++} cls="tok-null">
          {nul}
        </Tok>,
      )
    } else if (punct !== undefined) {
      nodes.push(
        <Tok key={key++} cls="tok-punct">
          {punct}
        </Tok>,
      )
    }
    last = TOKEN_RE.lastIndex
  }
  if (last < source.length) nodes.push(source.slice(last))

  return (
    <pre className="whitespace-pre-wrap break-all font-mono text-xs">
      {nodes}
    </pre>
  )
}
