import { describe, expect, it } from 'vitest'

import type { NodeDefinition } from './types'
import {
  buildValidationRequest,
  compatibleHandles,
  createFlowNode,
  handleId,
  parseHandleId,
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
