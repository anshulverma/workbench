import { describe, expect, it } from 'vitest'
import type { PipelineGraph } from '../types/pipeline'
import { laneKeyForType, layout } from './layout'
import { defaultGraph } from './graphs'

describe('layout', () => {
  it('centers a single-node column vertically', () => {
    // The source lane holds exactly one node, so it must land on the board's
    // vertical midline.
    const result = layout(defaultGraph)
    const source = result.nodes.find((n) => n.type === 'source')!
    expect(source.ui_y).toBe(Math.round(result.height / 2))
  })

  it('assigns deterministic columns from lane structure', () => {
    const result = layout(defaultGraph)
    const x = (id: number) => result.nodes.find((n) => n.id === id)!.ui_x
    // source < extraction < llm filter < sinks, strictly left-to-right
    expect(x(1)).toBeLessThan(x(2))
    expect(x(2)).toBeLessThan(x(3))
    expect(x(3)).toBeLessThan(x(4))
  })

  it('keeps a pinned node at its stored coordinates', () => {
    const pinned: PipelineGraph = {
      ...defaultGraph,
      nodes: defaultGraph.nodes.map((n) =>
        n.id === 3 ? { ...n, pinned: true, ui_x: 999, ui_y: 17 } : n,
      ),
    }
    const node = layout(pinned).nodes.find((n) => n.id === 3)!
    expect(node.ui_x).toBe(999)
    expect(node.ui_y).toBe(17)
  })

  it('emits the five phase lanes in order', () => {
    const result = layout(defaultGraph)
    expect(result.lanes.map((l) => l.key)).toEqual([
      'source',
      'pre',
      'extract',
      'post',
      'sinks',
    ])
  })

  it('maps node types to lane keys for drag snapping', () => {
    expect(laneKeyForType('source')).toBe('source')
    expect(laneKeyForType('pre_filter')).toBe('pre')
    expect(laneKeyForType('extraction')).toBe('extract')
    expect(laneKeyForType('sink')).toBe('sinks')
    expect(laneKeyForType('enricher')).toBe('post')
  })
})
