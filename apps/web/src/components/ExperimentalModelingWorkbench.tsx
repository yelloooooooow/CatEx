import {
  Atom,
  Beaker,
  CheckCircle2,
  Database,
  FileUp,
  KeyRound,
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

const SAMPLE_STATE_LABELS: Record<
  ExperimentalSampleState,
  { chinese: string; english: string }
> = {
  as_prepared: { chinese: '制备后（未进行电化学活化）', english: 'As prepared (before electrochemical activation)' },
  activated: { chinese: '活化后', english: 'Activated (after electrochemical activation)' },
  operando_approximation: { chinese: '接近工作态', english: 'Working-state approximation' },
  post_mortem: { chinese: '反应后', english: 'Post-reaction' },
  unspecified: { chinese: '未注明 / 不确定', english: 'Not specified / uncertain' },
}

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

const EVIDENCE_KIND_LABELS: Record<
  ExperimentalEvidenceKind,
  { chinese: string; english: string }
> = {
  xrd: { chinese: 'XRD', english: 'XRD' },
  gixrd: { chinese: 'GIXRD', english: 'GIXRD' },
  icp: { chinese: 'ICP', english: 'ICP' },
  eds: { chinese: 'EDS', english: 'EDS' },
  xps: { chinese: 'XPS', english: 'XPS' },
  tem: { chinese: 'TEM', english: 'TEM' },
  sem: { chinese: 'SEM', english: 'SEM' },
  raman: { chinese: '拉曼光谱', english: 'Raman spectroscopy' },
  synthesis: { chinese: '制备信息', english: 'Synthesis details' },
  electrochemistry: { chinese: '电化学数据', english: 'Electrochemistry' },
  literature: { chinese: '文献依据', english: 'Literature reference' },
  other: { chinese: '其他', english: 'Other' },
}

const EVIDENCE_ROLE_LABELS = {
  hard: { chinese: '必须符合', english: 'Must match' },
  soft: { chinese: '用于排序', english: 'Use for ranking' },
  context: { chinese: '仅作参考', english: 'Reference only' },
} as const

const COMPOSITION_SCOPE_LABELS: Record<
  ExperimentalCompositionConstraint['scope'],
  { chinese: string; english: string }
> = {
  bulk: { chinese: '体相（ICP）', english: 'Bulk (ICP)' },
  surface: { chinese: '表面（XPS）', english: 'Surface (XPS)' },
  local: { chinese: '局部（EDS/TEM）', english: 'Local (EDS/TEM)' },
  unspecified: { chinese: '未注明', english: 'Not specified' },
}

const RUN_STATUS_LABELS: Record<string, { chinese: string; english: string }> = {
  ready_for_review: { chinese: '可以确认', english: 'Ready to review' },
  insufficient_evidence: { chinese: '信息不足', english: 'More evidence needed' },
  no_valid_candidates: { chinese: '没有可用候选', english: 'No valid candidates' },
  error: { chinese: '运行失败', english: 'Failed' },
}

const CLAIM_LEVEL_LABELS: Record<string, { chinese: string; english: string }> = {
  no_atomic_claim: { chinese: '不能支持原子结构判断', english: 'No atomistic claim' },
  candidate_only: { chinese: '仅支持候选模型', english: 'Candidate models only' },
  phase_family_supported: { chinese: '支持相类型判断', english: 'Phase family supported' },
  structural_variant_supported: { chinese: '支持结构变体判断', english: 'Structural variant supported' },
}

const MODEL_KIND_LABELS: Record<string, { chinese: string; english: string }> = {
  bulk: { chinese: '体相模型', english: 'Bulk model' },
  surface: { chinese: '表面模型', english: 'Surface model' },
}

const SCIENTIFIC_MESSAGE_LABELS: Record<string, string> = {
  'Multiple phase combinations lie within the configured XRD ambiguity margin.': '有多组物相组合的 XRD 匹配度接近，暂时无法区分。',
  'The local reference library does not explain the diffraction pattern strongly enough.': '当前参考结构不足以解释 XRD 图谱。',
  'At least one evidence-supported hypothesis lacks a defensible atomic realization.': '至少有一种受表征支持的假设还没有可用的原子结构模型。',
  'Add ICP-OES or quantified EDS with uncertainty to constrain bulk composition.': '补充带不确定度的 ICP-OES 或定量 EDS，以限定体相成分。',
  'Add laboratory XRD/GIXRD with wavelength, scan range, substrate, and geometry metadata.': '补充实验室 XRD/GIXRD，并记录波长、扫描范围、基底和测试几何。',
  'Acquire a longer-count or geometry-adjusted XRD/GIXRD scan before adding a costly method.': '在增加昂贵表征前，可先延长 XRD/GIXRD 采集时间或调整测试几何。',
  'Add state-resolved XPS to test surface oxidation/hydroxylation hypotheses.': '补充对应样品阶段的 XPS，以判断表面氧化或羟基化。',
  'Add targeted TEM/SAED lattice-spacing and crystallite-size evidence for leading phases.': '针对主要候选相补充 TEM/SAED 晶面间距和晶粒尺寸。',
  'Measure XPS before and after activation, and compare with Raman if oxide families remain ambiguous.': '比较活化前后的 XPS；若氧化物类型仍不明确，再结合拉曼光谱。',
  'Treat disorder as a motif ensemble; use total scattering/PDF only if candidate-dependent DFT conclusions remain different.': '将无序结构表示为局部构型集合；只有当不同候选导致不同 DFT 结论时，再考虑总散射/PDF。',
}

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

function formatTimestamp(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function localizedRecord(
  record: Record<string, { chinese: string; english: string }>,
  key: string,
  tr: (chinese: string, english: string) => string,
): string {
  const label = record[key]
  return label ? tr(label.chinese, label.english) : key.replaceAll('_', ' ')
}

function localizedScientificMessage(
  value: string,
  tr: (chinese: string, english: string) => string,
): string {
  return tr(SCIENTIFIC_MESSAGE_LABELS[value] ?? value, value)
}

function vectorLength(vector: number[]): number {
  return Math.hypot(...vector)
}

function latticeParameters(lattice: number[][]): { a: number; b: number; c: number } {
  return {
    a: vectorLength(lattice[0] ?? []),
    b: vectorLength(lattice[1] ?? []),
    c: vectorLength(lattice[2] ?? []),
  }
}

interface CredentialEditorProps {
  provider: 'materials_project' | 'openai'
  source: 'environment' | 'system_keyring' | null
  savedToSystem: boolean
  storeAvailable: boolean
  busy: boolean
  onSave: (provider: 'materials_project' | 'openai', secret: string) => Promise<void>
  onDelete: (provider: 'materials_project' | 'openai') => Promise<void>
}

function CredentialEditor({
  provider,
  source,
  savedToSystem,
  storeAvailable,
  busy,
  onSave,
  onDelete,
}: CredentialEditorProps) {
  const { tr } = useI18n()
  const [secret, setSecret] = useState('')
  const label = provider === 'materials_project'
    ? tr('Materials Project API 密钥', 'Materials Project API key')
    : tr('OpenAI API 密钥', 'OpenAI API key')

  const save = async () => {
    const submittedSecret = secret
    setSecret('')
    await onSave(provider, submittedSecret)
  }

  return (
    <form
      className="experimental-credential-editor"
      onSubmit={(event) => {
        event.preventDefault()
        void save()
      }}
    >
      <div className="credential-status-line">
        <KeyRound size={15} />
        <span>
          <strong>{source ? tr('已连接', 'Connected') : tr('未连接', 'Not connected')}</strong>
          <small>
            {source === 'system_keyring'
              ? tr('安全保存在本机系统密钥库', 'Securely stored in the system keyring')
              : source === 'environment'
                ? tr('当前由环境变量提供', 'Currently provided by an environment variable')
                : storeAvailable
                  ? tr('保存前会先联网验证', 'The key is verified before it is saved')
                  : tr('未检测到受支持的系统密钥库', 'No supported system keyring was detected')}
          </small>
        </span>
      </div>
      <input
        aria-hidden="true"
        autoComplete="username"
        name={`catex-${provider}-account`}
        readOnly
        tabIndex={-1}
        type="text"
        value={provider}
        hidden
      />
      <label>
        {label}
        <input
          aria-label={label}
          autoCapitalize="none"
          autoComplete="new-password"
          disabled={busy || !storeAvailable}
          name={`catex-${provider}-credential`}
          onChange={(event) => setSecret(event.target.value)}
          placeholder={tr('输入后安全保存到本机', 'Enter and save securely on this computer')}
          spellCheck={false}
          type="password"
          value={secret}
        />
      </label>
      <div className="credential-actions">
        <button
          className="secondary-button accent"
          disabled={busy || !storeAvailable || secret.trim().length < 8}
          type="submit"
        >
          {busy ? <LoaderCircle className="spin" size={14} /> : <ShieldCheck size={14} />}
          {tr('验证并安全保存', 'Verify and save securely')}
        </button>
        {savedToSystem && (
          <button
            className="secondary-button danger"
            disabled={busy}
            onClick={() => void onDelete(provider)}
            type="button"
          >
            <Trash2 size={14} /> {tr('从本机清除', 'Remove from this computer')}
          </button>
        )}
      </div>
      <small>
        {tr(
          '密钥不会进入项目、导出文件、浏览器存储或 Git。',
          'The key is never written to projects, exports, browser storage, or Git.',
        )}
      </small>
    </form>
  )
}

function XrdComparisonPlot({ run }: { run: ExperimentalModelingRun }) {
  const { tr } = useI18n()
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
        <span className="observed">{tr('实验曲线', 'Measured')}</span>
        <span className="fitted">{tr('模拟曲线', 'Simulated')} · {plot.label}</span>
        <span className="residual">{tr('差值', 'Difference')}</span>
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
  const [focusedAtomIndex1Based, setFocusedAtomIndex1Based] = useState<number | null>(null)
  const [showAtomIndices, setShowAtomIndices] = useState(false)

  const [evidenceKind, setEvidenceKind] = useState<ExperimentalEvidenceKind>('xrd')
  const [evidenceState, setEvidenceState] = useState<ExperimentalSampleState>('activated')
  const [evidenceRole, setEvidenceRole] = useState<'hard' | 'soft' | 'context'>('hard')
  const [evidenceNote, setEvidenceNote] = useState('')
  const [evidenceMetadata, setEvidenceMetadata] = useState('{}')
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null)

  const [constraintElement, setConstraintElement] = useState('Ni')
  const [constraintMinimum, setConstraintMinimum] = useState('45')
  const [constraintMaximum, setConstraintMaximum] = useState('75')
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
  const focusedAtom = focusedCandidate && focusedAtomIndex1Based
    ? {
        index: focusedAtomIndex1Based,
        element: focusedCandidate.viewer.species[focusedAtomIndex1Based - 1],
        fractional: focusedCandidate.viewer.fractional_coordinates[focusedAtomIndex1Based - 1],
        cartesian: focusedCandidate.viewer.cartesian_coordinates[focusedAtomIndex1Based - 1],
      }
    : null
  const focusedElementCounts = focusedCandidate
    ? [...focusedCandidate.viewer.species.reduce((counts, element) => {
        counts.set(element, (counts.get(element) ?? 0) + 1)
        return counts
      }, new Map<string, number>())]
    : []
  const focusedLattice = focusedCandidate
    ? latticeParameters(focusedCandidate.viewer.lattice)
    : null
  const stateMismatchCount = spec.evidence.filter(
    (item) => item.sample_state !== 'unspecified' && item.sample_state !== spec.target_state,
  ).length
  const approvedIds = useMemo(
    () => new Set(reviews.flatMap((review) => review.approved_candidate_ids)),
    [reviews],
  )

  useEffect(() => {
    setFocusedAtomIndex1Based(null)
    setShowAtomIndices(false)
  }, [focusedCandidateId])

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
      onMessage('success', tr('样品与表征信息已保存。', 'Sample and characterization details saved.'))
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
        throw new Error(tr('高级信息必须是有效的 JSON 对象。', 'Advanced metadata must be a valid JSON object.'))
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
      onMessage('neutral', tr('已添加这项表征；保存当前信息后生效。', 'Characterization added; save the current details to apply it.'))
    } catch (error) {
      reportError(error, 'Failed to add evidence.')
    } finally {
      setBusy(null)
    }
  }

  const addConstraint = () => {
    const minimum = Number(constraintMinimum)
    const maximum = Number(constraintMaximum)
    if (
      !constraintElement.trim()
      || !Number.isFinite(minimum)
      || !Number.isFinite(maximum)
      || minimum < 0
      || maximum > 100
      || minimum > maximum
    ) {
      onMessage('error', tr('请输入 0–100 at.% 范围内的有效成分区间。', 'Enter a valid composition interval between 0 and 100 at.%.'))
      return
    }
    setSpec((current) => ({
      ...current,
      composition_constraints: [
        ...current.composition_constraints.filter(
          (item) => !(
            item.element.toLowerCase() === constraintElement.trim().toLowerCase()
            && item.scope === constraintScope
          ),
        ),
        {
          element: constraintElement.trim(),
          minimum_atomic_fraction: minimum / 100,
          maximum_atomic_fraction: maximum / 100,
          scope: constraintScope,
          evidence_ids: current.evidence
            .filter((item) => item.kind === 'icp' || item.kind === 'eds' || item.kind === 'xps')
            .map((item) => item.evidence_id),
        },
      ],
    }))
  }

  const saveCredential = async (
    provider: 'materials_project' | 'openai',
    secret: string,
  ) => {
    setBusy(`credential-${provider}`)
    try {
      const result = await api.saveExperimentalCredential(provider, secret)
      setCapabilities(result.capabilities)
      onMessage(
        'success',
        provider === 'materials_project'
          ? tr(
              'Materials Project 密钥已验证并安全保存到本机系统密钥库。',
              'The Materials Project key was verified and saved in the system keyring.',
            )
          : tr(
              'OpenAI 密钥已验证并安全保存到本机系统密钥库。',
              'The OpenAI key was verified and saved in the system keyring.',
            ),
      )
    } catch (error) {
      reportError(error, 'Credential verification or storage failed.')
    } finally {
      setBusy(null)
    }
  }

  const deleteCredential = async (
    provider: 'materials_project' | 'openai',
  ) => {
    setBusy(`credential-${provider}`)
    try {
      const result = await api.deleteExperimentalCredential(provider)
      setCapabilities(result.capabilities)
      onMessage(
        'success',
        tr(
          '凭据已从本机系统密钥库清除。',
          'The credential was removed from the system keyring.',
        ),
      )
    } catch (error) {
      reportError(error, 'Credential removal failed.')
    } finally {
      setBusy(null)
    }
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
      onMessage('success', tr('OPTIMADE 搜索结果已保存到当前项目。', 'OPTIMADE search results saved to the project.'))
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
      onMessage('success', tr('Materials Project 搜索结果已保存到当前项目。', 'Materials Project search results saved to the project.'))
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
      onMessage('success', tr('候选结构已生成，请比较后选择要保留的模型。', 'Candidates generated. Compare them and select the models to retain.'))
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
      onMessage('success', tr('所选结构的确认记录已保存。', 'Confirmation saved for the selected structures.'))
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
      onMessage('success', tr('所选结构已加入项目结构库。', 'Selected structures added to the project.'))
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
        <p>{tr('样品信息、表征数据和候选结构需要保存在一个项目中。', 'Sample details, characterization data, and candidate structures are saved in a project.')}</p>
      </section>
    )
  }

  return (
    <section className="experimental-workbench">
      <div className="section-heading experimental-heading">
        <div>
          <span className="eyebrow">{tr('实验建模', 'Experimental modeling')}</span>
          <h2>{tr('从表征数据生成候选结构', 'Build candidate structures from measurements')}</h2>
          <p>{tr('添加样品信息和表征结果，生成一组可比较的结构模型；确认后再保存到项目。', 'Add sample details and measurements, compare representative models, then save the structures you confirm.')}</p>
        </div>
        <button className="secondary-button" disabled={busy !== null} onClick={() => void refresh()} type="button">
          <RefreshCw size={15} /> {tr('刷新', 'Refresh')}
        </button>
      </div>

      <div className="experimental-capability-row">
        <span className="capability-chip available"><ShieldCheck size={13} /> {tr('本地生成可用', 'Local generation ready')}</span>
        <span className={`capability-chip ${capabilities?.providers.materials_project.available ? 'available' : 'muted'}`}>
          <Database size={13} /> Materials Project {capabilities?.providers.materials_project.available ? tr('已连接', 'connected') : tr('未连接', 'not connected')}
        </span>
        <span className={`capability-chip ${capabilities?.gpt_planner.available ? 'available' : 'muted'}`}>
          <Sparkles size={13} /> {tr('AI 辅助', 'AI assistance')} {capabilities?.gpt_planner.available ? tr('已连接', 'connected') : tr('未连接（可选）', 'not connected (optional)')}
        </span>
        <span className={`capability-chip ${capabilities?.credential_store.available ? 'available' : 'muted'}`}>
          <KeyRound size={13} />
          {capabilities?.credential_store.available
            ? tr('密钥安全存储可用', 'Secure credential storage ready')
            : tr('密钥安全存储不可用', 'Secure credential storage unavailable')}
        </span>
      </div>

      <ol className="experimental-stepper">
        {[
          tr('填写样品信息', 'Describe sample'),
          tr('添加表征', 'Add measurements'),
          tr('准备参考结构', 'Prepare references'),
          tr('生成候选', 'Generate candidates'),
          tr('确认并保存', 'Review and save'),
        ].map((label, index) => <li key={label}><span>{index + 1}</span>{label}</li>)}
      </ol>

      <div className="experimental-grid">
        <article className="experimental-card">
          <div className="card-heading">
            <div><span className="eyebrow">{tr('第 1 步', 'Step 1')}</span><h3>{tr('样品信息', 'Sample details')}</h3></div>
            <Beaker size={18} />
          </div>
          <div className="experimental-form-grid">
            <label>{tr('样品名称或编号', 'Sample name or ID')}<input value={spec.sample_id} onChange={(event) => setSpec((current) => ({ ...current, sample_id: event.target.value }))} /></label>
            <label>{tr('模型要表示的阶段', 'Stage to represent')}<select value={spec.target_state} onChange={(event) => setSpec((current) => ({ ...current, target_state: event.target.value as ExperimentalSampleState }))}>{SAMPLE_STATES.map((item) => <option key={item} value={item}>{tr(SAMPLE_STATE_LABELS[item].chinese, SAMPLE_STATE_LABELS[item].english)}</option>)}</select></label>
            <label>{tr('材料类型', 'Material type')}<select value={spec.material_pack} onChange={(event) => setSpec((current) => ({ ...current, material_pack: event.target.value }))}><option value="generic">{tr('通用材料', 'General material')}</option><option value="alloy-electrocatalyst">{tr('合金电催化剂', 'Alloy electrocatalyst')}</option></select></label>
            <label>{tr('主要元素', 'Main elements')}<input value={spec.allowed_elements.join(', ')} onChange={(event) => setSpec((current) => ({ ...current, allowed_elements: parseElements(event.target.value) }))} /></label>
            <label>{tr('不应出现的元素（可选）', 'Excluded elements (optional)')}<input value={spec.excluded_elements.join(', ')} onChange={(event) => setSpec((current) => ({ ...current, excluded_elements: parseElements(event.target.value) }))} placeholder="Na, Cl" /></label>
          </div>
          <small className="experimental-field-help">{tr('若不确定样品阶段，可选择“未注明 / 不确定”，仍可继续生成候选。', 'If the sample stage is uncertain, select “Not specified / uncertain” and continue.')}</small>
          {stateMismatchCount > 0 && <div className="experimental-warning"><TriangleAlert size={15} /> {tr(`${stateMismatchCount} 条证据来自其他样品状态；推断时将保留这一差异。`, `${stateMismatchCount} evidence record(s) belong to another sample state; the mismatch remains explicit.`)}</div>}
          <button className="secondary-button accent" disabled={busy !== null} onClick={() => void saveSpec()} type="button">
            {busy === 'spec' ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
            {tr('保存当前信息', 'Save current details')}
          </button>
          {specRevisionId && <span className="success-chip experimental-revision"><CheckCircle2 size={13} /> {tr('已保存', 'Saved')}</span>}
        </article>

        <article className="experimental-card experimental-card-wide">
          <div className="card-heading">
            <div><span className="eyebrow">{tr('第 2 步', 'Step 2')}</span><h3>{tr('表征数据', 'Characterization')}</h3></div>
            <FileUp size={18} />
          </div>
          <div className="experimental-evidence-composer">
            <label>{tr('表征方法', 'Method')}<select value={evidenceKind} onChange={(event) => setEvidenceKind(event.target.value as ExperimentalEvidenceKind)}>{EVIDENCE_KINDS.map((item) => <option key={item} value={item}>{tr(EVIDENCE_KIND_LABELS[item].chinese, EVIDENCE_KIND_LABELS[item].english)}</option>)}</select></label>
            <label>{tr('测量时的样品阶段', 'Sample stage when measured')}<select value={evidenceState} onChange={(event) => setEvidenceState(event.target.value as ExperimentalSampleState)}>{SAMPLE_STATES.map((item) => <option key={item} value={item}>{tr(SAMPLE_STATE_LABELS[item].chinese, SAMPLE_STATE_LABELS[item].english)}</option>)}</select></label>
            <label>{tr('这项数据如何使用', 'How to use this data')}<select value={evidenceRole} onChange={(event) => setEvidenceRole(event.target.value as 'hard' | 'soft' | 'context')}><option value="hard">{tr(EVIDENCE_ROLE_LABELS.hard.chinese, EVIDENCE_ROLE_LABELS.hard.english)}</option><option value="soft">{tr(EVIDENCE_ROLE_LABELS.soft.chinese, EVIDENCE_ROLE_LABELS.soft.english)}</option><option value="context">{tr(EVIDENCE_ROLE_LABELS.context.chinese, EVIDENCE_ROLE_LABELS.context.english)}</option></select></label>
            <label className="file-field"><span>{tr('数据文件（可选）', 'Data file (optional)')}</span><input onChange={(event) => setEvidenceFile(event.target.files?.[0] ?? null)} type="file" /></label>
            <label className="wide">{tr('结果摘要', 'Result summary')}<input value={evidenceNote} onChange={(event) => setEvidenceNote(event.target.value)} placeholder={tr('例如：Cu Kα；活化后出现宽峰', 'e.g. Cu Kα; broad peak after activation')} /></label>
            <details className="experimental-advanced wide">
              <summary>{tr('高级信息（可选）', 'Advanced information (optional)')}</summary>
              <label>{tr('结构化 JSON', 'Structured JSON')}<textarea className="mono-input" rows={3} value={evidenceMetadata} onChange={(event) => setEvidenceMetadata(event.target.value)} /></label>
            </details>
            <button className="secondary-button" disabled={busy !== null} onClick={() => void addEvidenceToDraft()} type="button"><Plus size={15} /> {tr('添加这项表征', 'Add measurement')}</button>
          </div>
          <small className="experimental-field-help">{tr('样品阶段用于区分制备后、活化后和反应后的数据；不知道时可选“未注明 / 不确定”。', 'The sample stage separates as-prepared, activated, and post-reaction measurements. Choose “Not specified / uncertain” when unknown.')}</small>

          <div className="experimental-evidence-list">
            {spec.evidence.map((item) => (
              <div className={item.sample_state !== 'unspecified' && item.sample_state !== spec.target_state ? 'mismatch' : ''} key={item.evidence_id}>
                <span className={`evidence-role role-${item.role}`}>{tr(EVIDENCE_ROLE_LABELS[item.role].chinese, EVIDENCE_ROLE_LABELS[item.role].english)}</span>
                <strong>{tr(EVIDENCE_KIND_LABELS[item.kind].chinese, EVIDENCE_KIND_LABELS[item.kind].english)}</strong>
                <span>{tr(SAMPLE_STATE_LABELS[item.sample_state].chinese, SAMPLE_STATE_LABELS[item.sample_state].english)}</span>
                <span>{item.note || tr('未填写摘要', 'No summary')}</span>
                {item.evidence_artifact_id && <code>{item.evidence_artifact_id}</code>}
                <button aria-label={tr('删除这项表征', 'Remove measurement')} onClick={() => setSpec((current) => ({ ...current, evidence: current.evidence.filter((record) => record.evidence_id !== item.evidence_id) }))} type="button"><Trash2 size={14} /></button>
              </div>
            ))}
            {!spec.evidence.length && <p className="panel-empty">{tr('还没有添加表征数据。建议优先添加 XRD、ICP、XPS 和 TEM；缺少某一项也可以继续。', 'No measurements added. Start with XRD, ICP, XPS, and TEM when available; missing data does not block the workflow.')}</p>}
          </div>

          <h4 className="experimental-subheading">{tr('成分范围（可选）', 'Composition range (optional)')}</h4>
          <div className="experimental-constraint-composer">
            <label>{tr('元素', 'Element')}<input value={constraintElement} onChange={(event) => setConstraintElement(event.target.value)} /></label>
            <label>{tr('最低含量（at.%）', 'Minimum (at.%)')}<input min="0" max="100" step="0.1" type="number" value={constraintMinimum} onChange={(event) => setConstraintMinimum(event.target.value)} /></label>
            <label>{tr('最高含量（at.%）', 'Maximum (at.%)')}<input min="0" max="100" step="0.1" type="number" value={constraintMaximum} onChange={(event) => setConstraintMaximum(event.target.value)} /></label>
            <label>{tr('数据范围', 'Measurement scope')}<select value={constraintScope} onChange={(event) => setConstraintScope(event.target.value as ExperimentalCompositionConstraint['scope'])}>{Object.entries(COMPOSITION_SCOPE_LABELS).map(([value, label]) => <option key={value} value={value}>{tr(label.chinese, label.english)}</option>)}</select></label>
            <button className="secondary-button" onClick={addConstraint} type="button"><Plus size={15} /> {tr('添加范围', 'Add range')}</button>
          </div>
          <div className="experimental-constraint-list">
            {spec.composition_constraints.map((item) => (
              <span key={`${item.element}-${item.scope}`}>{item.element} · {(item.minimum_atomic_fraction * 100).toFixed(1)}–{(item.maximum_atomic_fraction * 100).toFixed(1)} at.% · {tr(COMPOSITION_SCOPE_LABELS[item.scope].chinese, COMPOSITION_SCOPE_LABELS[item.scope].english)}<button aria-label={tr('删除成分范围', 'Remove composition range')} onClick={() => setSpec((current) => ({ ...current, composition_constraints: current.composition_constraints.filter((record) => record !== item) }))} type="button">×</button></span>
            ))}
          </div>
        </article>

        <article className="experimental-card experimental-card-wide">
          <div className="card-heading">
            <div><span className="eyebrow">{tr('第 3 步', 'Step 3')}</span><h3>{tr('参考结构', 'Reference structures')}</h3></div>
            <Database size={18} />
          </div>
          <div className="experimental-provider-summary">
            <div><Atom size={18} /><span><strong>{artifacts.length}</strong>{tr('个已导入结构', 'imported structures')}</span><button onClick={onOpenStructures} type="button">{tr('打开结构库', 'Open library')}</button></div>
            <div><Layers3 size={18} /><span><strong>{catalogs.length}</strong>{tr('次数据库搜索', 'database searches')}</span></div>
            <div><FileUp size={18} /><span><strong>{evidenceArtifacts.length}</strong>{tr('个表征文件', 'measurement files')}</span></div>
          </div>
          <div className="experimental-provider-grid">
            <section>
              <h4>OPTIMADE</h4>
              <p>{tr('从支持 OPTIMADE 的数据库搜索结构。', 'Search a database that supports OPTIMADE.')}</p>
              <label>{tr('数据库地址', 'Database URL')}<input placeholder="https://provider.example" value={optimadeUrl} onChange={(event) => setOptimadeUrl(event.target.value)} /></label>
              <label>{tr('来源名称', 'Source name')}<input value={optimadeProvider} onChange={(event) => setOptimadeProvider(event.target.value)} /></label>
              <label>{tr('包含元素', 'Elements')}<input value={providerElements} onChange={(event) => setProviderElements(event.target.value)} /></label>
              <button className="secondary-button" disabled={busy !== null || !optimadeUrl.trim()} onClick={() => void fetchOptimade()} type="button">{busy === 'optimade' ? <LoaderCircle className="spin" size={15} /> : <Search size={15} />}{tr('搜索 OPTIMADE', 'Search OPTIMADE')}</button>
            </section>
            <section>
              <h4>Materials Project</h4>
              <p>{tr('搜索已知晶体结构。API 密钥只保存在本机系统密钥库。', 'Search known crystal structures. The API key is stored only in the system credential manager.')}</p>
              <CredentialEditor
                busy={busy === 'credential-materials_project'}
                onDelete={deleteCredential}
                onSave={saveCredential}
                provider="materials_project"
                savedToSystem={capabilities?.providers.materials_project.saved_to_system ?? false}
                source={capabilities?.providers.materials_project.credential_source ?? null}
                storeAvailable={capabilities?.credential_store.available ?? false}
              />
              <label>{tr('最多返回', 'Maximum results')}<input min="1" max="1000" type="number" value={providerMaximumResults} onChange={(event) => setProviderMaximumResults(event.target.value)} /></label>
              <button className="secondary-button accent" disabled={busy !== null || !capabilities?.providers.materials_project.available} onClick={() => void fetchMaterialsProject()} type="button">{busy === 'materials-project' ? <LoaderCircle className="spin" size={15} /> : <Database size={15} />}{tr('搜索 Materials Project', 'Search Materials Project')}</button>
              {!capabilities?.providers.materials_project.client_installed && <small>{tr('需要安装 mp-api 才能连接 Materials Project。', 'Install mp-api to connect to Materials Project.')}</small>}
            </section>
          </div>
          <div className="experimental-catalog-list">
            {catalogs.map((catalog) => (
              <label key={catalog.catalog_id}>
                <input checked={selectedCatalogIds.includes(catalog.catalog_id)} onChange={() => setSelectedCatalogIds((current) => current.includes(catalog.catalog_id) ? current.filter((item) => item !== catalog.catalog_id) : [...current, catalog.catalog_id])} type="checkbox" />
                <span><strong>{catalog.display_provider_id}</strong><small>{catalog.reference_count} {tr('条结构', 'structures')} · {formatTimestamp(catalog.created_at_utc)}</small></span>
              </label>
            ))}
          </div>
        </article>

        <article className="experimental-card">
          <div className="card-heading"><div><span className="eyebrow">{tr('第 4 步', 'Step 4')}</span><h3>{tr('生成候选结构', 'Generate candidates')}</h3></div><Play size={18} /></div>
          <h4 className="experimental-subheading">{tr('AI 辅助（可选）', 'AI assistance (optional)')}</h4>
          <CredentialEditor
            busy={busy === 'credential-openai'}
            onDelete={deleteCredential}
            onSave={saveCredential}
            provider="openai"
            savedToSystem={capabilities?.gpt_planner.saved_to_system ?? false}
            source={capabilities?.gpt_planner.credential_source ?? null}
            storeAvailable={capabilities?.credential_store.available ?? false}
          />
          <div className="experimental-form-grid">
            <label>{tr('生成方式', 'Generation method')}<select value={plannerKind} onChange={(event) => setPlannerKind(event.target.value as 'rule' | 'gpt')}><option value="rule">{tr('本地规则（推荐）', 'Local rules (recommended)')}</option><option disabled={!capabilities?.gpt_planner.available} value="gpt">{tr('AI 辅助规划', 'AI-assisted planning')}</option></select></label>
            <label>{tr('最多保留', 'Maximum candidates')}<input min="1" max="50" type="number" value={maximumRepresentatives} onChange={(event) => setMaximumRepresentatives(event.target.value)} /></label>
          </div>
          <details className="experimental-advanced">
            <summary>{tr('XRD 匹配设置（高级）', 'XRD matching settings (advanced)')}</summary>
            <label>{tr('波长', 'Wavelength')}<input value={xrdSettings.wavelength} onChange={(event) => setXrdSettings((current) => ({ ...current, wavelength: event.target.value }))} /></label>
            <label>{tr('允许的零点偏移（°）', 'Allowed zero shifts (°)')}<input value={shiftGridText} onChange={(event) => setShiftGridText(event.target.value)} /></label>
            <label>{tr('峰宽 FWHM（°）', 'Peak widths FWHM (°)')}<input value={fwhmGridText} onChange={(event) => setFwhmGridText(event.target.value)} /></label>
            <label>{tr('最低匹配分数', 'Minimum match score')}<input min="0" max="1" step="0.01" type="number" value={xrdSettings.minimum_supported_score} onChange={(event) => setXrdSettings((current) => ({ ...current, minimum_supported_score: Number(event.target.value) }))} /></label>
          </details>
          <button className="primary-button experimental-run-button" disabled={busy !== null || (!artifacts.length && !selectedCatalogIds.length)} onClick={() => void runInference()} type="button">{busy === 'inference' ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}{tr('生成候选结构', 'Generate candidates')}</button>
          <small>{tr('生成结果会先进入待确认列表，不会直接加入项目结构库。', 'Generated structures first appear in a review list and are not added to the project automatically.')}</small>
        </article>

        <article className="experimental-card">
          <div className="card-heading"><div><span className="eyebrow">{tr('记录', 'History')}</span><h3>{tr('生成历史', 'Generation history')}</h3></div><RefreshCw size={18} /></div>
          <div className="experimental-run-list">
            {runs.map((run) => (
              <button className={activeRun?.run_id === run.run_id ? 'active' : ''} disabled={busy !== null} key={run.run_id} onClick={() => void openRun(run.run_id).catch((error) => reportError(error, 'Failed to open run.'))} type="button">
                <span className={`run-state state-${run.status}`} />
                <span><strong>{localizedRecord(RUN_STATUS_LABELS, run.status, tr)}</strong><small>{run.planner_kind === 'rule' ? tr('本地规则', 'Local rules') : tr('AI 辅助', 'AI assisted')} · {tr(`${run.representative_count}/${run.candidate_count} 个已保留`, `${run.representative_count}/${run.candidate_count} retained`)}</small></span>
                <small>{formatTimestamp(run.created_at_utc)}</small>
              </button>
            ))}
            {!runs.length && <p className="panel-empty">{tr('还没有生成记录。', 'No generation history yet.')}</p>}
          </div>
        </article>
      </div>

      {activeRun && (
        <section className="experimental-results">
          <div className="section-heading">
            <div><span className="eyebrow">{tr('结果', 'Results')}</span><h2>{tr('比较候选结构', 'Compare candidate structures')}</h2><p>{tr('这些结构是与当前表征相容的代表性模型，不是对真实材料的唯一还原。', activeRun.report.claim_interpretation)}</p></div>
            <small>{formatTimestamp(activeRun.created_at_utc)}</small>
          </div>
          <div className="experimental-metrics">
            <div><span>{tr('当前状态', 'Current status')}</span><strong>{localizedRecord(RUN_STATUS_LABELS, activeRun.report.status, tr)}</strong></div>
            <div><span>{tr('当前数据可支持', 'Supported conclusion')}</span><strong>{localizedRecord(CLAIM_LEVEL_LABELS, activeRun.report.claim_ceiling, tr)}</strong></div>
            <div><span>{tr('XRD 最高匹配度', 'Best XRD match')}</span><strong>{formatScore(activeRun.report.phase_search?.best_score)}</strong></div>
            <div><span>{tr('保留的候选', 'Retained candidates')}</span><strong>{representativeIds.size}</strong></div>
          </div>

          <XrdComparisonPlot run={activeRun} />

          <div className="experimental-result-grid">
            <article className="experimental-result-card">
              <h3>{tr('可能的物相', 'Possible phases')}</h3>
              <div className="experimental-phase-table">
                {activeRun.report.phase_search?.single_phase_matches.slice(0, 8).map((match) => (
                  <div key={match.reference_key}><strong>{match.formula}</strong><span>{formatScore(match.evidence_score)}</span><small>{tr('拟合强度', 'Explained intensity')} {(match.explained_intensity_fraction * 100).toFixed(1)}% · {tr('零点偏移', 'zero shift')} {match.shift_degrees.toFixed(2)}°</small></div>
                ))}
                {!activeRun.report.phase_search && <p>{tr('没有可用于相族判断的 XRD/GIXRD 文件。', 'No XRD/GIXRD file was available for phase-family support.')}</p>}
              </div>
            </article>
            <article className="experimental-result-card">
              <h3>{tr('尚不能区分的情况', 'What remains unresolved')}</h3>
              {activeRun.report.ambiguity_reasons.length
                ? <ul>{activeRun.report.ambiguity_reasons.map((item) => <li key={item}>{localizedScientificMessage(item, tr)}</li>)}</ul>
                : <p className="panel-empty">{tr('当前没有记录额外的结构歧义。', 'No additional structural ambiguity was recorded.')}</p>}
              <h4>{tr('如需进一步缩小范围', 'To narrow the candidates further')}</h4>
              <ul>{activeRun.report.recommended_next_experiments.map((item) => <li key={item}>{localizedScientificMessage(item, tr)}</li>)}</ul>
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
                      <span>{localizedRecord(MODEL_KIND_LABELS, candidate.assessment.model_kind, tr)} · {candidate.assessment.num_sites} {tr('个原子', 'atoms')}</span>
                      <small>{tr('表征匹配度', 'Evidence match')} {formatScore(candidate.assessment.evidence_score)} · {tr('来源', 'source')} {candidate.assessment.parent_reference_key}</small>
                    </button>
                  </article>
                )
              })}
            </div>
            <article className="experimental-candidate-viewer">
              <div className="card-heading"><div><span className="eyebrow">{tr('结构预览', 'Structure preview')}</span><h3>{focusedCandidate?.assessment.formula ?? tr('选择候选结构', 'Select a candidate')}</h3></div><Atom size={18} /></div>
              <StructureViewer
                focusedAtomIndex1Based={focusedAtomIndex1Based}
                onAtomClick={focusedCandidate ? setFocusedAtomIndex1Based : undefined}
                showAtomIndices={showAtomIndices}
                structure={focusedCandidate?.viewer ?? null}
              />
              {focusedCandidate && (
                <div className="experimental-structure-inspector">
                  <div className="experimental-viewer-toolbar">
                    <span>{tr('只读查看；点击原子显示详情', 'Read-only; click an atom for details')}</span>
                    <button
                      className={showAtomIndices ? 'active' : ''}
                      onClick={() => setShowAtomIndices((current) => !current)}
                      type="button"
                    >
                      {showAtomIndices ? tr('隐藏编号', 'Hide indices') : tr('显示编号', 'Show indices')}
                    </button>
                  </div>
                  <div className="experimental-element-counts" aria-label={tr('元素计数', 'Element counts')}>
                    {focusedElementCounts.map(([element, count]) => (
                      <span key={element}><strong>{element}</strong>{count}</span>
                    ))}
                  </div>
                  <dl className="experimental-structure-summary">
                    <div><dt>{tr('原子数', 'Atoms')}</dt><dd>{focusedCandidate.viewer.species.length}</dd></div>
                    <div><dt>{tr('周期性', 'Periodicity')}</dt><dd>{focusedCandidate.viewer.periodic.map((item) => item ? 'P' : '—').join(' ')}</dd></div>
                    {focusedLattice && <div><dt>{tr('晶胞长度', 'Cell lengths')}</dt><dd>a {focusedLattice.a.toFixed(3)} · b {focusedLattice.b.toFixed(3)} · c {focusedLattice.c.toFixed(3)} Å</dd></div>}
                  </dl>
                  {focusedAtom?.element && focusedAtom.fractional && focusedAtom.cartesian ? (
                    <div className="experimental-atom-detail" aria-live="polite">
                      <strong>#{focusedAtom.index} · {focusedAtom.element}</strong>
                      <span>{tr('分数坐标', 'Fractional')} [{focusedAtom.fractional.map((value) => value.toFixed(4)).join(', ')}]</span>
                      <span>{tr('笛卡尔坐标', 'Cartesian')} [{focusedAtom.cartesian.map((value) => value.toFixed(4)).join(', ')}] Å</span>
                    </div>
                  ) : (
                    <div className="experimental-atom-detail muted">{tr('点击结构中的任一原子查看元素、序号和坐标。', 'Click any atom to inspect its element, index, and coordinates.')}</div>
                  )}
                </div>
              )}
              {focusedCandidate && <details className="experimental-provenance"><summary>{tr('来源与追溯信息', 'Source and provenance')}</summary><span>{tr('参考结构', 'Reference structure')}</span><code>{focusedCandidate.assessment.parent_reference_key}</code><span>{tr('结构校验码', 'Structure checksum')}</span><code>{shortHash(focusedCandidate.assessment.structure_sha256)}</code></details>}
            </article>
          </div>

          <div className="experimental-review-grid">
            <article className="experimental-card">
              <div className="card-heading"><div><span className="eyebrow">{tr('第 5 步', 'Step 5')}</span><h3>{tr('确认所选结构', 'Confirm selected structures')}</h3></div><CheckCircle2 size={18} /></div>
              <label>{tr('确认人', 'Confirmed by')}<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
              <label>{tr('选择理由', 'Reason for selection')}<textarea rows={3} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder={tr('说明这些结构与哪些表征结果相符，以及仍有哪些不确定性。', 'Note which measurements support these structures and what remains uncertain.')}/></label>
              <button className="secondary-button accent" disabled={busy !== null || !selectedCandidateIds.length || !reviewNote.trim()} onClick={() => void reviewCandidates()} type="button">{busy === 'review' ? <LoaderCircle className="spin" size={15} /> : <CheckCircle2 size={15} />}{tr('保存确认记录', 'Save confirmation')}</button>
              <div className="experimental-review-log">{reviews.map((review) => <div key={review.review_id}><strong>{review.reviewer}</strong><span>{tr(`${review.approved_candidate_ids.length} 个结构`, `${review.approved_candidate_ids.length} structures`)}</span><small>{review.note} · {formatTimestamp(review.reviewed_at_utc)}</small></div>)}</div>
            </article>
            <article className="experimental-card materialization-card">
              <div className="card-heading"><div><span className="eyebrow">{tr('保存', 'Save')}</span><h3>{tr('加入项目结构库', 'Add to project structures')}</h3></div><Save size={18} /></div>
              <p>{tr('只会加入已选中并保存过确认记录的结构。加入后可在“结构”页继续检查和准备计算。', 'Only selected structures with a saved confirmation are added. Continue checking and preparing them in Structures.')}</p>
              <button className="primary-button" disabled={busy !== null || !selectedCandidateIds.length || selectedCandidateIds.some((item) => !approvedIds.has(item))} onClick={() => void materializeCandidates()} type="button">{busy === 'materialize' ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}{tr('加入所选结构', 'Add selected structures')}</button>
              {activeRun.materialized && <span className="success-chip"><CheckCircle2 size={13} /> {tr('已加入项目结构库', 'Added to project structures')}</span>}
            </article>
          </div>
        </section>
      )}
    </section>
  )
}
