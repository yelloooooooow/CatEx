import type {
  Capabilities,
  CalculationConfig,
  CalculationResult,
  CalculationPlanResponse,
  CampaignCandidate,
  CampaignDecision,
  CampaignRecord,
  ChgnetPreRelaxationConfig,
  ChgnetPreRelaxationResponse,
  CifConversionResponse,
  EnergyDerivation,
  ExperimentalCandidateReview,
  ExperimentalCatalogSnapshot,
  ExperimentalEvidenceArtifact,
  ExperimentalMaterialization,
  ExperimentalModelingCapabilities,
  ExperimentalModelingRun,
  ExperimentalRunSummary,
  ExperimentalSpec,
  ExperimentalSpecRevision,
  HpcCancellationReceipt,
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
  VaspResultDocument,
  WorkflowValidation,
  WorkflowDraft,
  WorkflowExecutionPlan,
  WorkflowRevision,
  WorkflowRunGraph,
  WorkflowTemplateCatalogItem,
} from './types'
import type { WorkflowValidationRequest } from './workflow'

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    const value = detail?.detail
    const message =
      typeof value === 'string'
        ? value
        : typeof value?.message === 'string'
          ? value.message
          : `Request failed (${response.status})`
    throw new Error(message)
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
  workflowTemplates: async () => {
    const payload = await requestJson<{ templates: WorkflowTemplateCatalogItem[] }>(
      '/api/v1/workflows/templates',
    )
    return payload.templates
  },
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
  parseVaspOutputFiles: (files: File[]) => {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    return requestJson<VaspDemoResult>('/api/v1/vasp-output/parse', {
      method: 'POST',
      body: form,
    })
  },
  parseVaspResultFiles: (files: File[]) => {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    return requestJson<VaspResultDocument>('/api/v1/vasp-results/parse', {
      method: 'POST',
      body: form,
    })
  },
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
  experimentalModelingCapabilities: () =>
    requestJson<ExperimentalModelingCapabilities>(
      '/api/v1/experimental-modeling/capabilities',
    ),
  experimentalEvidence: async (projectId: string) => {
    const payload = await requestJson<{ evidence: ExperimentalEvidenceArtifact[] }>(
      `/api/v1/projects/${projectId}/experimental-modeling/evidence`,
    )
    return payload.evidence
  },
  addExperimentalEvidence: (projectId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return requestJson<ExperimentalEvidenceArtifact>(
      `/api/v1/projects/${projectId}/experimental-modeling/evidence`,
      { method: 'POST', body: form },
    )
  },
  experimentalSpec: async (projectId: string) => {
    const payload = await requestJson<{ revision: ExperimentalSpecRevision | null }>(
      `/api/v1/projects/${projectId}/experimental-modeling/spec`,
    )
    return payload.revision
  },
  saveExperimentalSpec: (projectId: string, payload: ExperimentalSpec) =>
    requestJson<ExperimentalSpecRevision>(
      `/api/v1/projects/${projectId}/experimental-modeling/spec`,
      {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
  experimentalCatalogs: async (projectId: string) => {
    const payload = await requestJson<{ catalogs: ExperimentalCatalogSnapshot[] }>(
      `/api/v1/projects/${projectId}/experimental-modeling/catalogs`,
    )
    return payload.catalogs
  },
  fetchOptimadeCatalog: (
    projectId: string,
    payload: {
      base_url: string
      provider_id: string
      required_elements: string[]
      maximum_results: number
      maximum_pages: number
      license?: string
      citation?: string
    },
  ) =>
    requestJson<ExperimentalCatalogSnapshot>(
      `/api/v1/projects/${projectId}/experimental-modeling/providers/optimade/search`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
  fetchMaterialsProjectCatalog: (
    projectId: string,
    payload: { required_elements: string[]; maximum_results: number },
  ) =>
    requestJson<ExperimentalCatalogSnapshot>(
      `/api/v1/projects/${projectId}/experimental-modeling/providers/materials-project/search`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
  experimentalRuns: async (projectId: string) => {
    const payload = await requestJson<{ runs: ExperimentalRunSummary[] }>(
      `/api/v1/projects/${projectId}/experimental-modeling/runs`,
    )
    return payload.runs
  },
  createExperimentalRun: (
    projectId: string,
    payload: {
      planner_kind: 'rule' | 'gpt'
      catalog_ids: string[]
      maximum_representatives: number
      xrd_settings: {
        wavelength: string
        shift_values_degrees: number[]
        fwhm_values_degrees: number[]
        baseline_window_points: number
        peak_relative_threshold: number
        peak_tolerance_degrees: number
        single_phase_pool: number
        maximum_phases: number
        complexity_penalty: number
        minimum_supported_score: number
        ambiguity_margin: number
      }
    },
  ) =>
    requestJson<ExperimentalModelingRun>(
      `/api/v1/projects/${projectId}/experimental-modeling/runs`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
  experimentalRun: (projectId: string, runId: string) =>
    requestJson<ExperimentalModelingRun>(
      `/api/v1/projects/${projectId}/experimental-modeling/runs/${runId}`,
    ),
  experimentalReviews: async (projectId: string, runId: string) => {
    const payload = await requestJson<{ reviews: ExperimentalCandidateReview[] }>(
      `/api/v1/projects/${projectId}/experimental-modeling/runs/${runId}/reviews`,
    )
    return payload.reviews
  },
  reviewExperimentalCandidates: (
    projectId: string,
    runId: string,
    payload: {
      approved_candidate_ids: string[]
      reviewer: string
      note: string
    },
  ) =>
    requestJson<ExperimentalCandidateReview>(
      `/api/v1/projects/${projectId}/experimental-modeling/runs/${runId}/reviews`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
  materializeExperimentalCandidates: (
    projectId: string,
    runId: string,
    payload: {
      candidate_ids: string[]
      confirm_report_sha256: string
      approved_write: true
    },
  ) =>
    requestJson<ExperimentalMaterialization>(
      `/api/v1/projects/${projectId}/experimental-modeling/runs/${runId}/materializations`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
  runChgnetPreRelaxation: (
    projectId: string,
    artifactId: string,
    config: ChgnetPreRelaxationConfig,
  ) =>
    requestJson<ChgnetPreRelaxationResponse>(
      `/api/v1/projects/${projectId}/chgnet-pre-relaxations`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          artifact_id: artifactId,
          model_name: config.model_name,
          optimizer: config.optimizer,
          fmax_eV_per_angstrom: config.fmax_eV_per_angstrom,
          max_steps: config.max_steps,
          relax_cell: config.relax_cell,
          device: config.device,
        }),
      },
    ),
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
  projectWorkflowDraft: async (projectId: string) => {
    const payload = await requestJson<{ draft: WorkflowDraft | null }>(
      `/api/v1/projects/${projectId}/workflow/draft`,
    )
    return payload.draft
  },
  saveProjectWorkflowDraft: (
    projectId: string,
    payload: WorkflowValidationRequest,
    expectedDraftSha256?: string,
  ) =>
    requestJson<{ draft: WorkflowDraft; validation: WorkflowValidation }>(
      `/api/v1/projects/${projectId}/workflow/draft`,
      {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          ...payload,
          ...(expectedDraftSha256
            ? { expected_draft_sha256: expectedDraftSha256 }
            : {}),
        }),
      },
    ),
  workflowRevisions: async (projectId: string) => {
    const payload = await requestJson<{ revisions: WorkflowRevision[] }>(
      `/api/v1/projects/${projectId}/workflow/revisions`,
    )
    return payload.revisions
  },
  publishWorkflowRevision: (projectId: string, title: string, note = '') =>
    requestJson<{ revision: WorkflowRevision; validation: WorkflowValidation }>(
      `/api/v1/projects/${projectId}/workflow/revisions`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title, note }),
      },
    ),
  workflowRunGraphs: async (projectId: string) => {
    const payload = await requestJson<{ run_graphs: WorkflowRunGraph[] }>(
      `/api/v1/projects/${projectId}/workflow/run-graphs`,
    )
    return payload.run_graphs
  },
  createWorkflowRunGraph: (
    projectId: string,
    revisionId: string,
    label: string,
  ) =>
    requestJson<WorkflowRunGraph>(
      `/api/v1/projects/${projectId}/workflow/run-graphs`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          revision_id: revisionId,
          label,
          bindings: {},
        }),
      },
    ),
  workflowExecutionPlan: async (projectId: string, runGraphId: string) => {
    const payload = await requestJson<{ plan: WorkflowExecutionPlan }>(
      `/api/v1/projects/${projectId}/workflow/run-graphs/${runGraphId}/execution-plan`,
    )
    return payload.plan
  },
  campaigns: async (projectId: string) => {
    const payload = await requestJson<{ campaigns: CampaignRecord[] }>(
      `/api/v1/projects/${projectId}/campaigns`,
    )
    return payload.campaigns
  },
  createCampaign: (
    projectId: string,
    payload: {
      title: string
      objective: string
      workflow_revision_id?: string
    },
  ) =>
    requestJson<CampaignRecord>(`/api/v1/projects/${projectId}/campaigns`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  campaignDetail: (projectId: string, campaignId: string) =>
    requestJson<{
      campaign: CampaignRecord
      candidates: CampaignCandidate[]
      decisions: CampaignDecision[]
    }>(`/api/v1/projects/${projectId}/campaigns/${campaignId}`),
  addCampaignCandidate: (
    projectId: string,
    campaignId: string,
    payload: {
      label: string
      structure_artifact_id?: string
      variables: Record<string, unknown>
    },
  ) =>
    requestJson<CampaignCandidate>(
      `/api/v1/projects/${projectId}/campaigns/${campaignId}/candidates`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
  recordCampaignDecision: (
    projectId: string,
    campaignId: string,
    payload: {
      action: string
      rationale: string
      candidate_id?: string
      evidence?: Record<string, unknown>
    },
  ) =>
    requestJson<CampaignDecision>(
      `/api/v1/projects/${projectId}/campaigns/${campaignId}/decisions`,
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
  cancelRemoteRun: (
    projectId: string,
    profile: HpcProfile,
    runId: string,
    approvedCancel: boolean,
  ) =>
    requestJson<HpcCancellationReceipt>(
      `/api/v1/projects/${projectId}/remote-cancel`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          profile,
          run_id: runId,
          approved_cancel: approvedCancel,
        }),
      },
    ),
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
