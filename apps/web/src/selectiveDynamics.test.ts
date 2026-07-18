import { describe, expect, it } from 'vitest'

import type { ViewerPayload } from './types'
import {
  buildConstraintPreview,
  formatAtomIndices,
  parseAtomIndices,
  toggleAtomIndex,
} from './selectiveDynamics'

const viewer: ViewerPayload = {
  schema_version: 'test',
  lattice: [[10, 0, 0], [0, 10, 0], [0, 0, 15]],
  species: ['C', 'C', 'O', 'H'],
  fractional_coordinates: [[0, 0, 0], [0, 0, 0.01], [0, 0, 0.2], [0, 0, 0.21]],
  cartesian_coordinates: [[0, 0, 0], [1, 0, 0.1], [0, 0, 3], [1, 0, 3.1]],
  periodic: [true, true, true],
}

describe('selective-dynamics preview', () => {
  it('parses POSCAR-style one-based atom ranges', () => {
    expect(parseAtomIndices('4, 1-2,2')).toEqual([1, 2, 4])
    expect(formatAtomIndices([4, 1, 4, 2])).toBe('1,2,4')
  })

  it('toggles an atom while preserving sorted one-based indices', () => {
    expect(toggleAtomIndex('1,4', 2)).toBe('1,2,4')
    expect(toggleAtomIndex('1,2,4', 2)).toBe('1,4')
  })

  it('previews fixed catalyst and mobile adsorbate atoms', () => {
    const preview = buildConstraintPreview(viewer, 'adsorbate_indices', '3-4', 1, 0.5)
    expect(preview.error).toBeNull()
    expect(preview.fixedIndices1Based).toEqual([1, 2])
    expect(preview.mobileIndices1Based).toEqual([3, 4])
  })

  it('uses the same bottom-layer grouping rule as the backend', () => {
    const preview = buildConstraintPreview(viewer, 'bottom_layers', '', 1, 0.5)
    expect(preview.layerCount).toBe(2)
    expect(preview.fixedIndices1Based).toEqual([1, 2])
    expect(preview.mobileIndices1Based).toEqual([3, 4])
  })

  it('blocks a layer choice that would fix every atom', () => {
    const preview = buildConstraintPreview(viewer, 'bottom_layers', '', 2, 0.5)
    expect(preview.error).toContain('leave at least one mobile layer')
    expect(preview.mobileIndices1Based).toEqual([])
  })
})
