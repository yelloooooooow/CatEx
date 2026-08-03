import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api'
import { I18nProvider } from '../i18n'
import type { ExperimentalModelingCapabilities } from '../types'
import {
  detectExperimentalEvidenceKind,
  ExperimentalModelingWorkbench,
  reconcileAutoInterpretedElements,
} from './ExperimentalModelingWorkbench'

const mocks = vi.hoisted(() => ({
  saveCredential: vi.fn(),
  experimentalRuns: vi.fn(),
  experimentalRun: vi.fn(),
  experimentalReviews: vi.fn(),
  extractEvidence: vi.fn(),
  saveSpec: vi.fn(),
}))

vi.mock('./StructureViewer', () => ({
  StructureViewer: ({
    structure,
  }: {
    structure?: {
      species: string[]
      fractional_coordinates: number[][]
      lattice: number[][]
    } | null
  }) => (
    <div>
      <button type="button">Mock structure viewer</button>
      {structure && <>
        <strong>#2 · {structure.species[1]}</strong>
        <span>Fractional [{structure.fractional_coordinates[1].map((value) => value.toFixed(4)).join(', ')}]</span>
        <span>a 3.000 · b 3.000 · c 4.000 Å</span>
        <button type="button">Show indices</button>
      </>}
    </div>
  ),
}))

const capabilities: ExperimentalModelingCapabilities = {
  schema_version: 'catex.experimental-modeling-capabilities.v2',
  enabled: true,
  max_evidence_upload_bytes: 20 * 1024 * 1024,
  rule_planner: { available: true, external_api: false },
  providers: {
    project: { available: true, requires_key: false },
    optimade: { available: true, requires_key: false },
    materials_project: {
      available: false,
      client_installed: true,
      key_configured: false,
      credential_source: null,
      saved_to_system: false,
      requires_key: true,
      api_key_environment_variable: 'MP_API_KEY',
    },
  },
  gpt_planner: {
    available: false,
    key_configured: false,
    credential_source: null,
    saved_to_system: false,
    api_key_environment_variable: 'OPENAI_API_KEY',
    model: 'test-model',
    responses_api: true,
    stores_responses: false,
  },
  credential_store: {
    available: true,
    persistent: true,
    backend: 'keyring.backends.Windows.WinVaultKeyring',
    reason: null,
  },
  credentials_persisted: true,
}

vi.mock('../api', () => {
  class MockApiError extends Error {
    readonly status: number

    constructor(message: string, status: number) {
      super(message)
      this.status = status
    }
  }

  return {
    ApiError: MockApiError,
    api: {
      experimentalModelingCapabilities: vi.fn(async () => capabilities),
      experimentalEvidence: vi.fn(async () => []),
      experimentalSpec: vi.fn(async () => null),
      experimentalCatalogs: vi.fn(async () => []),
      experimentalRuns: mocks.experimentalRuns,
      experimentalRun: mocks.experimentalRun,
      experimentalReviews: mocks.experimentalReviews,
      saveExperimentalCredential: mocks.saveCredential,
      extractExperimentalEvidence: mocks.extractEvidence,
      saveExperimentalSpec: mocks.saveSpec,
      addExperimentalEvidence: vi.fn(),
    },
  }
})

describe('experimental credential editor', () => {
  afterEach(() => cleanup())

  beforeEach(() => {
    window.localStorage.clear()
    window.localStorage.setItem('catex.language.v1', 'en')
    mocks.saveCredential.mockReset()
    mocks.experimentalRuns.mockReset()
    mocks.experimentalRuns.mockResolvedValue([])
    mocks.experimentalRun.mockReset()
    mocks.experimentalReviews.mockReset()
    mocks.experimentalReviews.mockResolvedValue([])
    mocks.saveCredential.mockResolvedValue({
      schema_version: 'catex.credential-save.v1',
      provider: 'materials_project',
      saved_to_system: true,
      verified: true,
      verification: { database_version: '2026.07.31' },
      capabilities: {
        ...capabilities,
        providers: {
          ...capabilities.providers,
          materials_project: {
            ...capabilities.providers.materials_project,
            available: true,
            key_configured: true,
            credential_source: 'system_keyring',
            saved_to_system: true,
          },
        },
      },
    })
    mocks.extractEvidence.mockReset()
    mocks.extractEvidence.mockResolvedValue({
      schema_version: 'catex.experimental-evidence-extraction.v1',
      evidence_id: 'xrd-test',
      metadata: {},
      composition_constraints: [],
      local_environment_constraints: [],
      lattice_spacing_constraints: [],
      suggested_elements: [],
      notices: [],
    })
    mocks.saveSpec.mockReset()
    mocks.saveSpec.mockResolvedValue({ spec_revision_id: 'spec-test' })
  })

  it('uses a password field, clears it on submit, and never writes browser storage', async () => {
    render(
      <I18nProvider>
        <ExperimentalModelingWorkbench
          artifacts={[]}
          onArtifactsChanged={vi.fn()}
          onMessage={vi.fn()}
          onOpenStructures={vi.fn()}
          projectId="project-1"
        />
      </I18nProvider>,
    )

    const input = await screen.findByLabelText('Materials Project API key')
    expect(input).toHaveAttribute('type', 'password')
    expect(input).toHaveAttribute('autocomplete', 'new-password')

    fireEvent.change(input, { target: { value: 'browser-memory-test-key' } })
    fireEvent.click(
      screen.getAllByRole('button', { name: 'Verify and save securely' })[0],
    )

    await waitFor(() =>
      expect(mocks.saveCredential).toHaveBeenCalledWith(
        'materials_project',
        'browser-memory-test-key',
      ),
    )
    expect(input).toHaveValue('')
    expect(JSON.stringify(window.localStorage)).not.toContain('browser-memory-test-key')
  })

  it('starts chemistry-neutral and does not expose a sample-stage selector', async () => {
    render(
      <I18nProvider>
        <ExperimentalModelingWorkbench
          artifacts={[]}
          onArtifactsChanged={vi.fn()}
          onMessage={vi.fn()}
          onOpenStructures={vi.fn()}
          projectId="project-1"
        />
      </I18nProvider>,
    )

    expect((await screen.findAllByText('Characterization')).length).toBeGreaterThan(0)
    expect(screen.getByLabelText('Main elements')).toHaveValue('')
    expect(screen.queryByText('Sample stage')).not.toBeInTheDocument()
  })

  it('detects common researcher conclusions without requiring a method field', () => {
    expect(detectExperimentalEvidenceKind('所有衍射峰均归属于Ni4Mo物相。')).toBe('xrd')
    expect(detectExperimentalEvidenceKind('ICP-OES: Ni 62±2 at.%, Mo 38±2 at.%')).toBe('icp')
    expect(detectExperimentalEvidenceKind('XPS拟合显示Mo–O组分占60%。')).toBe('xps')
    expect(detectExperimentalEvidenceKind('HRTEM晶面间距d=0.208 nm。')).toBe('tem')
  })

  it('removes stale elements from a replaced automatic interpretation', () => {
    expect(reconcileAutoInterpretedElements(
      ['Ni', 'Mo', 'F', 'H', 'P'],
      ['F', 'H', 'P'],
      [],
      ['Ni', 'Mo'],
    )).toEqual(['Ni', 'Mo'])
    expect(reconcileAutoInterpretedElements(
      ['Ni', 'Mo', 'O'],
      ['Mo', 'O'],
      ['Mo'],
      ['Ni', 'O'],
    )).toEqual(['Ni', 'Mo', 'O'])
  })

  it('shows qualitative phase extraction as a usable interpretation', async () => {
    const onMessage = vi.fn()
    mocks.extractEvidence.mockImplementation(async (_projectId, payload) => ({
      schema_version: 'catex.evidence-extraction.v1',
      metadata: {
        brief_conclusion: payload.conclusion,
        reported_phase_formulas: ['Ni4Mo'],
      },
      composition_constraints: [],
      local_environment_constraints: [],
      lattice_spacing_constraints: [],
      suggested_elements: ['Mo', 'Ni'],
      notices: [],
      automatic: true,
      review_required: true,
    }))
    render(
      <I18nProvider>
        <ExperimentalModelingWorkbench
          artifacts={[]}
          onArtifactsChanged={vi.fn()}
          onMessage={onMessage}
          onOpenStructures={vi.fn()}
          projectId="project-1"
        />
      </I18nProvider>,
    )

    fireEvent.change(await screen.findByLabelText('Conclusion or result summary'), {
      target: { value: '所有衍射峰均归属于Ni4Mo物相。' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Interpret and add' }))

    await waitFor(() => expect(mocks.extractEvidence).toHaveBeenCalledWith(
      'project-1',
      expect.objectContaining({ kind: 'xrd' }),
    ))
    expect(await screen.findByText(/Phase Ni4Mo · prioritizes parent matching/)).toBeInTheDocument()
    expect(screen.getByText(/Elements Mo, Ni/)).toBeInTheDocument()
    expect(onMessage).toHaveBeenCalledWith('success', expect.stringContaining('prioritize'))
  })

  it('keeps bulk and surface composition ranges for the same element', async () => {
    render(
      <I18nProvider>
        <ExperimentalModelingWorkbench
          artifacts={[]}
          onArtifactsChanged={vi.fn()}
          onMessage={vi.fn()}
          onOpenStructures={vi.fn()}
          projectId="project-1"
        />
      </I18nProvider>,
    )

    await screen.findAllByLabelText('Spatial scope')
    const scope = screen.getAllByLabelText('Spatial scope')[0]
    const addRange = screen.getAllByRole('button', { name: 'Add composition' }).at(-1)
    expect(scope).toBeDefined()
    expect(addRange).toBeDefined()
    fireEvent.change(screen.getByLabelText('Element'), { target: { value: 'Ni' } })
    fireEvent.change(screen.getAllByLabelText('Minimum (%)')[0], { target: { value: '45' } })
    fireEvent.change(screen.getAllByLabelText('Maximum (%)')[0], { target: { value: '75' } })
    fireEvent.click(addRange!)
    fireEvent.change(scope!, {
      target: { value: 'surface' },
    })
    fireEvent.click(addRange!)

    expect(screen.getByText(/Ni · 45\.0–75\.0% · Bulk \(ICP\)/)).toBeInTheDocument()
    expect(screen.getByText(/Ni · 45\.0–75\.0% · Surface \(XPS\)/)).toBeInTheDocument()
  })

  it('saves entered evidence when an older backend returns method not allowed', async () => {
    const onMessage = vi.fn()
    mocks.extractEvidence.mockRejectedValue(new ApiError('Method Not Allowed', 405))
    render(
      <I18nProvider>
        <ExperimentalModelingWorkbench
          artifacts={[]}
          onArtifactsChanged={vi.fn()}
          onMessage={onMessage}
          onOpenStructures={vi.fn()}
          projectId="project-1"
        />
      </I18nProvider>,
    )

    fireEvent.change(await screen.findByLabelText('Conclusion or result summary'), {
      target: { value: 'All peaks belong to Ni4Mo.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Interpret and add' }))

    await waitFor(() => expect(mocks.saveSpec).toHaveBeenCalled())
    expect(onMessage).toHaveBeenCalledWith(
      'warning',
      expect.stringContaining('restart CatEx'),
    )
  })

  it('shows read-only candidate structure and clicked atom details', async () => {
    mocks.experimentalRuns.mockResolvedValue([{
      run_id: 'model-run-test',
      report_sha256: 'a'.repeat(64),
      planner_kind: 'rule',
      representative_count: 1,
      candidate_count: 1,
      status: 'supported',
    }])
    mocks.experimentalRun.mockResolvedValue({
      run_id: 'model-run-test',
      materialized: false,
      xrd_plot: null,
      report: {
        representative_candidate_ids: ['candidate-1'],
        claim_interpretation: 'Representative hypothesis, not a unique structure.',
        claim_ceiling: 'representative_structure_family',
        status: 'supported',
        phase_search: null,
        ambiguity_reasons: [],
        recommended_next_experiments: [],
        identity_sha256: 'a'.repeat(64),
      },
      candidates: [{
        candidate_id: 'candidate-1',
        assessment: {
          formula: 'NiMo',
          model_kind: 'bulk',
          num_sites: 2,
          modality_support: [],
          parent_support: 0.9,
          surface_support: null,
          local_support: null,
          parent_reference_key: 'project:ni-mo',
          structure_sha256: 'b'.repeat(64),
          valid: true,
        },
        viewer: {
          schema_version: 'catex.viewer.v1',
          lattice: [[3, 0, 0], [0, 3, 0], [0, 0, 4]],
          species: ['Ni', 'Mo'],
          fractional_coordinates: [[0, 0, 0], [0.5, 0.5, 0.5]],
          cartesian_coordinates: [[0, 0, 0], [1.5, 1.5, 2]],
          periodic: [true, true, true],
        },
      }],
    })

    render(
      <I18nProvider>
        <ExperimentalModelingWorkbench
          artifacts={[]}
          onArtifactsChanged={vi.fn()}
          onMessage={vi.fn()}
          onOpenStructures={vi.fn()}
          projectId="project-1"
        />
      </I18nProvider>,
    )

    fireEvent.click(await screen.findByRole('button', { name: 'Mock structure viewer' }))
    expect(screen.getByText('#2 · Mo')).toBeInTheDocument()
    expect(screen.getByText('Fractional [0.5000, 0.5000, 0.5000]')).toBeInTheDocument()
    expect(screen.getByText('a 3.000 · b 3.000 · c 4.000 Å')).toBeInTheDocument()

    expect(screen.getByRole('button', { name: 'Show indices' })).toBeInTheDocument()
  })
})
