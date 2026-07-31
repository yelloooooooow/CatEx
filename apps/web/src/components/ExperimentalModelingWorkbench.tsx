import {
  Atom,
  Beaker,
  CheckCircle2,
  Database,
  FileUp,
  Layers3,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { api } from '../api'
import { useI18n } from '../i18n'
import type {
  ExperimentalCandidateReview,
  ExperimentalCatalogSnapshot,
  ExperimentalCompositionConstraint,
  ExperimentalEvidenceArtifact,
  ExperimentalEvidenceInput,
  ExperimentalEvidenceKind,
  ExperimentalModelingCapabilities,
  ExperimentalModelingRun,
  ExperimentalRunSummary,
  ExperimentalSampleState,
  ExperimentalSpec,
  ProjectArtifact,
} from '../types'
import { StructureViewer } from './StructureViewer'

interface ExperimentalModelingWorkbenchProps {
  projectId: string | null
  artifacts: ProjectArtifact[]
  onMessage: (tone: 'success' | 'error' | 'neutral' | 'warning', message: string) => void
  onArtifactsChanged: () => Promise<void> | void
  onOpenStructures: () => void
}

const SAMPLE_STATES: ExperimentalSampleState[] = [
  'as_prepared',
  'activated',
  'operando_approximation',
  'post_mortem',
  'unspecified',
]

const EVIDENCE_KINDS: ExperimentalEvidenceKind[] = [
  'xrd',
  'gixrd',
  'icp',
  'eds',
  'xps',
  'tem',
  'sem',
  'raman',
  'synthesis',
  'electrochemistry',
  'literature',
  'other',
]

const DEFAULT_SPEC: ExperimentalSpec = {
  schema_version: 'catex.experiment-spec.v1',
  sample_id: 'sample-1',
  target_state: 'activated',
  material_pack: 'alloy-electrocatalyst',
  allowed_elements: ['Ni', 'Mo'],
  excluded_elements: [],
  composition_constraints: [],
  evidence: [],
}

const DEFAULT_XRD_SETTINGS = {
  wavelength: 'CuKa',
  shift_values_degrees: [-0.2, -0.1, 0, 0.1, 0.2],
  fwhm_values_degrees: [0.1, 0.2, 0.4],
  baseline_window_points: 0,
  peak_relative_threshold: 0.05,
  peak_tolerance_degrees: 0.25,
  single_phase_pool: 8,
  maximum_phases: 3,
  complexity_penalty: 0.02,
  minimum_supported_score: 0.55,
  ambiguity_margin: 0.03,
}

function parseElements(value: string): string[] {
  return [...new Set(value.split(/[\s,;]+/).map((item) => item.trim()).filter(Boolean))]
}

function parseNumberList(value: string): number[] {
  const numbers = value
    .split(/[\s,;]+/)
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item))
  if (!numbers.length) throw new Error('At least one finite numeric value is required.')
  return numbers
}

function shortHash(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-6)}`
}

function formatScore(value: number | null | undefined): string {
  return value == null ? '—' : value.toFixed(3)
}

function XrdComparisonPlot({ run }: { run: ExperimentalModelingRun }) {
  const plot = run.xrd_plot
  if (!plot || plot.two_theta_degrees.length < 2) return null
  const width = 920
  const height = 270
  const pad = 34
  const xMin = plot.two_theta_degrees[0]
  const xMax = plot.two_theta_degrees.at(-1) ?? xMin + 1
  const scaleX = (value: number) => pad + ((value - xMin) / Math.max(xMax - xMin, 1e-9)) * (width - pad * 2)
  const scaleY = (value: number) => 18 + (1 - value) * 150
  const points = (values: number[], mapper: (value: number) => number) =>
    values.map((value, index) => `${scaleX(plot.two_theta_degrees[index])},${mapper(value)}`).join(' ')
  const residualPoints = points(plot.residual, (value) => 218 - value * 36)
  return (
    <div className="experimental-xrd-plot">
      <div className="experimental-plot-legend">
        <span className="observed">Observed</span>
        <span className="fitted">Fitted · {plot.label}</span>
        <span className="residual">Residual</span>
      </div>
      <svg aria-label="Observed, fitted, and residual XRD profiles" viewBox={`0 0 ${width} ${height}`}>
        <line className="axis" x1={pad} x2={width - pad} y1="168" y2="168" />
        <line className="axis" x1={pad} x2={width - pad} y1="218" y2="218" />
        <polyline className="observed-line" points={points(plot.observed_normalized, scaleY)} />
        <polyline className="fitted-line" points={points(plot.fitted_normalized, scaleY)} />
        <polyline className="residual-line" points={residualPoints} />
        <text x={pad} y="260">{xMin.toFixed(1)}°</text>
        <text textAnchor="end" x={width - pad} y="260">{xMax.toFixed(1)}° 2θ</text>
      </svg>
    </div>
  )
}

export function ExperimentalModelingWorkbench({
  projectId,
  artifacts,
  onMessage,
  onArtifactsChanged,
  onOpenStructures,
}: ExperimentalModelingWorkbenchProps) {
  const { tr } = useI18n()
  const [capabilities, setCapabilities] = useState<ExperimentalModelingCapabilities | null>(null)
  const [evidenceArtifacts, setEvidenceArtifacts] = useState<ExperimentalEvidenceArtifact[]>([])
  const [catalogs, setCatalogs] = useState<ExperimentalCatalogSnapshot[]>([])
  const [runs, setRuns] = useState<ExperimentalRunSummary[]>([])
  const [activeRun, setActiveRun] = useState<ExperimentalModelingRun | null>(null)
  const [reviews, setReviews] = useState<ExperimentalCandidateReview[]>([])
  const [spec, setSpec] = useState<ExperimentalSpec>(DEFAULT_SPEC)
  const [specRevisionId, setSpecRevisionId] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [selectedCatalogIds, setSelectedCatalogIds] = useState<string[]>([])
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([])
  const [focusedCandidateId, setFocusedCandidateId] = useState('')

  const [evidenceKind, setEvidenceKind] = useState<ExperimentalEvidenceKind>('xrd')
  const [evidenceState, setEvidenceState] = useState<ExperimentalSampleState>('activated')
  const [evidenceRole, setEvidenceRole] = useState<'hard' | 'soft' | 'context'>('hard')
  const [evidenceNote, setEvidenceNote] = useState('')
  const [evidenceMetadata, setEvidenceMetadata] = useState('{}')
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null)

  const [constraintElement, setConstraintElement] = useState('Ni')
  const [constraintMinimum, setConstraintMinimum] = useState('0.45')
  const [constraintMaximum, setConstraintMaximum] = useState('0.75')
  const [constraintScope, setConstraintScope] = useState<ExperimentalCompositionConstraint['scope']>('bulk')

  const [optimadeUrl, setOptimadeUrl] = useState('')
  const [optimadeProvider, setOptimadeProvider] = useState('optimade')
  const [providerElements, setProviderElements] = useState('Ni, Mo')
  const [providerMaximumResults, setProviderMaximumResults] = useState('50')

  const [plannerKind, setPlannerKind] = useState<'rule' | 'gpt'>('rule')
  const [maximumRepresentatives, setMaximumRepresentatives] = useState('10')
  const [xrdSettings, setXrdSettings] = useState(DEFAULT_XRD_SETTINGS)
  const [shiftGridText, setShiftGridText] = useState('-0.2, -0.1, 0, 0.1, 0.2')
  const [fwhmGridText, setFwhmGridText] = useState('0.1, 0.2, 0.4')
  const [reviewer, setReviewer] = useState('local-researcher')
  const [reviewNote, setReviewNote] = useState('')

  const representativeIds = useMemo(
    () => new Set(activeRun?.report.representative_candidate_ids ?? []),
    [activeRun],
  )
  const focusedCandidate = activeRun?.candidates.find(
    (candidate) => candidate.candidate_id === focusedCandidateId,
  ) ?? null
  const stateMismatchCount = spec.evidence.filter(
    (item) => item.sample_state !== 'unspecified' && item.sample_state !== spec.target_state,
  ).length
  const approvedIds = useMemo(
    () => new Set(reviews.flatMap((review) => review.approved_candidate_ids)),
    [reviews],
  )

  const reportError = (error: unknown, fallback: string) => {
    onMessage('error', error instanceof Error ? error.message : fallback)
  }

  const openRun = async (runId: string) => {
    if (!projectId) return
    const [record, reviewRecords] = await Promise.all([
      api.experimentalRun(projectId, runId),
      api.experimentalReviews(projectId, runId),
    ])
    setActiveRun(record)
    setReviews(reviewRecords)
    setSelectedCandidateIds([])
    setFocusedCandidateId(record.report.representative_candidate_ids[0] ?? record.candidates[0]?.candidate_id ?? '')
  }

  const refresh = async () => {
    const capabilityRecord = await api.experimentalModelingCapabilities()
    setCapabilities(capabilityRecord)
    if (!projectId) {
      setEvidenceArtifacts([])
      setCatalogs([])
      setRuns([])
      setActiveRun(null)
      setReviews([])
      return
    }
    const [evidence, revision, catalogRecords, runRecords] = await Promise.all([
      api.experimentalEvidence(projectId),
      api.experimentalSpec(projectId),
      api.experimentalCatalogs(projectId),
      api.experimentalRuns(projectId),
    ])
    setEvidenceArtifacts(evidence)
    setCatalogs(catalogRecords)
    setRuns(runRecords)
    setSelectedCatalogIds((current) => {
      const available = new Set(catalogRecords.map((item) => item.catalog_id))
      const retained = current.filter((item) => available.has(item))
      return retained.length ? retained : catalogRecords.map((item) => item.catalog_id)
    })
    if (revision) {
      setSpec(revision.spec)
      setSpecRevisionId(revision.spec_revision_id)
      setProviderElements(revision.spec.allowed_elements.join(', '))
      setEvidenceState(revision.spec.target_state)
    } else {
      setSpec(DEFAULT_SPEC)
      setSpecRevisionId('')
    }
    if (runRecords[0]) await openRun(runRecords[0].run_id)
    else {
      setActiveRun(null)
      setReviews([])
    }
  }

  useEffect(() => {
    void refresh().catch((error: unknown) => reportError(error, 'Failed to load experimental modeling.'))
    // Every loaded record is scoped to the active project.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const saveSpec = async () => {
    if (!projectId) return null
    setBusy('spec')
    try {
      const revision = await api.saveExperimentalSpec(projectId, spec)
      setSpec(revision.spec)
      setSpecRevisionId(revision.spec_revision_id)
      onMessage('success', tr('实验约束已保存为不可变版本。', 'Experimental constraints saved as an immutable revision.'))
      return revision
    } catch (error) {
      reportError(error, 'Failed to save experimental constraints.')
      return null
    } finally {
      setBusy(null)
    }
  }

  const addEvidenceToDraft = async () => {
    if (!projectId) return
    setBusy('evidence')
    try {
      let artifactId: string | undefined
      if (evidenceFile) {
        const artifact = await api.addExperimentalEvidence(projectId, evidenceFile)
        artifactId = artifact.evidence_artifact_id
        setEvidenceArtifacts((current) => [
          artifact,
          ...current.filter((item) => item.evidence_artifact_id !== artifact.evidence_artifact_id),
        ])
      }
      const metadata = JSON.parse(evidenceMetadata) as unknown
      if (metadata == null || Array.isArray(metadata) || typeof metadata !== 'object') {
        throw new Error('Evidence metadata must be a JSON object.')
      }
      const evidence: ExperimentalEvidenceInput = {
        evidence_id: `${evidenceKind}-${Date.now().toString(36)}`,
        kind: evidenceKind,
        sample_state: evidenceState,
        role: evidenceRole,
        metadata: metadata as Record<string, unknown>,
        ...(artifactId ? { evidence_artifact_id: artifactId } : {}),
        note: evidenceNote || evidenceFile?.name || '',
      }
      setSpec((current) => ({ ...current, evidence: [...current.evidence, evidence] }))
      setEvidenceNote('')
      setEvidenceMetadata('{}')
      setEvidenceFile(null)
      onMessage('neutral', tr('证据已加入草稿；保存约束后才会形成版本。', 'Evidence added to the draft; save constraints to create a revision.'))
    } catch (error) {
      reportError(error, 'Failed to add evidence.')
    } finally {
      setBusy(null)
    }
  }

  const addConstraint = () => {
    const minimum = Number(constraintMinimum)
    const maximum = Number(constraintMaximum)
    if (!constraintElement.trim() || !Number.isFinite(minimum) || !Number.isFinite(maximum)) {
      onMessage('error', tr('请输入有效的元素和原子分数区间。', 'Enter a valid element and atomic-fraction interval.'))
      return
    }
    setSpec((current) => ({
      ...current,
      composition_constraints: [
        ...current.composition_constraints.filter(
          (item) => item.element.toLowerCase() !== constraintElement.trim().toLowerCase(),
        ),
        {
          element: constraintElement.trim(),
          minimum_atomic_fraction: minimum,
          maximum_atomic_fraction: maximum,
          scope: constraintScope,
          evidence_ids: current.evidence
            .filter((item) => item.kind === 'icp' || item.kind === 'eds')
            .map((item) => item.evidence_id),
        },
      ],
    }))
  }

  const fetchOptimade = async () => {
    if (!projectId) return
    setBusy('optimade')
    try {
      const catalog = await api.fetchOptimadeCatalog(projectId, {
        base_url: optimadeUrl,
        provider_id: optimadeProvider,
        required_elements: parseElements(providerElements),
        maximum_results: Number(providerMaximumResults),
        maximum_pages: 5,
      })
      setCatalogs((current) => [catalog, ...current])
      setSelectedCatalogIds((current) => [...new Set([...current, catalog.catalog_id])])
      onMessage('success', tr('OPTIMADE 快照已写入当前项目。', 'OPTIMADE snapshot added to the project.'))
    } catch (error) {
      reportError(error, 'OPTIMADE search failed.')
    } finally {
      setBusy(null)
    }
  }

  const fetchMaterialsProject = async () => {
    if (!projectId) return
    setBusy('materials-project')
    try {
      const catalog = await api.fetchMaterialsProjectCatalog(projectId, {
        required_elements: parseElements(providerElements),
        maximum_results: Number(providerMaximumResults),
      })
      setCatalogs((current) => [catalog, ...current])
      setSelectedCatalogIds((current) => [...new Set([...current, catalog.catalog_id])])
      onMessage('success', tr('Materials Project 快照已写入当前项目。', 'Materials Project snapshot added to the project.'))
    } catch (error) {
      reportError(error, 'Materials Project search failed.')
    } finally {
      setBusy(null)
    }
  }

  const runInference = async () => {
    if (!projectId) return
    setBusy('inference')
    try {
      const revision = await api.saveExperimentalSpec(projectId, spec)
      setSpecRevisionId(revision.spec_revision_id)
      const record = await api.createExperimentalRun(projectId, {
        planner_kind: plannerKind,
        catalog_ids: selectedCatalogIds,
        maximum_representatives: Number(maximumRepresentatives),
        xrd_settings: {
          ...xrdSettings,
          shift_values_degrees: parseNumberList(shiftGridText),
          fwhm_values_degrees: parseNumberList(fwhmGridText),
        },
      })
      setActiveRun(record)
      setReviews([])
      setSelectedCandidateIds([])
      setFocusedCandidateId(record.report.representative_candidate_ids[0] ?? '')
      const runRecords = await api.experimentalRuns(projectId)
      setRuns(runRecords)
      onMessage('success', tr('候选推断完成；结果仍需人工审核。', 'Candidate inference completed; human review is still required.'))
    } catch (error) {
      reportError(error, 'Experimental-model inference failed.')
    } finally {
      setBusy(null)
    }
  }

  const reviewCandidates = async () => {
    if (!projectId || !activeRun) return
    setBusy('review')
    try {
      const record = await api.reviewExperimentalCandidates(projectId, activeRun.run_id, {
        approved_candidate_ids: selectedCandidateIds,
        reviewer,
        note: reviewNote,
      })
      setReviews((current) => [...current, record])
      setReviewNote('')
      onMessage('success', tr('候选审核已追加记录。', 'Candidate review appended to the audit trail.'))
    } catch (error) {
      reportError(error, 'Candidate review failed.')
    } finally {
      setBusy(null)
    }
  }

  const materializeCandidates = async () => {
    if (!projectId || !activeRun) return
    setBusy('materialize')
    try {
      await api.materializeExperimentalCandidates(projectId, activeRun.run_id, {
        candidate_ids: selectedCandidateIds,
        confirm_report_sha256: activeRun.report.identity_sha256,
        approved_write: true,
      })
      await onArtifactsChanged()
      const record = await api.experimentalRun(projectId, activeRun.run_id)
      setActiveRun(record)
      setRuns(await api.experimentalRuns(projectId))
      onMessage('success', tr('已审核候选已写入项目结构库。', 'Approved candidates materialized into project structures.'))
    } catch (error) {
      reportError(error, 'Candidate materialization failed.')
    } finally {
      setBusy(null)
    }
  }

  if (!projectId) {
    return (
      <section className="empty-workspace experimental-empty">
        <Beaker size={34} />
        <h2>{tr('先创建或打开项目', 'Open a project first')}</h2>
        <p>{tr('实验证据、数据库快照和候选结构都必须绑定到一个项目。', 'Evidence, catalog snapshots, and candidate models must belong to a project.')}</p>
      </section>
    )
  }

  return (
    <section className="experimental-workbench">
      <div className="section-heading experimental-heading">
        <div>
          <span className="eyebrow">EXPERIMENT → REPRESENTATIVE MODELS</span>
          <h2>{tr('实验约束建模', 'Experiment-informed modeling')}</h2>
          <p>{tr('生成可审计的代表性候选，不声称复刻唯一真实原子结构。', 'Generate auditable representative hypotheses without claiming a unique real atomic structure.')}</p>
        </div>
        <button className="secondary-button" disabled={busy !== null} onClick={() => void refresh()} type="button">
          <RefreshCw size={15} /> {tr('刷新', 'Refresh')}
        </button>
      </div>

      <div className="experimental-capability-row">
        <span className="capability-chip available"><ShieldCheck size={13} /> {tr('规则规划器可用', 'Rule planner ready')}</span>
        <span className={`capability-chip ${capabilities?.providers.materials_project.available ? 'available' : 'muted'}`}>
          <Database size={13} /> MP {capabilities?.providers.materials_project.available ? tr('可用', 'ready') : tr('未配置', 'not configured')}
        </span>
        <span className={`capability-chip ${capabilities?.gpt_planner.available ? 'available' : 'muted'}`}>
          <Sparkles size={13} /> GPT {capabilities?.gpt_planner.available ? capabilities.gpt_planner.model : tr('可选 / 未配置', 'optional / not configured')}
        </span>
        <span className="capability-chip muted">{tr('密钥不会保存到项目', 'Credentials are never persisted')}</span>
      </div>

      <ol className="experimental-stepper">
        {[
          tr('样品状态', 'Sample state'),
          tr('表征证据', 'Evidence'),
          tr('母体结构', 'Parent structures'),
          tr('推断', 'Inference'),
          tr('审核与写入', 'Review & materialize'),
        ].map((label, index) => <li key={label}><span>{index + 1}</span>{label}</li>)}
      </ol>

      <div className="experimental-grid">
        <article className="experimental-card">
          <div className="card-heading">
            <div><span className="eyebrow">SAMPLE LIFECYCLE</span><h3>{tr('目标样品状态', 'Target sample state')}</h3></div>
            <Beaker size={18} />
          </div>
          <div className="experimental-form-grid">
            <label>{tr('样品 ID', 'Sample ID')}<input value={spec.sample_id} onChange={(event) => setSpec((current) => ({ ...current, sample_id: event.target.value }))} /></label>
            <label>{tr('目标状态', 'Target state')}<select value={spec.target_state} onChange={(event) => setSpec((current) => ({ ...current, target_state: event.target.value as ExperimentalSampleState }))}>{SAMPLE_STATES.map((item) => <option key={item}>{item}</option>)}</select></label>
            <label>{tr('材料包', 'Material pack')}<select value={spec.material_pack} onChange={(event) => setSpec((current) => ({ ...current, material_pack: event.target.value }))}><option value="generic">generic</option><option value="alloy-electrocatalyst">alloy-electrocatalyst</option></select></label>
            <label>{tr('允许元素', 'Allowed elements')}<input value={spec.allowed_elements.join(', ')} onChange={(event) => setSpec((current) => ({ ...current, allowed_elements: parseElements(event.target.value) }))} /></label>
            <label>{tr('排除元素', 'Excluded elements')}<input value={spec.excluded_elements.join(', ')} onChange={(event) => setSpec((current) => ({ ...current, excluded_elements: parseElements(event.target.value) }))} placeholder="Na, Cl" /></label>
          </div>
          {stateMismatchCount > 0 && <div className="experimental-warning"><TriangleAlert size={15} /> {tr(`${stateMismatchCount} 条证据来自其他样品状态；推断时将保留这一差异。`, `${stateMismatchCount} evidence record(s) belong to another sample state; the mismatch remains explicit.`)}</div>}
          <button className="secondary-button accent" disabled={busy !== null} onClick={() => void saveSpec()} type="button">
            {busy === 'spec' ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
            {tr('保存约束版本', 'Save constraint revision')}
          </button>
          {specRevisionId && <code className="experimental-revision">{specRevisionId}</code>}
        </article>

        <article className="experimental-card experimental-card-wide">
          <div className="card-heading">
            <div><span className="eyebrow">EVIDENCE REGISTER</span><h3>{tr('表征证据与成分区间', 'Characterization evidence and composition')}</h3></div>
            <FileUp size={18} />
          </div>
          <div className="experimental-evidence-composer">
            <label>{tr('类型', 'Kind')}<select value={evidenceKind} onChange={(event) => setEvidenceKind(event.target.value as ExperimentalEvidenceKind)}>{EVIDENCE_KINDS.map((item) => <option key={item}>{item}</option>)}</select></label>
            <label>{tr('测量状态', 'Measured state')}<select value={evidenceState} onChange={(event) => setEvidenceState(event.target.value as ExperimentalSampleState)}>{SAMPLE_STATES.map((item) => <option key={item}>{item}</option>)}</select></label>
            <label>{tr('约束等级', 'Constraint role')}<select value={evidenceRole} onChange={(event) => setEvidenceRole(event.target.value as 'hard' | 'soft' | 'context')}><option value="hard">hard</option><option value="soft">soft</option><option value="context">context</option></select></label>
            <label className="file-field"><span>{tr('原始文件（可选）', 'Raw file (optional)')}</span><input onChange={(event) => setEvidenceFile(event.target.files?.[0] ?? null)} type="file" /></label>
            <label className="wide">{tr('简短结论 / 仪器信息', 'Summary / instrument details')}<input value={evidenceNote} onChange={(event) => setEvidenceNote(event.target.value)} placeholder={tr('例如：Cu Kα；活化后出现宽峰', 'e.g. Cu Kα; broad peak after activation')} /></label>
            <label className="wide">{tr('结构化元数据 JSON', 'Structured metadata JSON')}<textarea className="mono-input" rows={3} value={evidenceMetadata} onChange={(event) => setEvidenceMetadata(event.target.value)} /></label>
            <button className="secondary-button" disabled={busy !== null} onClick={() => void addEvidenceToDraft()} type="button"><Plus size={15} /> {tr('加入证据草稿', 'Add evidence to draft')}</button>
          </div>

          <div className="experimental-evidence-list">
            {spec.evidence.map((item) => (
              <div className={item.sample_state !== 'unspecified' && item.sample_state !== spec.target_state ? 'mismatch' : ''} key={item.evidence_id}>
                <span className={`evidence-role role-${item.role}`}>{item.role}</span>
                <strong>{item.kind.toUpperCase()}</strong>
                <span>{item.sample_state}</span>
                <span>{item.note || tr('无备注', 'No note')}</span>
                {item.evidence_artifact_id && <code>{item.evidence_artifact_id}</code>}
                <button aria-label="Remove evidence" onClick={() => setSpec((current) => ({ ...current, evidence: current.evidence.filter((record) => record.evidence_id !== item.evidence_id) }))} type="button"><Trash2 size={14} /></button>
              </div>
            ))}
            {!spec.evidence.length && <p className="panel-empty">{tr('尚未加入证据。XRD 不是强制条件，但缺少时只能给出较低层级的候选结论。', 'No evidence yet. XRD is not mandatory, but without it the claim ceiling remains low.')}</p>}
          </div>

          <div className="experimental-constraint-composer">
            <label>{tr('元素', 'Element')}<input value={constraintElement} onChange={(event) => setConstraintElement(event.target.value)} /></label>
            <label>{tr('最小原子分数', 'Minimum atomic fraction')}<input min="0" max="1" step="0.01" type="number" value={constraintMinimum} onChange={(event) => setConstraintMinimum(event.target.value)} /></label>
            <label>{tr('最大原子分数', 'Maximum atomic fraction')}<input min="0" max="1" step="0.01" type="number" value={constraintMaximum} onChange={(event) => setConstraintMaximum(event.target.value)} /></label>
            <label>{tr('空间范围', 'Scope')}<select value={constraintScope} onChange={(event) => setConstraintScope(event.target.value as ExperimentalCompositionConstraint['scope'])}><option value="bulk">bulk</option><option value="surface">surface</option><option value="local">local</option><option value="unspecified">unspecified</option></select></label>
            <button className="secondary-button" onClick={addConstraint} type="button"><Plus size={15} /> {tr('添加区间', 'Add interval')}</button>
          </div>
          <div className="experimental-constraint-list">
            {spec.composition_constraints.map((item) => (
              <span key={`${item.element}-${item.scope}`}>{item.element} · {item.minimum_atomic_fraction.toFixed(2)}–{item.maximum_atomic_fraction.toFixed(2)} · {item.scope}<button onClick={() => setSpec((current) => ({ ...current, composition_constraints: current.composition_constraints.filter((record) => record !== item) }))} type="button">×</button></span>
            ))}
          </div>
        </article>

        <article className="experimental-card experimental-card-wide">
          <div className="card-heading">
            <div><span className="eyebrow">PARENT STRUCTURES</span><h3>{tr('项目结构与数据库快照', 'Project structures and database snapshots')}</h3></div>
            <Database size={18} />
          </div>
          <div className="experimental-provider-summary">
            <div><Atom size={18} /><span><strong>{artifacts.length}</strong>{tr('个项目结构', 'project structures')}</span><button onClick={onOpenStructures} type="button">{tr('管理', 'Manage')}</button></div>
            <div><Layers3 size={18} /><span><strong>{catalogs.length}</strong>{tr('个不可变快照', 'immutable snapshots')}</span></div>
            <div><FileUp size={18} /><span><strong>{evidenceArtifacts.length}</strong>{tr('个原始证据文件', 'raw evidence files')}</span></div>
          </div>
          <div className="experimental-provider-grid">
            <section>
              <h4>OPTIMADE</h4>
              <label>{tr('HTTPS 端点', 'HTTPS endpoint')}<input placeholder="https://provider.example" value={optimadeUrl} onChange={(event) => setOptimadeUrl(event.target.value)} /></label>
              <label>{tr('来源标签', 'Provider label')}<input value={optimadeProvider} onChange={(event) => setOptimadeProvider(event.target.value)} /></label>
              <label>{tr('必须包含元素', 'Required elements')}<input value={providerElements} onChange={(event) => setProviderElements(event.target.value)} /></label>
              <button className="secondary-button" disabled={busy !== null || !optimadeUrl.trim()} onClick={() => void fetchOptimade()} type="button">{busy === 'optimade' ? <LoaderCircle className="spin" size={15} /> : <Search size={15} />}{tr('显式联网检索', 'Explicit network search')}</button>
            </section>
            <section>
              <h4>Materials Project</h4>
              <p>{tr('提供稳定性元数据和数据库版本。API key 仅由后端环境变量读取。', 'Adds stability metadata and database version. The key is read only from the backend environment.')}</p>
              <label>{tr('最大结果数', 'Maximum results')}<input min="1" max="1000" type="number" value={providerMaximumResults} onChange={(event) => setProviderMaximumResults(event.target.value)} /></label>
              <button className="secondary-button accent" disabled={busy !== null || !capabilities?.providers.materials_project.available} onClick={() => void fetchMaterialsProject()} type="button">{busy === 'materials-project' ? <LoaderCircle className="spin" size={15} /> : <Database size={15} />}{tr('获取 MP 快照', 'Fetch MP snapshot')}</button>
              {!capabilities?.providers.materials_project.available && <small>{capabilities?.providers.materials_project.client_installed ? tr('后端未检测到 MP_API_KEY。', 'MP_API_KEY was not detected by the backend.') : tr('需要安装 mp-api 并配置 MP_API_KEY。', 'Install mp-api and configure MP_API_KEY.')}</small>}
            </section>
          </div>
          <div className="experimental-catalog-list">
            {catalogs.map((catalog) => (
              <label key={catalog.catalog_id}>
                <input checked={selectedCatalogIds.includes(catalog.catalog_id)} onChange={() => setSelectedCatalogIds((current) => current.includes(catalog.catalog_id) ? current.filter((item) => item !== catalog.catalog_id) : [...current, catalog.catalog_id])} type="checkbox" />
                <span><strong>{catalog.display_provider_id}</strong><small>{catalog.provider_kind} · {catalog.reference_count} structures · {catalog.created_at_utc}</small></span>
                <code>{catalog.catalog_id}</code>
              </label>
            ))}
          </div>
        </article>

        <article className="experimental-card">
          <div className="card-heading"><div><span className="eyebrow">INFERENCE SETTINGS</span><h3>{tr('候选推断', 'Candidate inference')}</h3></div><Play size={18} /></div>
          <div className="experimental-form-grid">
            <label>{tr('规划器', 'Planner')}<select value={plannerKind} onChange={(event) => setPlannerKind(event.target.value as 'rule' | 'gpt')}><option value="rule">rule · local</option><option disabled={!capabilities?.gpt_planner.available} value="gpt">gpt · {capabilities?.gpt_planner.model}</option></select></label>
            <label>{tr('代表性模型上限', 'Representative limit')}<input min="1" max="50" type="number" value={maximumRepresentatives} onChange={(event) => setMaximumRepresentatives(event.target.value)} /></label>
          </div>
          <details className="experimental-advanced">
            <summary>{tr('高级 XRD nuisance 参数', 'Advanced XRD nuisance settings')}</summary>
            <label>{tr('波长', 'Wavelength')}<input value={xrdSettings.wavelength} onChange={(event) => setXrdSettings((current) => ({ ...current, wavelength: event.target.value }))} /></label>
            <label>{tr('零点漂移网格（度）', 'Shift grid (degrees)')}<input value={shiftGridText} onChange={(event) => setShiftGridText(event.target.value)} /></label>
            <label>{tr('FWHM 网格（度）', 'FWHM grid (degrees)')}<input value={fwhmGridText} onChange={(event) => setFwhmGridText(event.target.value)} /></label>
            <label>{tr('支持阈值', 'Support threshold')}<input min="0" max="1" step="0.01" type="number" value={xrdSettings.minimum_supported_score} onChange={(event) => setXrdSettings((current) => ({ ...current, minimum_supported_score: Number(event.target.value) }))} /></label>
          </details>
          <button className="primary-button experimental-run-button" disabled={busy !== null || (!artifacts.length && !selectedCatalogIds.length)} onClick={() => void runInference()} type="button">{busy === 'inference' ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}{tr('保存并运行推断', 'Save and run inference')}</button>
          <small>{tr('运行会写入不可变报告和候选文件，但不会写入项目结构库。', 'A run stores an immutable report and candidate files, but does not add project structures.')}</small>
        </article>

        <article className="experimental-card">
          <div className="card-heading"><div><span className="eyebrow">RUN HISTORY</span><h3>{tr('推断记录', 'Inference runs')}</h3></div><RefreshCw size={18} /></div>
          <div className="experimental-run-list">
            {runs.map((run) => (
              <button className={activeRun?.run_id === run.run_id ? 'active' : ''} disabled={busy !== null} key={run.run_id} onClick={() => void openRun(run.run_id).catch((error) => reportError(error, 'Failed to open run.'))} type="button">
                <span className={`run-state state-${run.status}`} />
                <span><strong>{run.status}</strong><small>{run.planner_kind} · {run.representative_count}/{run.candidate_count} representatives</small></span>
                <code>{shortHash(run.report_sha256)}</code>
              </button>
            ))}
            {!runs.length && <p className="panel-empty">{tr('尚无推断记录。', 'No inference runs yet.')}</p>}
          </div>
        </article>
      </div>

      {activeRun && (
        <section className="experimental-results">
          <div className="section-heading">
            <div><span className="eyebrow">HYPOTHESIS SET · NOT UNIQUE TRUTH</span><h2>{tr('候选结果与审核', 'Candidate results and review')}</h2><p>{activeRun.report.claim_interpretation}</p></div>
            <code>{activeRun.run_id}</code>
          </div>
          <div className="experimental-metrics">
            <div><span>{tr('状态', 'Status')}</span><strong>{activeRun.report.status}</strong></div>
            <div><span>{tr('结论上限', 'Claim ceiling')}</span><strong>{activeRun.report.claim_ceiling}</strong></div>
            <div><span>{tr('XRD 最佳证据分数', 'Best XRD evidence score')}</span><strong>{formatScore(activeRun.report.phase_search?.best_score)}</strong></div>
            <div><span>{tr('代表性候选', 'Representatives')}</span><strong>{representativeIds.size}</strong></div>
          </div>

          <XrdComparisonPlot run={activeRun} />

          <div className="experimental-result-grid">
            <article className="experimental-result-card">
              <h3>{tr('相假设排名', 'Ranked phase hypotheses')}</h3>
              <div className="experimental-phase-table">
                {activeRun.report.phase_search?.single_phase_matches.slice(0, 8).map((match) => (
                  <div key={match.reference_key}><strong>{match.formula}</strong><span>{formatScore(match.evidence_score)}</span><small>{(match.explained_intensity_fraction * 100).toFixed(1)}% explained · shift {match.shift_degrees.toFixed(2)}°</small></div>
                ))}
                {!activeRun.report.phase_search && <p>{tr('没有可用于相族判断的 XRD/GIXRD 文件。', 'No XRD/GIXRD file was available for phase-family support.')}</p>}
              </div>
            </article>
            <article className="experimental-result-card">
              <h3>{tr('仍未解决的问题', 'Remaining ambiguity')}</h3>
              <ul>{activeRun.report.ambiguity_reasons.map((item) => <li key={item}>{item}</li>)}</ul>
              <h4>{tr('建议的下一项低成本实验', 'Suggested next low-cost experiments')}</h4>
              <ul>{activeRun.report.recommended_next_experiments.map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
          </div>

          <div className="experimental-candidate-layout">
            <div className="experimental-candidate-list">
              {activeRun.candidates.map((candidate) => {
                const representative = representativeIds.has(candidate.candidate_id)
                const selected = selectedCandidateIds.includes(candidate.candidate_id)
                return (
                  <article className={`${focusedCandidateId === candidate.candidate_id ? 'focused' : ''} ${!candidate.assessment.valid ? 'invalid' : ''}`} key={candidate.candidate_id}>
                    <label>
                      <input checked={selected} disabled={!representative || !candidate.assessment.valid} onChange={() => setSelectedCandidateIds((current) => current.includes(candidate.candidate_id) ? current.filter((item) => item !== candidate.candidate_id) : [...current, candidate.candidate_id])} type="checkbox" />
                      <span>{representative ? tr('代表性候选', 'Representative') : tr('非代表候选', 'Non-representative')}</span>
                    </label>
                    <button onClick={() => setFocusedCandidateId(candidate.candidate_id)} type="button">
                      <strong>{candidate.assessment.formula}</strong>
                      <span>{candidate.assessment.model_kind} · {candidate.assessment.num_sites} sites</span>
                      <small>score {formatScore(candidate.assessment.evidence_score)} · {candidate.assessment.parent_reference_key}</small>
                      <code>{candidate.candidate_id}</code>
                    </button>
                  </article>
                )
              })}
            </div>
            <article className="experimental-candidate-viewer">
              <div className="card-heading"><div><span className="eyebrow">CANDIDATE PREVIEW</span><h3>{focusedCandidate?.assessment.formula ?? tr('选择候选', 'Select a candidate')}</h3></div><Atom size={18} /></div>
              <StructureViewer structure={focusedCandidate?.viewer ?? null} />
              {focusedCandidate && <div className="experimental-provenance"><span>{tr('母体', 'Parent')}</span><code>{focusedCandidate.assessment.parent_reference_key}</code><span>{tr('结构哈希', 'Structure hash')}</span><code>{shortHash(focusedCandidate.assessment.structure_sha256)}</code></div>}
            </article>
          </div>

          <div className="experimental-review-grid">
            <article className="experimental-card">
              <div className="card-heading"><div><span className="eyebrow">SCIENTIFIC REVIEW GATE</span><h3>{tr('审核所选候选', 'Review selected candidates')}</h3></div><CheckCircle2 size={18} /></div>
              <label>{tr('审核者', 'Reviewer')}<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
              <label>{tr('审核依据', 'Review rationale')}<textarea rows={3} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder={tr('说明为何这些模型足以代表当前实验假设。', 'Explain why these models represent the current evidence.')}/></label>
              <button className="secondary-button accent" disabled={busy !== null || !selectedCandidateIds.length || !reviewNote.trim()} onClick={() => void reviewCandidates()} type="button">{busy === 'review' ? <LoaderCircle className="spin" size={15} /> : <CheckCircle2 size={15} />}{tr('追加审核记录', 'Append review')}</button>
              <div className="experimental-review-log">{reviews.map((review) => <div key={review.review_id}><strong>{review.reviewer}</strong><span>{review.approved_candidate_ids.join(', ')}</span><small>{review.note} · {review.reviewed_at_utc}</small></div>)}</div>
            </article>
            <article className="experimental-card materialization-card">
              <div className="card-heading"><div><span className="eyebrow">EXPLICIT PROJECT WRITE</span><h3>{tr('写入项目结构库', 'Materialize project structures')}</h3></div><Save size={18} /></div>
              <p>{tr('只写入已审核且当前仍被选中的候选。后续仍需使用 CatEx 的结构审核门。', 'Only selected, reviewed candidates are written. They still pass through the normal CatEx structure review gate.')}</p>
              <code>{shortHash(activeRun.report.identity_sha256)}</code>
              <button className="primary-button" disabled={busy !== null || !selectedCandidateIds.length || selectedCandidateIds.some((item) => !approvedIds.has(item))} onClick={() => void materializeCandidates()} type="button">{busy === 'materialize' ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}{tr('确认并写入所选结构', 'Confirm and materialize selected')}</button>
              {activeRun.materialized && <span className="success-chip"><CheckCircle2 size={13} /> {tr('该 run 已执行过 materialization', 'This run has been materialized')}</span>}
            </article>
          </div>
        </section>
      )}
    </section>
  )
}
