import { describe, expect, it } from 'vitest'

import type { NodeDefinition } from './types'
import {
  buildValidationRequest,
  compatibleHandles,
  createFlowNode,
  firstCompatiblePortPair,
  handleId,
  layoutWorkflow,
  localProjectDirectory,
  parseHandleId,
  wouldCreateWorkflowCycle,
} from './workflow'

describe('typed workflow handles', () => {
  it('accepts equal scientific port kinds', () => {
    const source = handleId('out', 'structure_record', 'record')
    const target = handleId('in', 'structure_record', 'record')

    expect(compatibleHandles(source, target)).toBe(true)
    expect(parseHandleId(source)).toEqual({
      direction: 'out',
      kind: 'structure_record',
      portId: 'record',
    })
  })

  it('rejects mismatched scientific port kinds and directions', () => {
    expect(
      compatibleHandles(
        handleId('out', 'structure_artifact', 'structure'),
        handleId('in', 'reviewed_structure', 'structure'),
      ),
    ).toBe(false)
    expect(
      compatibleHandles(
        handleId('in', 'structure_record', 'record'),
        handleId('in', 'structure_record', 'record'),
      ),
    ).toBe(false)
  })

  it('serializes edited node parameters into the validation contract', () => {
    const definition: NodeDefinition = {
      type_id: 'vasp.relax',
      title: 'Relax',
      description: 'Relax structure',
      category: 'calculation',
      inputs: [],
      outputs: [],
      parameters: [
        {
          key: 'nsw',
          label: 'NSW',
          kind: 'integer',
          default: 200,
          description: '',
          required: true,
          choices: [],
          minimum: 1,
          maximum: 2000,
        },
      ],
      review_gate: false,
    }
    const node = createFlowNode(definition, { x: 10, y: 20 }, 'relax-1')
    node.data.parameters.nsw = 350

    expect(buildValidationRequest([node], []).nodes[0]).toEqual({
      node_id: 'relax-1',
      type_id: 'vasp.relax',
      position: { x: 10, y: 20 },
      parameters: { nsw: 350 },
    })
  })
})

describe('workflow editor helpers', () => {
  const definition = (
    typeId: string,
    inputKind?: string,
    outputKind?: string,
  ): NodeDefinition => ({
    type_id: typeId,
    title: typeId,
    description: '',
    category: 'calculation',
    inputs: inputKind
      ? [{ port_id: 'input', label: 'Input', kind: inputKind, required: true, multiple: false }]
      : [],
    outputs: outputKind
      ? [{ port_id: 'state', label: 'State', kind: outputKind, required: true, multiple: false }]
      : [],
    parameters: [],
    review_gate: false,
  })

  it('finds the first scientifically compatible connection', () => {
    expect(
      firstCompatiblePortPair(
        definition('source', undefined, 'calculation_state'),
        definition('target', 'calculation_state', 'calculation_state'),
      ),
    ).toEqual({
      sourceHandle: handleId('out', 'calculation_state', 'state'),
      targetHandle: handleId('in', 'calculation_state', 'input'),
    })
  })

  it('lays a DAG out from left to right and keeps branches in one layer', () => {
    const source = createFlowNode(definition('source', undefined, 'state'), { x: 0, y: 0 }, 'source')
    const branchA = createFlowNode(definition('a', 'state', 'state'), { x: 0, y: 0 }, 'a')
    const branchB = createFlowNode(definition('b', 'state', 'state'), { x: 0, y: 0 }, 'b')
    const laidOut = layoutWorkflow(
      [source, branchA, branchB],
      [
        { id: 'source-a', source: 'source', target: 'a' },
        { id: 'source-b', source: 'source', target: 'b' },
      ],
    )
    const byId = new Map(laidOut.map((node) => [node.id, node]))

    expect(byId.get('a')?.position.x).toBeGreaterThan(byId.get('source')?.position.x ?? 0)
    expect(byId.get('a')?.position.x).toBe(byId.get('b')?.position.x)
    expect(byId.get('a')?.position.y).not.toBe(byId.get('b')?.position.y)
  })

  it('shows the exact per-project directory under the configured storage root', () => {
    expect(localProjectDirectory('E:\\CatEx data', 'project-abc123')).toBe(
      'E:\\CatEx data\\projects\\project-abc123',
    )
    expect(localProjectDirectory('/tmp/catex', 'project-abc123')).toBe(
      '/tmp/catex/projects/project-abc123',
    )
  })

  it('rejects a connection that would close a directed cycle', () => {
    const edges = [
      { id: 'a-b', source: 'a', target: 'b' },
      { id: 'b-c', source: 'b', target: 'c' },
    ]
    expect(wouldCreateWorkflowCycle(edges, 'c', 'a')).toBe(true)
    expect(wouldCreateWorkflowCycle(edges, 'a', 'c')).toBe(false)
  })
})
