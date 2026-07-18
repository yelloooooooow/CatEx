import { describe, expect, it } from 'vitest'

import { compatibleHandles, handleId, parseHandleId } from './workflow'

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
})
