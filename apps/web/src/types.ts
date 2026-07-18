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
}

export interface NodeDefinition {
  type_id: string
  title: string
  description: string
  category: 'source' | 'structure' | 'review' | 'protocol' | 'execution' | 'parsing'
  inputs: PortDefinition[]
  outputs: PortDefinition[]
  review_gate: boolean
}

export interface WorkflowTemplateNode {
  node_id: string
  type_id: string
  position: { x: number; y: number }
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
  schema_version: 'catex.web-workflow.v1'
  nodes: WorkflowTemplateNode[]
  edges: WorkflowTemplateEdge[]
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
    free_energy_eV: number
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
  demo?: {
    synthetic: true
    scientific_result_eligible: false
    commands_executed: false
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
