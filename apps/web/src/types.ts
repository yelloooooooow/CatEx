export type Severity = 'info' | 'warning' | 'error'

export interface Diagnostic {
  code: string
  severity: Severity
  message: string
  context?: Record<string, unknown>
}

export interface PortDefinition {
  port_id: string
  label: string
  kind: string
  required: boolean
  multiple: boolean
}

export interface ParameterDefinition {
  key: string
  label: string
  kind: 'string' | 'integer' | 'number' | 'boolean' | 'choice'
  default: string | number | boolean
  description: string
  required: boolean
  choices: string[]
  minimum: number | null
  maximum: number | null
}

export interface NodeDefinition {
  type_id: string
  title: string
  description: string
  category:
    | 'source'
    | 'structure'
    | 'experiment'
    | 'review'
    | 'protocol'
    | 'execution'
    | 'parsing'
    | 'calculation'
  inputs: PortDefinition[]
  outputs: PortDefinition[]
  parameters: ParameterDefinition[]
  review_gate: boolean
}

export interface WorkflowTemplateNode {
  node_id: string
  type_id: string
  position: { x: number; y: number }
  parameters: Record<string, string | number | boolean>
}

export interface WorkflowTemplateEdge {
  edge_id: string
  source_node_id: string
  source_port_id: string
  target_node_id: string
  target_port_id: string
}

export interface WorkflowTemplate {
  schema_version: string
  template_id: string
  title: string
  description: string
  nodes: WorkflowTemplateNode[]
  edges: WorkflowTemplateEdge[]
}

export interface WorkflowValidation {
  schema_version: string
  status: 'valid' | 'error'
  valid: boolean
  diagnostics: Diagnostic[]
}

export interface TemplateResponse {
  template: WorkflowTemplate
  validation: WorkflowValidation
}

export interface Capabilities {
  schema_version: string
  catex_version: string
  mode: string
  hpc_enabled: boolean
  ssh_enabled: boolean
  hpc_default_active: boolean
  credentials_persisted: boolean
  project_persistence_enabled: boolean
  protocol_editor_enabled: boolean
  local_materialization_enabled: boolean
  writes_outside_ephemeral_storage: boolean
  persistent_storage_root: string
  scientific_acceptance_enabled: boolean
  max_structure_upload_bytes: number
  result_first_enabled?: boolean
  reaction_analysis_enabled?: boolean
  mlip_pre_relaxation_enabled?: boolean
  chgnet?: ChgnetCapabilities
  experimental_modeling_enabled?: boolean
  experimental_modeling?: ExperimentalModelingCapabilities
}

export interface ChgnetCapabilities {
  schema_version: 'catex.chgnet-capabilities.v1'
  available: boolean
  packages: Record<string, { installed: boolean; version: string | null }>
  missing_packages: string[]
  models: string[]
  optimizers: string[]
  devices: string[]
  cuda_available: boolean
  defaults: ChgnetPreRelaxationConfig
  execution_location: 'local'
  contacts_hpc: false
}

export interface ChgnetPreRelaxationConfig {
  schema_version?: 'catex.chgnet-pre-relaxation-config.v1'
  model_name: '0.3.0' | 'r2scan'
  optimizer: 'FIRE' | 'BFGS' | 'LBFGS'
  fmax_eV_per_angstrom: number
  max_steps: number
  relax_cell: boolean
  device: 'auto' | 'cpu' | 'cuda'
}

export interface StructureRecord {
  formula: string
  reduced_formula: string
  num_sites: number
  species_counts: Array<[string, number]>
  lattice_lengths: [number, number, number]
  lattice_angles: [number, number, number]
  volume_angstrom3: number
  canonical_hash: string | null
}

export interface InspectionMetrics {
  minimum_distance_angstrom: number | null
  volume_per_atom_angstrom3: number | null
  occupied_span_fractions: [number, number, number] | null
  estimated_vacuum_angstrom: [number, number, number] | null
}

export interface ViewerPayload {
  schema_version: string
  lattice: [number, number, number][]
  species: string[]
  fractional_coordinates: [number, number, number][]
  cartesian_coordinates: [number, number, number][]
  periodic: [boolean, boolean, boolean]
}

export interface StructureInspectionResponse {
  schema_version: string
  retained: boolean
  source: { filename: string; size_bytes: number; sha256: string }
  inspection: {
    schema_version: string
    status: 'ok' | 'warning' | 'error'
    record: StructureRecord | null
    metrics: InspectionMetrics | null
    diagnostics: Diagnostic[]
  }
  viewer: ViewerPayload | null
}

export interface CifConversionResponse {
  schema_version: 'catex.cif-to-poscar.v1'
  source_filename: string
  output_filename: 'POSCAR'
  poscar_text: string
  inspection: StructureInspectionResponse
  writes_performed: false
}

export interface SelectiveDynamicsResponse {
  schema_version: 'catex.selective-dynamics.v1'
  strategy: 'none' | 'adsorbate_indices' | 'bottom_layers'
  poscar_text: string
  site_count: number
  fixed_indices_1based: number[]
  mobile_indices_1based: number[]
  fixed_count: number
  mobile_count: number
  writes_performed: false
}

export interface ProjectRecord {
  schema_version: 'catex.web-project.v1'
  project_id: string
  title: string
  purpose: 'literature_reproduction' | 'original_research' | 'experimental_interpretation' | 'training'
  description: string
  template_id: string
  created_at_utc: string
  updated_at_utc: string
  artifact_count: number
  run_count: number
  workflow_saved: boolean
  protocol_saved: boolean
  remote_submission_count: number
}

export interface ProjectArtifact {
  schema_version: 'catex.web-artifact.v1'
  artifact_id: string
  project_id: string
  artifact_type: 'structure'
  original_filename: string
  stored_filename: string
  sha256: string
  size_bytes: number
  created_at_utc: string
  retained: true
  inspection: StructureInspectionResponse['inspection']
  viewer: ViewerPayload | null
}

export interface ProjectArtifactSource {
  schema_version: 'catex.web-artifact-source.v1'
  artifact_id: string
  filename: string
  sha256: string
  content: string
  read_only: true
}

export interface ChgnetPreRelaxationResponse {
  schema_version: 'catex.web-chgnet-pre-relaxation.v1'
  relaxation_id: string
  project_id: string
  recorded_at_utc: string
  source_artifact_id: string
  source_sha256: string
  output_artifact_id: string
  output_sha256: string
  config: ChgnetPreRelaxationConfig
  summary: {
    schema_version: 'catex.chgnet-pre-relaxation-result.v1'
    status: 'converged' | 'max_steps_or_optimizer_stop'
    converged: boolean
    n_steps: number
    final_fmax_eV_per_angstrom: number
    target_fmax_eV_per_angstrom: number
    initial_energy_eV: number
    final_energy_eV: number
    energy_change_eV: number
    maximum_displacement_angstrom: number
    rms_displacement_angstrom: number
    fixed_atom_count: number
    mobile_atom_count: number
    fixed_indices_1based: number[]
    model_name: string
    model_version: string
    optimizer: string
    device: string
    relax_cell: boolean
    elapsed_seconds: number
    input_sha256?: string
    output_sha256?: string
    scientific_role: 'geometry_pre_relaxation_only'
  }
  warnings: string[]
  hpc_contacted: false
  vasp_executed: false
  output_artifact: ProjectArtifact
  poscar_text: string
  retained: true
}

export interface StructureReview {
  schema_version: 'catex.web-structure-review.v1'
  artifact_id: string
  artifact_sha256: string
  approved: boolean
  reviewer: string
  reviewed_at_utc: string
  note: string
}

export interface SavedWorkflowPayload {
  schema_version: 'catex.web-workflow.v1' | 'catex.workflow-draft.v1'
  nodes: WorkflowTemplateNode[]
  edges: WorkflowTemplateEdge[]
  draft_sha256?: string
  generation?: number
  saved_at_utc?: string | null
}

export interface WorkflowDraft extends SavedWorkflowPayload {
  schema_version: 'catex.workflow-draft.v1'
  draft_sha256: string
  generation: number
  saved_at_utc: string | null
}

export interface WorkflowRevision {
  schema_version: 'catex.workflow-revision.v1'
  revision_id: string
  content_sha256: string
  published_at_utc: string
  title: string
  note: string
  workflow: {
    nodes: WorkflowTemplateNode[]
    edges: WorkflowTemplateEdge[]
  }
}

export interface WorkflowRunGraph {
  schema_version: 'catex.workflow-run-graph.v1'
  run_graph_id: string
  revision_id: string
  workflow_sha256: string
  created_at_utc: string
  label: string
  bindings: Record<string, unknown>
  workflow: {
    nodes: WorkflowTemplateNode[]
    edges: WorkflowTemplateEdge[]
  }
  state: 'planned'
}

export interface WorkflowExecutionPlan {
  schema_version: 'catex.workflow-execution-plan.v1'
  stage_count: number
  stages: Array<{
    stage_id: string
    node_id: string
    node_type: string
    depends_on: string[]
    execution_backend: 'local_chgnet' | 'project_hpc_profile'
    calculation_type: string
    directory_name: string
    structure_source: 'project_structure' | 'upstream_CONTCAR'
    incar_overrides: Record<string, string | number | boolean>
    parameters: Record<string, string | number | boolean>
    required_inputs: string[]
    produced_outputs: string[]
  }>
  commands_executed: false
  files_written: false
  submitted: false
  automatic_scientific_parameter_changes: false
}

export interface WorkflowTemplateCatalogItem extends WorkflowTemplate {
  validation: WorkflowValidation
}

export interface CampaignRecord {
  schema_version: 'catex.campaign.v1'
  campaign_id: string
  project_id: string
  title: string
  objective: string
  workflow_revision_id: string | null
  status: 'active' | 'paused' | 'completed' | 'archived'
  created_at_utc: string
  updated_at_utc?: string
  candidate_count: number
  decision_count: number
}

export interface CampaignCandidate {
  schema_version: 'catex.campaign-candidate.v1'
  candidate_id: string
  campaign_id: string
  label: string
  structure_artifact_id: string | null
  variables: Record<string, unknown>
  status: 'proposed' | 'prepared' | 'running' | 'succeeded' | 'failed' | 'excluded'
  created_at_utc: string
}

export interface CampaignDecision {
  schema_version: 'catex.campaign-decision.v1'
  decision_id: string
  campaign_id: string
  candidate_id: string | null
  action: string
  rationale: string
  evidence: Record<string, unknown>
  recorded_at_utc: string
}

export interface CalculationConfig {
  schema_version: 'catex.web-calculation-config.v1'
  protocol: Record<string, unknown>
  potcar_metadata: Record<string, unknown>
  execution_profile: Record<string, unknown>
  cluster_policy: Record<string, unknown>
}

export interface CalculationPlanResponse {
  schema_version: 'catex.web-plan-response.v1'
  resolution: {
    status: string
    diagnostics: Diagnostic[]
    resolved: {
      approved: boolean
      energy_family_id: string
      resolved_protocol_sha256: string
      incar_text: string
      kpoints_text: string
    } | null
  }
  plan: {
    status: string
    job_name: string
    job_directory: string
    plan_sha256: string
    ready_for_materialization: boolean
    diagnostics: Diagnostic[]
    slurm: {
      status: string
      script_text: string
      script_sha256: string
      submitted: boolean
      diagnostics: Diagnostic[]
    }
  } | null
  writes_performed: false
  submitted: false
}

export interface MaterializationResponse {
  schema_version: 'catex.web-materialization-response.v1'
  plan: NonNullable<CalculationPlanResponse['plan']>
  materialization: {
    status: string
    job_directory: string
    submitted: false
    potcar_materialized: false
    diagnostics: Diagnostic[]
  }
  submitted: false
  potcar_materialized: false
}

export interface RunSummary {
  schema_version: 'catex.web-run-summary.v1'
  run_id: string
  plan_sha256: string
  resolved_protocol_sha256: string
  energy_family_id: string
  local_materialized: true
  potcar_materialized: boolean
  submitted: boolean
  job_id: string | null
  cancellation_requested: boolean
  result_count: number
}

export interface HpcProfile {
  host: string
  port: number
  username: string
  private_key_path: string
  allowed_root: string
  potcar_builder?: string
  potcar_root?: string
  host_key_sha256?: string
  connect_timeout_seconds: number
}

export interface RemotePotcarCopy {
  schema_version: 'catex.hpc-potcar-copy.v1'
  run_id: string
  filename: 'POTCAR'
  content_base64: string
  sha256: string
  writes_performed_remotely: false
}

export interface RemotePotcarMetadata {
  schema_version: 'catex.potcar-metadata.v1'
  potential_family: string
  datasets: Array<{
    element: string
    potential_label: string
    titel: string
    lexch: string
    zval: number
    enmax_eV: number
    sha256: string
  }>
  raw_potcar_returned: false
  writes_performed: false
}

export interface HpcObservation {
  schema_version: 'catex.web-hpc-observation.v1'
  observed_at_utc: string
  snapshot_filename: string
  report: {
    status: string
    source: 'squeue' | 'sacct'
    observation: {
      job_id: string
      state: string
      active: boolean
      terminal: boolean
      elapsed_seconds: number
    } | null
    diagnostics: Diagnostic[]
  }
  writes_performed_remotely: false
}

export interface HpcCancellationReceipt {
  schema_version: 'catex.cancellation-receipt.v1'
  requested_at_utc: string
  run_id: string
  job_id: string
  cancellation_requested: true
  command_output_sha256: string
  remote_files_modified: false
  remote_files_deleted: false
}

export interface RemoteRunResult {
  schema_version: 'catex.web-run-result.v1'
  run_id: string
  job_id: string
  vasp: VaspDemoResult
  binding: {
    status: string
    binding_valid: boolean
    scheduler_success: boolean
    ready_for_scientific_review: boolean
    diagnostics: Diagnostic[]
  }
  restart_assessment: {
    schema_version: 'catex.restart-assessment.v1'
    status: 'blocked' | 'manual_review_required' | 'no_restart' | 'wait'
    failure_categories: string[]
    required_reviews: string[]
    restart_authorized: false
    restart_inputs_materialized: false
    scientific_parameters_changed: false
    diagnostics: Diagnostic[]
  }
  scientific_result_accepted: false
  human_review_required: false
  analysis_eligible: boolean
  initial_structure: ResultStructureSnapshot | null
  final_structure: ResultStructureSnapshot | null
}

export interface ResultStructureSnapshot {
  filename: string
  inspection: StructureInspectionResponse['inspection']
  viewer: ViewerPayload | null
}

export interface CalculationResult {
  schema_version: 'catex.web-calculation-result.v1'
  run_id: string
  job_id: string | null
  status: string
  calculation_type: string
  energy_eV: number | null
  energy_kind: string | null
  energy_family_id: string | null
  analysis_eligible: boolean
  final_structure: ResultStructureSnapshot | null
  vibrations: VibrationSummary | null
}

export interface ReferenceCaseSummary {
  schema_version: 'catex.web-reference-case.v1'
  case_id: string
  title: string
  role: string
  readiness: {
    status: string
    ready_for_production_planning: boolean
    blocking_requirement_ids: string[]
    satisfied_requirement_ids: string[]
    report_sha256: string
    requirements: Array<{
      requirement_id: string
      category: string
      description: string
      status: string
      note: string
    }>
  }
  che_protocol_draft: {
    status: string
    temperature_kelvin: number | null
  }
  execution_authorized: false
}

export interface ReviewedEnergy {
  schema_version: 'catex.reviewed-energy.v1'
  energy_id: string
  kind: string
  value_eV: number
  energy_family_id: string
  record_sha256: string
  scientific_result_accepted: true
  eligible_for_same_energy_family_derivation: true
}

export interface EnergyDerivation {
  schema_version: 'catex.linear-energy-derivation.v1'
  status: 'derived' | 'not_derived'
  derivation_id: string
  value_eV: number | null
  energy_family_id: string | null
  kind: string | null
  derivation_sha256: string | null
  scientific_interpretation_approved: false
  thermochemical_corrections_included: false
  diagnostics: Diagnostic[]
}

export interface VaspDemoResult {
  schema_version: string
  status: string
  scientifically_complete: boolean
  completion_reason: string
  target_vasp_version: string
  detected_vasp_version: string | null
  energy: {
    free_energy_eV: number | null
    energy_without_entropy_eV: number | null
    sigma_zero_energy_eV: number | null
  } | null
  forces: {
    vectors_eV_per_angstrom: number[][]
    maximum_norm_eV_per_angstrom: number
    maximum_atom_index_1based: number
  } | null
  convergence: {
    electronic: string
    ionic: string
    calculation_type: string
    ionic_steps_completed: number
    final_electronic_step: number | null
    criteria: {
      EDIFF_eV: number | null
      EDIFFG_eV_per_angstrom: number | null
      NELM: number | null
      NSW: number | null
      IBRION: number | null
    }
  }
  termination: {
    outcome: string
    normal_footer_found: boolean
    fatal_error_codes: string[]
  }
  magnetization: {
    projected_components: Array<{
      component: string
      site_projected_totals_muB: number[]
      projected_sum_muB: number
    }>
    cell_moment_muB: number[] | null
  } | null
  vibrations: VibrationSummary | null
  diagnostics: Diagnostic[]
  upload?: {
    filenames: string[]
    retained: false
    hpc_contacted: false
  }
  demo?: {
    synthetic: true
    scientific_result_eligible: false
    commands_executed: false
    hpc_contacted: false
  }
}

export interface VaspResultDocument {
  schema_version: 'catex.vasp-result-document.v1'
  directory: string
  artifact_inventory: Array<{
    filename: string
    size_bytes: number
    sha256: string
  }>
  energy: {
    free_energy_eV: number | null
    energy_without_entropy_eV?: number | null
    sigma_zero_energy_eV: number | null
    source?: string
  } | null
  vasp_output: VaspDemoResult | null
  vasprun: {
    filename: 'vasprun.xml'
    ionic_step_count: number
    free_energy_eV: number | null
    sigma_zero_energy_eV: number | null
    fermi_energy_eV: number | null
  } | null
  final_structure: {
    source: 'CONTCAR'
    record: StructureRecord
    viewer: ViewerPayload
  } | null
  trajectory: {
    filename: 'XDATCAR'
    frame_count: number
    coordinate_marker: string | null
  } | null
  volumetric: Array<{
    filename: 'CHGCAR' | 'LOCPOT' | 'ELFCAR'
    kind: string
    grid_dimensions: number[] | null
    grid_point_count: number | null
    values_included_in_document: false
  }>
  diagnostics: Diagnostic[]
  upload?: {
    filenames: string[]
    retained: false
    hpc_contacted: false
  }
}

export interface VibrationMode {
  mode_index: number
  imaginary: boolean
  frequency_THz: number
  'wavenumber_cm-1': number
  energy_meV: number
}

export interface VibrationSummary {
  modes: VibrationMode[]
  mode_count: number
  real_mode_count: number
  imaginary_mode_count: number
  zero_point_energy_eV: number
}

export interface HarmonicThermochemistry {
  schema_version: 'catex.harmonic-thermochemistry.v1'
  model: 'harmonic_vibration'
  temperature_kelvin: number
  'low_frequency_cutoff_cm-1': number
  included_mode_count: number
  excluded_low_frequency_count: number
  excluded_imaginary_count: number
  zero_point_energy_eV: number
  thermal_vibrational_energy_eV: number
  entropy_eV_per_kelvin: number
  entropy_term_eV: number
  free_energy_correction_eV: number
  warnings: string[]
}

export interface ReactionTemplate {
  template_id: 'her-che' | 'oer-aem-che'
  name: string
  state_keys: string[]
  state_labels: string[]
  reservoir_keys: string[]
}

export interface ReactionAnalysis {
  schema_version: 'catex.electrocatalysis-analysis.v1'
  template_id: ReactionTemplate['template_id']
  conditions: {
    temperature_kelvin: number
    potential_volts: number
    pH: number
    reference_electrode: 'RHE' | 'SHE'
  }
  states: Array<{
    key: string
    label: string
    electron_count: number
    standard_free_energy_eV: number
    free_energy_eV: number
  }>
  step_free_energies_eV: number[]
  potential_limiting_step: number
  limiting_potential_volts: number | null
  overpotential_volts: number | null
  descriptor_eV: number | null
  energy_family_id: string | null
  provenance_preserved: true
}

export type RuntimeStatus = 'idle' | 'running' | 'success' | 'warning' | 'review' | 'blocked'

export type ExperimentalSampleState =
  | 'as_prepared'
  | 'activated'
  | 'operando_approximation'
  | 'post_mortem'
  | 'unspecified'

export type ExperimentalEvidenceKind =
  | 'xrd'
  | 'gixrd'
  | 'icp'
  | 'eds'
  | 'xps'
  | 'raman'
  | 'sem'
  | 'tem'
  | 'synthesis'
  | 'electrochemistry'
  | 'literature'
  | 'other'

export interface ExperimentalModelingCapabilities {
  schema_version: 'catex.experimental-modeling-capabilities.v1'
  enabled: boolean
  max_evidence_upload_bytes: number
  rule_planner: { available: boolean; external_api: false }
  providers: {
    project: { available: boolean; requires_key: false }
    optimade: { available: boolean; requires_key: false }
    materials_project: {
      available: boolean
      client_installed: boolean
      key_configured: boolean
      requires_key: true
      api_key_environment_variable: 'MP_API_KEY'
    }
  }
  gpt_planner: {
    available: boolean
    key_configured: boolean
    api_key_environment_variable: 'OPENAI_API_KEY'
    model: string
    responses_api: true
    stores_responses: false
  }
  credentials_persisted: false
}

export interface ExperimentalEvidenceArtifact {
  schema_version: 'catex.web-experimental-evidence-artifact.v1'
  evidence_artifact_id: string
  project_id: string
  original_filename: string
  stored_filename: string
  sha256: string
  size_bytes: number
  created_at_utc: string
  retained: true
}

export interface ExperimentalEvidenceInput {
  evidence_id: string
  kind: ExperimentalEvidenceKind
  sample_state: ExperimentalSampleState
  role: 'hard' | 'soft' | 'context'
  metadata: Record<string, unknown>
  evidence_artifact_id?: string
  note: string
}

export interface ExperimentalCompositionConstraint {
  element: string
  minimum_atomic_fraction: number
  maximum_atomic_fraction: number
  scope: 'bulk' | 'surface' | 'local' | 'unspecified'
  evidence_ids: string[]
}

export interface ExperimentalSpec {
  schema_version: 'catex.experiment-spec.v1'
  sample_id: string
  target_state: ExperimentalSampleState
  material_pack: string
  allowed_elements: string[]
  excluded_elements: string[]
  composition_constraints: ExperimentalCompositionConstraint[]
  evidence: ExperimentalEvidenceInput[]
}

export interface ExperimentalSpecRevision {
  schema_version: 'catex.web-experimental-spec-revision.v1'
  spec_revision_id: string
  project_id: string
  created_at_utc: string
  identity_sha256: string
  spec: ExperimentalSpec
  normalized_spec: ExperimentalSpec
}

export interface ExperimentalStructureReference {
  provider: string
  record_id: string
  key: string
  formula: string
  elements: string[]
  source_kind: string
  source_locator: string
  structure_sha256: string
  artifact_sha256: string | null
  license: string
  citation: string
}

export interface ExperimentalCatalogSnapshot {
  schema_version: 'catex.web-structure-catalog-snapshot.v1'
  catalog_id: string
  project_id: string
  provider_kind: 'optimade' | 'materials_project'
  provider_id: string
  display_provider_id: string
  created_at_utc: string
  query: Record<string, unknown>
  reference_count: number
  references: ExperimentalStructureReference[]
  fetch_report: Record<string, unknown>
}

export interface ExperimentalCandidateAssessment {
  candidate_id: string
  recipe_id: string
  hypothesis_id: string
  parent_reference_key: string
  model_kind: 'bulk' | 'surface'
  structure_sha256: string
  formula: string
  num_sites: number
  valid: boolean
  evidence_score: number
  phase_support_score: number | null
  xrd_directly_applicable: boolean
  transformation_sha256s: string[]
  diagnostics: Diagnostic[]
}

export interface ExperimentalCandidate {
  candidate_id: string
  relative_path: string
  assessment: ExperimentalCandidateAssessment
  viewer: ViewerPayload
}

export interface ExperimentalPhaseSearch {
  status: string
  best_score: number | null
  score_interpretation: string
  considered_reference_keys: string[]
  settings: Record<string, unknown>
  single_phase_matches: Array<{
    reference_key: string
    formula: string
    evidence_score: number
    cosine_similarity: number
    explained_intensity_fraction: number
    normalized_absolute_residual: number
    shift_degrees: number
    fwhm_degrees: number
    peak_evidence: {
      matched_pairs_degrees: number[][]
      unexplained_observed_degrees: number[]
      missing_predicted_degrees: number[]
    }
  }>
  combination_matches: Array<{
    reference_keys: string[]
    formulas: string[]
    diffraction_contributions: number[]
    evidence_score: number
    explained_intensity_fraction: number
    normalized_absolute_residual: number
  }>
  diagnostics: Diagnostic[]
}

export interface ExperimentalModelingRun {
  schema_version: 'catex.web-experimental-modeling-run.v1'
  run_id: string
  project_id: string
  created_at_utc: string
  spec_revision_id: string
  planner_kind: 'rule' | 'gpt'
  catalog_ids: string[]
  report: {
    status: string
    claim_ceiling: string
    claim_interpretation: string
    identity_sha256: string
    phase_search: ExperimentalPhaseSearch | null
    candidate_plan: {
      hypotheses: Array<{
        hypothesis_id: string
        summary: string
        assumptions: string[]
        generated_atomistic_candidate: boolean
      }>
      recipes: Array<Record<string, unknown>>
      diagnostics: Diagnostic[]
    }
    candidate_assessments: ExperimentalCandidateAssessment[]
    representative_candidate_ids: string[]
    unresolved_hypothesis_ids: string[]
    ambiguity_reasons: string[]
    recommended_next_experiments: string[]
    diagnostics: Diagnostic[]
    external_api_called: boolean
    writes_performed: false
  }
  xrd_plot: {
    schema_version: 'catex.web-xrd-plot.v1'
    label: string
    two_theta_degrees: number[]
    observed_normalized: number[]
    fitted_normalized: number[]
    residual: number[]
  } | null
  candidates: ExperimentalCandidate[]
  review_required: true
  materialized: boolean
  materialization_id?: string
}

export interface ExperimentalRunSummary {
  run_id: string
  created_at_utc: string
  spec_revision_id: string
  planner_kind: 'rule' | 'gpt'
  status: string
  claim_ceiling: string
  report_sha256: string
  candidate_count: number
  representative_count: number
  materialized: boolean
}

export interface ExperimentalCandidateReview {
  schema_version: 'catex.web-experimental-model-review.v1'
  review_id: string
  project_id: string
  run_id: string
  report_sha256: string
  approved_candidate_ids: string[]
  reviewer: string
  note: string
  reviewed_at_utc: string
  unique_structure_claimed: false
}

export interface ExperimentalMaterialization {
  schema_version: 'catex.web-experimental-materialization.v1'
  materialization_id: string
  project_id: string
  run_id: string
  report_sha256: string
  candidate_ids: string[]
  artifacts: Array<{ candidate_id: string; artifact: ProjectArtifact }>
  materialized_at_utc: string
  approved_write: true
}
