import { describe, expect, it } from 'vitest'

import {
  canResumeExistingRun,
  formatSlurmWalltime,
  parseSlurmWalltimeMinutes,
  potcarDatasetOrder,
  potcarMetadataMatchesSpecies,
  poscarSpeciesOrder,
  selectActiveStructureArtifact,
  selectActionableDiagnostic,
  uniqueSpeciesOrder,
} from './inputReadiness'
import type { Diagnostic } from './types'

describe('input readiness helpers', () => {
  it('shows a blocking error before an earlier informational finding', () => {
    const diagnostics: Diagnostic[] = [
      { code: 'VACUUM_AXIS_CANDIDATE', severity: 'info', message: 'Vacuum detected.', context: {} },
      { code: 'POTCAR_ORDER_MISMATCH', severity: 'error', message: 'POTCAR order mismatch.', context: {} },
    ]
    expect(selectActionableDiagnostic(diagnostics)?.code).toBe('POTCAR_ORDER_MISMATCH')
  })

  it('preserves the first-occurrence POSCAR species order', () => {
    expect(uniqueSpeciesOrder(['C', 'C', 'N', 'Zn', 'Ni', 'Ni'])).toEqual(['C', 'N', 'Zn', 'Ni'])
  })

  it('reads the declared species order from the POSCAR header', () => {
    const poscar = [
      'C62N6ZnNi slab',
      '1.0',
      '10 0 0',
      '0 10 0',
      '0 0 15',
      'C N Zn Ni',
      '62 6 1 1',
      'Direct',
    ].join('\n')
    expect(poscarSpeciesOrder(poscar)).toEqual(['C', 'N', 'Zn', 'Ni'])
  })

  it('requires exact POTCAR dataset order compatibility', () => {
    const metadata = { datasets: [{ element: 'C' }, { element: 'N' }, { element: 'Zn' }, { element: 'Ni' }] }
    expect(potcarDatasetOrder(metadata)).toEqual(['C', 'N', 'Zn', 'Ni'])
    expect(potcarMetadataMatchesSpecies(metadata, ['C', 'N', 'Zn', 'Ni'])).toBe(true)
    expect(potcarMetadataMatchesSpecies(metadata, ['C', 'N', 'Ni', 'Zn'])).toBe(false)
    expect(potcarMetadataMatchesSpecies({ datasets: [{ element: 'Na' }, { element: 'Cl' }] }, ['C', 'N', 'Zn', 'Ni'])).toBe(false)
  })

  it('keeps the explicitly selected structure even when an unrelated artifact was created later', () => {
    const artifacts = [
      { artifact_id: 'newer', artifact_type: 'structure', created_at_utc: '2026-07-18T16:00:00Z' },
      { artifact_id: 'selected', artifact_type: 'structure', created_at_utc: '2026-07-18T01:00:00Z' },
    ]
    expect(selectActiveStructureArtifact(artifacts, 'selected')?.artifact_id).toBe('selected')
    expect(selectActiveStructureArtifact(artifacts, '')?.artifact_id).toBe('newer')
  })

  it('parses and formats Slurm walltime without hiding the seven-day policy', () => {
    expect(parseSlurmWalltimeMinutes('7-00:00:00')).toBe(10080)
    expect(parseSlurmWalltimeMinutes('00:10:01')).toBe(11)
    expect(parseSlurmWalltimeMinutes('7 days')).toBeNull()
    expect(formatSlurmWalltime(10080)).toBe('7-00:00:00')
    expect(formatSlurmWalltime(10)).toBe('00:10:00')
  })

  it('resumes only an identical materialized run when directory existence is the sole blocker', () => {
    const plan = {
      plan_sha256: 'same-plan',
      diagnostics: [{
        code: 'MATERIALIZATION_DESTINATION_EXISTS',
        severity: 'error' as const,
        message: 'already exists',
        context: {},
      }],
    }
    const run = { plan_sha256: 'same-plan', local_materialized: true }
    expect(canResumeExistingRun(plan, run)).toBe(true)
    expect(canResumeExistingRun(plan, { ...run, plan_sha256: 'other-plan' })).toBe(false)
    expect(canResumeExistingRun(plan, { ...run, local_materialized: false })).toBe(false)
    expect(canResumeExistingRun({
      ...plan,
      diagnostics: [...plan.diagnostics, {
        code: 'SLURM_WALLTIME_LIMIT_EXCEEDED',
        severity: 'error' as const,
        message: 'walltime blocked',
        context: {},
      }],
    }, run)).toBe(false)
  })
})
