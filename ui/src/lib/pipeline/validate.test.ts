import { describe, expect, it } from 'vitest'
import type { PipelineGraph } from '../types/pipeline'
import { validate } from './validate'
import { editedGraph } from './graphs'

describe('validate', () => {
  it('passes the canonical edited graph clean', () => {
    const result = validate(editedGraph)
    expect(result.ok).toBe(true)
    expect(result.problems).toHaveLength(0)
    expect(result.errorNodes.size).toBe(0)
    expect(result.errorEdges.size).toBe(0)
  })

  it('flags a no-fallback problem on node 3 when its default edge (E15) is deleted', () => {
    // E15 (3 → Triage, always) is the only `always` fallback leaving the
    // relevance filter; without it, items matching no condition are lost.
    const broken: PipelineGraph = {
      ...editedGraph,
      edges: editedGraph.edges.filter((e) => e.id !== 15),
    }
    const result = validate(broken)
    expect(result.ok).toBe(false)
    const nofall = result.problems.find((p) => p.id === 'nofall-3')
    expect(nofall).toBeDefined()
    expect(nofall!.nodes).toContain(3)
    expect(result.errorNodes.has(3)).toBe(true)
    // every conditional edge leaving node 3 is ringed
    for (const e of broken.edges.filter((e) => e.from_node === 3)) {
      expect(result.errorEdges.has(e.id)).toBe(true)
    }
  })

  it('flags a field-segment problem for a pre_filter testing a post-extraction field', () => {
    // `relevance` is produced by extraction, so a pre-filter referencing it
    // cannot evaluate — validate() must surface a segment problem on the node.
    const graph: PipelineGraph = {
      nodes: [
        { id: 1, type: 'source', label: 'Source', source_scope: null, config: {}, enabled: true, ui_x: 0, ui_y: 0 },
        {
          id: 2,
          type: 'pre_filter',
          label: 'Bad pre-filter',
          source_scope: ['all'],
          config: { tree: { field: 'relevance', operator: 'gte', value: 70 } },
          enabled: true,
          ui_x: 0,
          ui_y: 0,
        },
        { id: 3, type: 'extraction', label: 'Extraction', source_scope: null, config: {}, enabled: true, ui_x: 0, ui_y: 0 },
        { id: 4, type: 'sink', role: 'triage', label: 'Triage', source_scope: null, config: {}, enabled: true, ui_x: 0, ui_y: 0 },
      ],
      edges: [
        { id: 1, from_node: 1, to_node: 2, predicate: { op: 'always' }, order_index: 1 },
        { id: 2, from_node: 2, to_node: 3, predicate: { op: 'always' }, order_index: 1 },
        { id: 3, from_node: 3, to_node: 4, predicate: { op: 'always' }, order_index: 1 },
      ],
    }
    const result = validate(graph)
    expect(result.ok).toBe(false)
    const seg = result.problems.find((p) => p.id === 'segn-2')
    expect(seg).toBeDefined()
    expect(seg!.msg).toContain('relevance')
    expect(result.errorNodes.has(2)).toBe(true)
  })
})
