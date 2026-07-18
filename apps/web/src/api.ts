import type {
  Capabilities,
  CalculationConfig,
  CalculationResult,
  CalculationPlanResponse,
  CifConversionResponse,
  EnergyDerivation,
  HpcObservation,
  HpcProfile,
  HarmonicThermochemistry,
  MaterializationResponse,
  NodeDefinition,
  ProjectArtifact,
  ProjectArtifactSource,
  ProjectRecord,
  ReferenceCaseSummary,
  ReactionAnalysis,
  ReactionTemplate,
  ReviewedEnergy,
  RemoteRunResult,
  RemotePotcarCopy,
  RemotePotcarMetadata,
  RunSummary,
  SavedWorkflowPayload,
  SelectiveDynamicsResponse,
  StructureInspectionResponse,
  StructureReview,
  TemplateResponse,
  VaspDemoResult,
  WorkflowValidation,
} from './types'
import type { WorkflowValidationRequest } from './workflow'

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  capabilities: () => requestJson<Capabilities>('/api/v1/capabilities'),
  registry: async () => {
    const payload = await requestJson<{ nodes: NodeDefinition[] }>('/api/v1/workflows/registry')
    return payload.nodes
  },
  defaultTemplate: () =>
    requestJson<TemplateResponse>('/api/v1/workflows/templates/default'),
  validateWorkflow: (payload: WorkflowValidationRequest) =>
    requestJson<WorkflowValidation>('/api/v1/workflows/validate', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  inspectStructure: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return requestJson<StructureInspectionResponse>('/api/v1/structures/inspect', {
      method: 'POST',
      body: form,
    })
  },
  convertCifToPoscar: (filename: string, content: string) =>
    requestJson<CifConversionResponse>('/api/v1/structures/cif-to-poscar', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ filename, content }),
    }),
  applySelectiveDynamics: (payload: {
    poscar_text: string
    strategy: 'none' | 'adsorbate_indices' | 'bottom_layers'
    mobile_indices_1based: number[]
    bottom_layer_count: number
    layer_tolerance_angstrom: number
  }) =>
    requestJson<SelectiveDynamicsResponse>('/api/v1/structures/selective-dynamics', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  projects: async () => {
    const payload = await requestJson<{ projects: ProjectRecord[] }>('/api/v1/projects')
    return payload.projects
  },
  createProject: (payload: {
    title: string
    purpose: ProjectRecord['purpose']
    description?: string
  }) =>
    requestJson<ProjectRecord>('/api/v1/projects', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  paper4ReferenceCase: () =>
    requestJson<ReferenceCaseSummary>('/api/v1/reference-cases/paper4'),
  createPaper4Project: () =>
    requestJson<ProjectRecord>('/api/v1/projects/from-reference/paper4', {
      method: 'POST',
    }),
  projectArtifacts: async (projectId: string) => {
    const payload = await requestJson<{ artifacts: ProjectArtifact[] }>(
      `/api/v1/projects/${projectId}/artifacts`,
    )
    return payload.artifacts
  },
  projectArtifactSource: (projectId: string, artifactId: string) =>
    requestJson<ProjectArtifactSource>(
      `/api/v1/projects/${projectId}/artifacts/${artifactId}/source`,
    ),
  addProjectStructure: (projectId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return requestJson<ProjectArtifact>(`/api/v1/projects/${projectId}/structures`, {
      method: 'POST',
      body: form,
    })
  },
  projectStructureReview: async (projectId: string, artifactId: string) => {
    const payload = await requestJson<{ review: StructureReview | null }>(
      `/api/v1/projects/${projectId}/structure-reviews/${artifactId}`,
    )
    return payload.review
  },
  reviewProjectStructure: (
    projectId: string,
    artifactId: string,
    reviewer: string,
    note: string,
  ) =>
    requestJson<StructureReview>(`/api/v1/projects/${projectId}/structure-reviews`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        artifact_id: artifactId,
        approved: true,
        reviewer,
        note,
      }),
    }),
  projectWorkflow: async (projectId: string) => {
    const payload = await requestJson<{ workflow: SavedWorkflowPayload | null }>(
      `/api/v1/projects/${projectId}/workflow`,
    )
    return payload.workflow
  },
  saveProjectWorkflow: (projectId: string, payload: WorkflowValidationRequest) =>
    requestJson<{ workflow: SavedWorkflowPayload; validation: WorkflowValidation }>(
      `/api/v1/projects/${projectId}/workflow`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
  projectExportUrl: (projectId: string) => `/api/v1/projects/${projectId}/export`,
  defaultCalculationConfig: () =>
    requestJson<CalculationConfig>('/api/v1/calculation-config/default'),
  projectCalculationConfig: async (projectId: string) => {
    const payload = await requestJson<{ bundle: CalculationConfig | null }>(
      `/api/v1/projects/${projectId}/calculation-config`,
    )
    return payload.bundle
  },
  saveCalculationConfig: (projectId: string, payload: CalculationConfig) =>
    requestJson<{ bundle: CalculationConfig; revision_sha256: string; saved: boolean }>(
      `/api/v1/projects/${projectId}/calculation-config`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
  planCalculation: (projectId: string, artifactId: string) =>
    requestJson<CalculationPlanResponse>(`/api/v1/projects/${projectId}/calculation-plan`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ artifact_id: artifactId }),
    }),
  approveProtocol: (projectId: string, artifactId: string, reviewer: string, note: string) =>
    requestJson<{ approved: true; resolved_protocol_sha256: string }>(
      `/api/v1/projects/${projectId}/protocol-review`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ artifact_id: artifactId, reviewer, note }),
      },
    ),
  materializeCalculation: (
    projectId: string,
    artifactId: string,
    planSha256: string,
    approvedWrite: boolean,
  ) =>
    requestJson<MaterializationResponse>(`/api/v1/projects/${projectId}/materializations`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        artifact_id: artifactId,
        confirm_plan_sha256: planSha256,
        approved_write: approvedWrite,
      }),
    }),
  projectRuns: async (projectId: string) => {
    const payload = await requestJson<{ runs: RunSummary[] }>(
      `/api/v1/projects/${projectId}/runs`,
    )
    return payload.runs
  },
  calculationResults: async (projectId: string) => {
    const payload = await requestJson<{ results: CalculationResult[] }>(
      `/api/v1/projects/${projectId}/calculation-results`,
    )
    return payload.results
  },
  probeHpc: (profile: HpcProfile) =>
    requestJson<{ connected: boolean; credentials_retained: false }>('/api/v1/hpc/probe', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ profile }),
    }),
  remotePotcarMetadata: (profile: HpcProfile, labels: string[]) =>
    requestJson<RemotePotcarMetadata>('/api/v1/hpc/potcar-metadata', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ profile, labels }),
    }),
  stageRemoteRun: (
    projectId: string,
    profile: HpcProfile,
    runId: string,
    planSha256: string,
    approvedRemoteWrite: boolean,
  ) =>
    requestJson<{ run_id: string; potcar_materialized_on_hpc: true }>(
      `/api/v1/projects/${projectId}/remote-stage`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          profile,
          run_id: runId,
          confirm_plan_sha256: planSha256,
          approved_remote_write: approvedRemoteWrite,
        }),
      },
    ),
  submitRemoteRun: (
    projectId: string,
    profile: HpcProfile,
    runId: string,
    planSha256: string,
    approvedSubmit: boolean,
  ) =>
    requestJson<{ job_id: string }>(`/api/v1/projects/${projectId}/remote-submit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        profile,
        run_id: runId,
        confirm_plan_sha256: planSha256,
        approved_submit: approvedSubmit,
      }),
    }),
  copyRemotePotcar: (projectId: string, profile: HpcProfile, runId: string) =>
    requestJson<RemotePotcarCopy>(`/api/v1/projects/${projectId}/remote-potcar`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ profile, run_id: runId, approved_local_write: true }),
    }),
  observeRemoteRun: (projectId: string, profile: HpcProfile, runId: string) =>
    requestJson<HpcObservation>(`/api/v1/projects/${projectId}/remote-observe`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ profile, run_id: runId }),
    }),
  pullRemoteResults: (
    projectId: string,
    profile: HpcProfile,
    runId: string,
    approvedLocalWrite: boolean,
  ) =>
    requestJson<RemoteRunResult>(`/api/v1/projects/${projectId}/remote-results`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        profile,
        run_id: runId,
        approved_local_write: approvedLocalWrite,
      }),
    }),
  reviewResult: (
    projectId: string,
    runId: string,
    accepted: boolean,
    reviewer: string,
    note: string,
    energyKind = 'sigma_zero',
  ) =>
    requestJson<{ decision: 'accepted' | 'rejected'; review_sha256: string }>(
      `/api/v1/projects/${projectId}/result-reviews`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          run_id: runId,
          accepted,
          reviewer,
          note,
          energy_kind: energyKind,
        }),
      },
    ),
  reviewedEnergies: async (projectId: string) => {
    const payload = await requestJson<{ energies: ReviewedEnergy[] }>(
      `/api/v1/projects/${projectId}/reviewed-energies`,
    )
    return payload.energies
  },
  deriveEnergy: (
    projectId: string,
    derivationId: string,
    coefficients: Record<string, number>,
    approvedWrite: boolean,
  ) =>
    requestJson<EnergyDerivation>(`/api/v1/projects/${projectId}/energy-derivations`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        derivation_id: derivationId,
        coefficients,
        approved_write: approvedWrite,
      }),
    }),
  harmonicThermochemistry: (
    modes: Array<{ wavenumber_cm1: number; energy_mev: number; imaginary: boolean }>,
    temperatureKelvin: number,
    cutoffCm1: number,
  ) =>
    requestJson<HarmonicThermochemistry>('/api/v1/thermochemistry/harmonic', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        modes,
        temperature_kelvin: temperatureKelvin,
        low_frequency_cutoff_cm1: cutoffCm1,
      }),
    }),
  reactionTemplates: async () => {
    const payload = await requestJson<{ templates: ReactionTemplate[] }>(
      '/api/v1/reaction-analysis/templates',
    )
    return payload.templates
  },
  analyzeReaction: (payload: {
    template_id: ReactionTemplate['template_id']
    states: Record<
      string,
      {
        energy_eV: number
        correction_eV: number
        run_id?: string
        energy_family_id?: string
      }
    >
    h2_free_energy_eV: number
    h2o_free_energy_eV?: number
    oer_equilibrium_free_energy_eV: number
    temperature_kelvin: number
    potential_volts: number
    pH: number
    reference_electrode: 'RHE' | 'SHE'
  }) =>
    requestJson<ReactionAnalysis>('/api/v1/reaction-analysis', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  demoVaspOutput: () => requestJson<VaspDemoResult>('/api/v1/demo/vasp-output'),
}
