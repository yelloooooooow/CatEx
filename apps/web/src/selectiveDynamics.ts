import type { ViewerPayload } from './types'

export type SelectiveDynamicsStrategy = 'none' | 'adsorbate_indices' | 'bottom_layers'

export interface ConstraintPreview {
  fixedIndices1Based: number[]
  mobileIndices1Based: number[]
  error: string | null
  layerCount: number
}

export function parseAtomIndices(text: string): number[] {
  const values = new Set<number>()
  for (const token of text.split(',').map((item) => item.trim()).filter(Boolean)) {
    const range = /^(\d+)-(\d+)$/.exec(token)
    if (range) {
      const start = Number(range[1])
      const end = Number(range[2])
      if (start < 1 || end < start || end - start > 20000) throw new Error(`Invalid atom range: ${token}`)
      for (let value = start; value <= end; value += 1) values.add(value)
    } else if (/^\d+$/.test(token) && Number(token) >= 1) values.add(Number(token))
    else throw new Error(`Invalid atom index: ${token}`)
  }
  return [...values].sort((left, right) => left - right)
}

export function formatAtomIndices(indices: number[]): string {
  return [...new Set(indices)].sort((left, right) => left - right).join(',')
}

export function toggleAtomIndex(text: string, index1Based: number): string {
  let indices: number[]
  try {
    indices = parseAtomIndices(text)
  } catch {
    indices = []
  }
  const values = new Set(indices)
  if (values.has(index1Based)) values.delete(index1Based)
  else values.add(index1Based)
  return formatAtomIndices([...values])
}

function allIndices(siteCount: number): number[] {
  return Array.from({ length: siteCount }, (_, index) => index + 1)
}

export function buildConstraintPreview(
  viewer: ViewerPayload | null,
  strategy: SelectiveDynamicsStrategy,
  mobileAtomText: string,
  bottomLayerCount: number,
  layerToleranceAngstrom: number,
): ConstraintPreview {
  const siteCount = viewer?.species.length ?? 0
  const all = allIndices(siteCount)
  if (!viewer || siteCount === 0) {
    return { fixedIndices1Based: [], mobileIndices1Based: [], error: 'Load a POSCAR structure first.', layerCount: 0 }
  }

  if (strategy === 'none') {
    return { fixedIndices1Based: [], mobileIndices1Based: all, error: null, layerCount: 0 }
  }

  if (strategy === 'adsorbate_indices') {
    let mobile: number[]
    try {
      mobile = parseAtomIndices(mobileAtomText)
    } catch (error) {
      return {
        fixedIndices1Based: [],
        mobileIndices1Based: [],
        error: error instanceof Error ? error.message : 'Invalid atom indices.',
        layerCount: 0,
      }
    }
    const mobileSet = new Set(mobile)
    const fixed = all.filter((index) => !mobileSet.has(index))
    if (mobile.length === 0) {
      return {
        fixedIndices1Based: all,
        mobileIndices1Based: [],
        error: 'Select at least one adsorbate atom.',
        layerCount: 0,
      }
    }
    if (mobile.some((index) => index > siteCount)) {
      return {
        fixedIndices1Based: fixed,
        mobileIndices1Based: mobile.filter((index) => index <= siteCount),
        error: `Atom indices must be between 1 and ${siteCount}.`,
        layerCount: 0,
      }
    }
    return { fixedIndices1Based: fixed, mobileIndices1Based: mobile, error: null, layerCount: 0 }
  }

  if (!Number.isFinite(layerToleranceAngstrom) || layerToleranceAngstrom < 0.01 || layerToleranceAngstrom > 5) {
    return {
      fixedIndices1Based: [],
      mobileIndices1Based: all,
      error: 'Layer tolerance must be between 0.01 and 5.0 angstrom.',
      layerCount: 0,
    }
  }

  const indexedZ = viewer.cartesian_coordinates
    .map((coordinates, index) => ({ index1Based: index + 1, z: coordinates[2] }))
    .sort((left, right) => left.z - right.z)
  const layers: number[][] = []
  let layerReference: number | null = null
  for (const atom of indexedZ) {
    if (layerReference === null || atom.z - layerReference > layerToleranceAngstrom) {
      layers.push([atom.index1Based])
      layerReference = atom.z
    } else {
      layers[layers.length - 1].push(atom.index1Based)
    }
  }
  const safeLayerCount = Math.max(0, Math.trunc(bottomLayerCount))
  const fixedSet = new Set(layers.slice(0, safeLayerCount).flat())
  const fixed = all.filter((index) => fixedSet.has(index))
  const mobile = all.filter((index) => !fixedSet.has(index))
  const error = safeLayerCount < 1
    ? 'Fix at least one bottom layer.'
    : safeLayerCount >= layers.length
      ? 'The fixed-layer count must leave at least one mobile layer.'
      : null
  return { fixedIndices1Based: fixed, mobileIndices1Based: mobile, error, layerCount: layers.length }
}
