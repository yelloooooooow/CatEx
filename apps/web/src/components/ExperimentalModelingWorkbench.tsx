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

import { api, ApiError } from '../api'
import { useI18n } from '../i18n'
import type {
  ExperimentalCandidateReview,
  ExperimentalCatalogSnapshot,
  ExperimentalCompositionConstraint,
  ExperimentalEvidenceArtifact,
  ExperimentalEvidenceCheck,
  ExperimentalEvidenceExtraction,
  ExperimentalEvidenceInput,
  ExperimentalEvidenceKind,
  ExperimentalLatticeSpacingConstraint,
  ExperimentalLocalEnvironmentConstraint,
  ExperimentalModelingCapabilities,
  ExperimentalModelingRun,
  ExperimentalRunSummary,
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

const COMPOSITION_BASIS_LABELS: Record<
  ExperimentalCompositionConstraint['basis'],
  { chinese: string; english: string }
> = {
  total_atomic_fraction: { chinese: '全部原子归一化', english: 'All atoms' },
  metal_normalized_atomic_fraction: { chinese: '仅金属元素归一化', english: 'Metals only' },
  weight_fraction: { chinese: '质量分数', english: 'Weight fraction' },
}

const CHECK_STATUS_LABELS: Record<string, { chinese: string; english: string }> = {
  within_range: { chinese: '符合', english: 'Within range' },
  outside_range: { chinese: '超出范围', english: 'Outside range' },
  not_applicable: { chinese: '不适用', english: 'Not applicable' },
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
  'Add surface-sensitive XPS to test oxidation/hydroxylation hypotheses.': '补充表面敏感的 XPS，以判断氧化或羟基化。',
  'Add targeted TEM/SAED lattice-spacing and crystallite-size evidence for leading phases.': '针对主要候选相补充 TEM/SAED 晶面间距和晶粒尺寸。',
  'Measure XPS before and after activation, and compare with Raman if oxide families remain ambiguous.': '比较活化前后的 XPS；若氧化物类型仍不明确，再结合拉曼光谱。',
  'Treat disorder as a motif ensemble; use total scattering/PDF only if candidate-dependent DFT conclusions remain different.': '将无序结构表示为局部构型集合；只有当不同候选导致不同 DFT 结论时，再考虑总散射/PDF。',
}

const EXTRACTION_NOTICE_LABELS: Record<string, string> = {
  'The uploaded file is retained, but automatic extraction supports text and CSV files only.': '文件已保留，但目前只会从文本或 CSV 表格中自动提取数值。',
  'The uploaded text file could not be decoded as UTF-8; enter a short conclusion manually.': '文本文件无法按 UTF-8 读取，请填写简短结论或另存为 UTF-8。',
  'An oxygen-coordination presence constraint was inferred from the brief conclusion; confirm the range before treating it as mandatory.': '已从简短结论推断出含氧配位，但比例范围仍需确认，不应直接设为强约束。',
  'No fitted XPS peak table was recognized; the raw spectrum was retained without automatic oxidation-state assignment.': '没有识别到 XPS 拟合峰表；原始谱图已保留，但不会自动指定氧化态。',
  'A TEM image alone is not converted into a lattice spacing; add a measured d-spacing or a table.': '不会仅凭 TEM 图片自动测量晶格间距；请补充已测量的 d 值或结果表。',
  'No composition table was recognized; add element ranges manually or use element/value/unit columns.': '没有识别到组成表；可手动补充范围，或使用 element / value / unit 列。',
  'Automatic extraction is unavailable in the running backend; the file and entered notes were saved without blocking your work.': '当前运行中的后端不支持自动提取；文件和已填写信息仍已保存，不会阻止继续工作。请重启 CatEx 以启用自动提取。',
}

const DEFAULT_SPEC: ExperimentalSpec = {
  schema_version: 'catex.experiment-spec.v1',
  sample_id: 'sample-1',
  material_pack: 'surface-catalyst',
  allowed_elements: [],
  excluded_elements: [],
  composition_constraints: [],
  local_environment_constraints: [],
  lattice_spacing_constraints: [],
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

function normalizeSpecForEditor(value: ExperimentalSpec): ExperimentalSpec {
  const legacy = value as ExperimentalSpec & {
    target_state?: unknown
    evidence: Array<ExperimentalEvidenceInput & { sample_state?: unknown }>
  }
  return {
    schema_version: 'catex.experiment-spec.v1',
    sample_id: legacy.sample_id,
    material_pack: legacy.material_pack,
    allowed_elements: legacy.allowed_elements,
    excluded_elements: legacy.excluded_elements,
    composition_constraints: (legacy.composition_constraints ?? []).map((item) => ({
      ...item,
      basis: item.basis ?? 'total_atomic_fraction',
    })),
    local_environment_constraints: legacy.local_environment_constraints ?? [],
    lattice_spacing_constraints: legacy.lattice_spacing_constraints ?? [],
    evidence: (legacy.evidence ?? []).map((item) => {
      const current = { ...item } as ExperimentalEvidenceInput & { sample_state?: unknown }
      delete current.sample_state
      return current
    }),
  }
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

function evidenceSummary(item: ExperimentalEvidenceInput, fallback: string): string {
  if (item.note.trim()) return item.note
  const instrument = item.metadata.instrument_info
  return typeof instrument === 'string' && instrument.trim() ? instrument : fallback
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

function localizedCheckLabel(
  check: ExperimentalEvidenceCheck,
  tr: (chinese: string, english: string) => string,
): string {
  if (check.kind === 'xrd') return tr('母体物相的 XRD 支持', 'Parent-phase XRD support')
  if (check.kind === 'geometry') return tr('结构几何检查', 'Geometry validation')
  if (check.kind === 'tem') return check.label
  if (check.kind === 'xps') {
    const match = check.label.match(/^([A-Z][a-z]?) coordinated to ([A-Z][a-z]?)$/)
    return match
      ? tr(`${match[1]}–${match[2]} 邻近比例`, `${match[1]} coordinated to ${match[2]}`)
      : check.label
  }
  const [element, scope, basis] = check.label.split(' · ')
  const scopeLabel = COMPOSITION_SCOPE_LABELS[
    scope as ExperimentalCompositionConstraint['scope']
  ]
  const basisLabel = COMPOSITION_BASIS_LABELS[
    basis as ExperimentalCompositionConstraint['basis']
  ]
  return scopeLabel && basisLabel
    ? `${element} · ${tr(scopeLabel.chinese, scopeLabel.english)} · ${tr(basisLabel.chinese, basisLabel.english)}`
    : check.label
}

function localizedCheckMessage(
  check: ExperimentalEvidenceCheck,
  tr: (chinese: string, english: string) => string,
): string {
  const messages: Record<string, string> = {
    'XRD evaluates the parent crystalline phase; it does not identify this surface termination.': 'XRD 只检验母体晶相，不能确定这个具体表面终止。',
    'The simulated parent phase is compared with the measured powder pattern.': '将母体结构的模拟衍射与实验粉末图谱进行比较。',
    'This model type does not represent the requested spatial composition scope.': '该模型类型不能表示这项表征对应的空间范围。',
    'Candidate composition is compared with the entered interval.': '候选结构的组成与实验输入范围逐项比较。',
    'This is a geometric compatibility proxy, not a simulated XPS spectrum.': '这里只检查局域几何是否相容，并未模拟 XPS 谱。',
    'A bulk model is not used to evaluate a surface XPS constraint.': '体相模型不用于评价表面 XPS 约束。',
    'Nearest parent-phase diffraction spacing; a local TEM observation is not a bulk phase fraction.': '显示母体结构中最接近的晶面间距；局部 TEM 观察不等同于体相含量。',
    'Local geometry and periodic-distance diagnostics.': '检查局域几何和周期性边界下的原子间距。',
  }
  return tr(messages[check.message] ?? check.message, check.message)
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
  const [evidenceKind, setEvidenceKind] = useState<ExperimentalEvidenceKind>('xrd')
  const [evidenceRole, setEvidenceRole] = useState<'hard' | 'soft' | 'context'>('soft')
  const [evidenceNote, setEvidenceNote] = useState('')
  const [evidenceInstrumentInfo, setEvidenceInstrumentInfo] = useState('')
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null)
  const [extractionNotices, setExtractionNotices] = useState<string[]>([])

  const [constraintElement, setConstraintElement] = useState('')
  const [constraintMinimum, setConstraintMinimum] = useState('')
  const [constraintMaximum, setConstraintMaximum] = useState('')
  const [constraintScope, setConstraintScope] = useState<ExperimentalCompositionConstraint['scope']>('bulk')
  const [constraintBasis, setConstraintBasis] = useState<ExperimentalCompositionConstraint['basis']>('total_atomic_fraction')

  const [environmentElement, setEnvironmentElement] = useState('')
  const [environmentNeighbor, setEnvironmentNeighbor] = useState('O')
  const [environmentMinimum, setEnvironmentMinimum] = useState('')
  const [environmentMaximum, setEnvironmentMaximum] = useState('')
  const [environmentCutoff, setEnvironmentCutoff] = useState('2.6')
  const [environmentScope, setEnvironmentScope] = useState<ExperimentalLocalEnvironmentConstraint['scope']>('surface')

  const [spacingValue, setSpacingValue] = useState('')
  const [spacingTolerance, setSpacingTolerance] = useState('')

  const [optimadeUrl, setOptimadeUrl] = useState('')
  const [optimadeProvider, setOptimadeProvider] = useState('optimade')
  const [providerElements, setProviderElements] = useState('')
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
      const normalized = normalizeSpecForEditor(revision.spec)
      setSpec(normalized)
      setSpecRevisionId(revision.spec_revision_id)
      setProviderElements(normalized.allowed_elements.join(', '))
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
      setSpec(normalizeSpecForEditor(revision.spec))
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
      const evidenceId = `${evidenceKind}-${Date.now().toString(36)}`
      let artifactId: string | undefined
      if (evidenceFile) {
        const artifact = await api.addExperimentalEvidence(projectId, evidenceFile)
        artifactId = artifact.evidence_artifact_id
        setEvidenceArtifacts((current) => [
          artifact,
          ...current.filter((item) => item.evidence_artifact_id !== artifact.evidence_artifact_id),
        ])
      }
      const extractable = new Set<ExperimentalEvidenceKind>([
        'xrd', 'gixrd', 'icp', 'eds', 'xps', 'tem',
      ])
      let extraction: ExperimentalEvidenceExtraction | null = null
      let extractionUnavailable = false
      if (extractable.has(evidenceKind)) {
        try {
          extraction = await api.extractExperimentalEvidence(projectId, {
            evidence_id: evidenceId,
            ...(artifactId ? { evidence_artifact_id: artifactId } : {}),
            kind: evidenceKind as 'xrd' | 'gixrd' | 'icp' | 'eds' | 'xps' | 'tem',
            conclusion: evidenceNote,
            instrument_info: evidenceInstrumentInfo,
          })
        } catch (error) {
          if (error instanceof ApiError && (error.status === 404 || error.status === 405)) {
            extractionUnavailable = true
          } else {
            throw error
          }
        }
      }
      const metadata: Record<string, unknown> = extraction?.metadata ?? {
        ...(evidenceNote ? { brief_conclusion: evidenceNote } : {}),
        ...(evidenceInstrumentInfo ? { instrument_info: evidenceInstrumentInfo } : {}),
      }
      const evidence: ExperimentalEvidenceInput = {
        evidence_id: evidenceId,
        kind: evidenceKind,
        role: evidenceRole,
        metadata,
        ...(artifactId ? { evidence_artifact_id: artifactId } : {}),
        note: evidenceNote || evidenceFile?.name || '',
      }
      const composition = [...spec.composition_constraints]
        for (const item of extraction?.composition_constraints ?? []) {
          const key = `${item.element.toLowerCase()}|${item.scope}|${item.basis}`
          const index = composition.findIndex((record) => (
            `${record.element.toLowerCase()}|${record.scope}|${record.basis}` === key
          ))
          if (index >= 0) composition[index] = item
          else composition.push(item)
        }
      const environments = [...spec.local_environment_constraints]
        for (const item of extraction?.local_environment_constraints ?? []) {
          const key = `${item.element.toLowerCase()}|${item.neighbor_element.toLowerCase()}|${item.scope}`
          const index = environments.findIndex((record) => (
            `${record.element.toLowerCase()}|${record.neighbor_element.toLowerCase()}|${record.scope}` === key
          ))
          if (index >= 0) environments[index] = item
          else environments.push(item)
        }
      const spacings = [...spec.lattice_spacing_constraints]
        for (const item of extraction?.lattice_spacing_constraints ?? []) {
          if (!spacings.some((record) => Math.abs(record.d_spacing_angstrom - item.d_spacing_angstrom) < 1e-6)) {
            spacings.push(item)
          }
        }
      const nextSpec: ExperimentalSpec = {
        ...spec,
        allowed_elements: [...new Set([
          ...spec.allowed_elements,
          ...(extraction?.suggested_elements ?? []),
        ])],
        evidence: [...spec.evidence, evidence],
        composition_constraints: composition,
        local_environment_constraints: environments,
        lattice_spacing_constraints: spacings,
      }
      setSpec(nextSpec)
      if (extraction?.suggested_elements.length) {
        setProviderElements(nextSpec.allowed_elements.join(', '))
      }
      const revision = await api.saveExperimentalSpec(projectId, nextSpec)
      setSpecRevisionId(revision.spec_revision_id)
      setExtractionNotices([
        ...(extraction?.notices ?? []),
        ...(extractionUnavailable
          ? ['Automatic extraction is unavailable in the running backend; the file and entered notes were saved without blocking your work.']
          : []),
      ])
      setEvidenceNote('')
      setEvidenceInstrumentInfo('')
      setEvidenceFile(null)
      const extractedConstraintCount = (
        extraction?.composition_constraints.length ?? 0
      ) + (extraction?.local_environment_constraints.length ?? 0) + (
        extraction?.lattice_spacing_constraints.length ?? 0
      )
      const inferredElements = extraction?.suggested_elements ?? []
      const chineseInference = inferredElements.length
        ? `，并识别到元素 ${inferredElements.join(', ')}`
        : ''
      const englishInference = inferredElements.length
        ? ` and identified ${inferredElements.join(', ')}`
        : ''
      onMessage(
        extractionUnavailable ? 'warning' : 'neutral',
        tr(
          extractionUnavailable
            ? '已添加表征，但当前后端未提供自动提取。文件与填写内容已保存；重启 CatEx 后可恢复自动提取。'
            : extractedConstraintCount
            ? `已添加表征${chineseInference}，并提取 ${extractedConstraintCount} 条可用于筛选的数值约束。`
            : `已添加表征${chineseInference}。信息已结构化保存；暂无可直接用于数值筛选的约束。`,
          extractionUnavailable
            ? 'Measurement added, but automatic extraction is unavailable in the running backend. The file and notes were saved; restart CatEx to restore extraction.'
            : extractedConstraintCount
            ? `Measurement added${englishInference}, with ${extractedConstraintCount} numeric constraint(s) extracted for screening.`
            : `Measurement added${englishInference}. The metadata was saved; no numeric screening constraint was inferred.`,
        ),
      )
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
            && item.basis === constraintBasis
          ),
        ),
        {
          element: constraintElement.trim(),
          minimum_atomic_fraction: minimum / 100,
          maximum_atomic_fraction: maximum / 100,
          scope: constraintScope,
          basis: constraintBasis,
          evidence_ids: current.evidence
            .filter((item) => item.kind === 'icp' || item.kind === 'eds' || item.kind === 'xps')
            .map((item) => item.evidence_id),
        },
      ],
    }))
  }

  const addEnvironmentConstraint = () => {
    const minimum = Number(environmentMinimum)
    const maximum = Number(environmentMaximum)
    const cutoff = Number(environmentCutoff)
    if (
      !environmentElement.trim()
      || !environmentNeighbor.trim()
      || !Number.isFinite(minimum)
      || !Number.isFinite(maximum)
      || !Number.isFinite(cutoff)
      || minimum < 0
      || maximum > 100
      || minimum > maximum
      || cutoff < 0.5
      || cutoff > 6
    ) {
      onMessage('error', tr('请输入有效的局域环境比例和截断距离。', 'Enter a valid local-environment range and cutoff.'))
      return
    }
    const record: ExperimentalLocalEnvironmentConstraint = {
      element: environmentElement.trim(),
      neighbor_element: environmentNeighbor.trim(),
      minimum_site_fraction: minimum / 100,
      maximum_site_fraction: maximum / 100,
      cutoff_angstrom: cutoff,
      scope: environmentScope,
      evidence_ids: spec.evidence.filter((item) => item.kind === 'xps').map((item) => item.evidence_id),
    }
    setSpec((current) => ({
      ...current,
      local_environment_constraints: [
        ...current.local_environment_constraints.filter((item) => !(
          item.element.toLowerCase() === record.element.toLowerCase()
          && item.neighbor_element.toLowerCase() === record.neighbor_element.toLowerCase()
          && item.scope === record.scope
        )),
        record,
      ],
    }))
  }

  const addSpacingConstraint = () => {
    const spacing = Number(spacingValue)
    const tolerance = Number(spacingTolerance)
    if (!Number.isFinite(spacing) || spacing <= 0 || !Number.isFinite(tolerance) || tolerance <= 0 || tolerance > spacing) {
      onMessage('error', tr('请输入有效的晶格间距和容差。', 'Enter a valid lattice spacing and tolerance.'))
      return
    }
    const record: ExperimentalLatticeSpacingConstraint = {
      d_spacing_angstrom: spacing,
      tolerance_angstrom: tolerance,
      evidence_ids: spec.evidence.filter((item) => item.kind === 'tem').map((item) => item.evidence_id),
    }
    setSpec((current) => ({
      ...current,
      lattice_spacing_constraints: [
        ...current.lattice_spacing_constraints.filter((item) => Math.abs(item.d_spacing_angstrom - spacing) > 1e-6),
        record,
      ],
    }))
  }

  const removeEvidence = async (evidenceId: string) => {
    if (!projectId) return
    const previous = spec
    const nextSpec: ExperimentalSpec = {
      ...spec,
      evidence: spec.evidence.filter((item) => item.evidence_id !== evidenceId),
      composition_constraints: spec.composition_constraints
        .map((item) => ({ ...item, evidence_ids: item.evidence_ids.filter((value) => value !== evidenceId) }))
        .filter((item) => item.evidence_ids.length > 0),
      local_environment_constraints: spec.local_environment_constraints
        .map((item) => ({ ...item, evidence_ids: item.evidence_ids.filter((value) => value !== evidenceId) }))
        .filter((item) => item.evidence_ids.length > 0),
      lattice_spacing_constraints: spec.lattice_spacing_constraints
        .map((item) => ({ ...item, evidence_ids: item.evidence_ids.filter((value) => value !== evidenceId) }))
        .filter((item) => item.evidence_ids.length > 0),
    }
    setSpec(nextSpec)
    setBusy('evidence')
    try {
      const revision = await api.saveExperimentalSpec(projectId, nextSpec)
      setSpecRevisionId(revision.spec_revision_id)
      onMessage('neutral', tr('表征及其自动约束已移除。', 'Measurement and its extracted constraints removed.'))
    } catch (error) {
      setSpec(previous)
      reportError(error, 'Failed to remove evidence.')
    } finally {
      setBusy(null)
    }
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
          tr('填写建模范围', 'Define scope'),
          tr('添加表征', 'Add measurements'),
          tr('准备参考结构', 'Prepare references'),
          tr('生成候选', 'Generate candidates'),
          tr('确认并保存', 'Review and save'),
        ].map((label, index) => <li key={label}><span>{index + 1}</span>{label}</li>)}
      </ol>

      <div className="experimental-grid">
        <article className="experimental-card experimental-card-wide experimental-scope-card">
          <div className="card-heading">
            <div><span className="eyebrow">{tr('第 1 步', 'Step 1')}</span><h3>{tr('样品与建模范围', 'Sample and modeling scope')}</h3></div>
            <Beaker size={18} />
          </div>
          <div className="experimental-form-grid">
            <label>{tr('样品名称或编号', 'Sample name or ID')}<input value={spec.sample_id} onChange={(event) => setSpec((current) => ({ ...current, sample_id: event.target.value }))} /></label>
            <label>{tr('材料类型', 'Material type')}<select value={spec.material_pack} onChange={(event) => setSpec((current) => ({ ...current, material_pack: event.target.value }))}><option value="generic">{tr('体相材料', 'Bulk material')}</option><option value="surface-catalyst">{tr('表面催化材料', 'Surface catalyst')}</option><option value="alloy-electrocatalyst">{tr('合金或掺杂催化材料', 'Alloy or doped catalyst')}</option></select></label>
            <label>{tr('主要元素', 'Main elements')}<input value={spec.allowed_elements.join(', ')} onChange={(event) => setSpec((current) => ({ ...current, allowed_elements: parseElements(event.target.value) }))} /></label>
            <label>{tr('不应出现的元素（可选）', 'Excluded elements (optional)')}<input value={spec.excluded_elements.join(', ')} onChange={(event) => setSpec((current) => ({ ...current, excluded_elements: parseElements(event.target.value) }))} placeholder="Na, Cl" /></label>
          </div>
          <small className="experimental-field-help">{tr('主要元素可先留空；添加组成表或明确的物相结论后会自动补全。材料类型只决定生成体相模型还是同时生成表面变体。', 'Main elements may be left blank and are filled from composition tables or explicit phase conclusions. Material type only controls bulk versus surface variants.')}</small>
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
            <label>{tr('这项数据如何使用', 'How to use this data')}<select value={evidenceRole} onChange={(event) => setEvidenceRole(event.target.value as 'hard' | 'soft' | 'context')}><option value="hard">{tr(EVIDENCE_ROLE_LABELS.hard.chinese, EVIDENCE_ROLE_LABELS.hard.english)}</option><option value="soft">{tr(EVIDENCE_ROLE_LABELS.soft.chinese, EVIDENCE_ROLE_LABELS.soft.english)}</option><option value="context">{tr(EVIDENCE_ROLE_LABELS.context.chinese, EVIDENCE_ROLE_LABELS.context.english)}</option></select></label>
            <label className="file-field"><span>{tr('数据文件或结果表（可选）', 'Data file or result table (optional)')}</span><input onChange={(event) => setEvidenceFile(event.target.files?.[0] ?? null)} type="file" /></label>
            <label className="wide">{tr('简短结论（可选）', 'Brief conclusion (optional)')}<input value={evidenceNote} onChange={(event) => setEvidenceNote(event.target.value)} placeholder={tr('例如：Mo–O存在；d = 2.03 ± 0.05 Å', 'e.g. Mo–O is present; d = 2.03 ± 0.05 Å')} /></label>
            <label className="wide">{tr('仪器与测试条件（可选）', 'Instrument and measurement conditions (optional)')}<input value={evidenceInstrumentInfo} onChange={(event) => setEvidenceInstrumentInfo(event.target.value)} placeholder={tr('例如：Cu Kα；GIXRD入射角0.5°；Ni网基底', 'e.g. Cu Kα; GIXRD 0.5° incidence; Ni mesh substrate')} /></label>
            <button className="secondary-button accent" disabled={busy !== null || (!evidenceFile && !evidenceNote.trim() && !evidenceInstrumentInfo.trim())} onClick={() => void addEvidenceToDraft()} type="button">{busy === 'evidence' ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />} {tr('添加并自动提取', 'Add and extract')}</button>
          </div>
          <small className="experimental-field-help">{tr('数据文件、简短结论或仪器信息至少提供一项。CatEx会从常见CSV/文本表格和明确结论中提取可检查信息；原始XPS谱和TEM图片不会被无依据自动判读。', 'Provide at least a data file, short conclusion, or instrument note. CatEx extracts reviewable values from common CSV/text tables and explicit conclusions; it does not guess oxidation states from raw XPS or lattice spacings from a TEM image.')}</small>
          {extractionNotices.map((notice) => <div className="experimental-warning" key={notice}><TriangleAlert size={15} /> {tr(EXTRACTION_NOTICE_LABELS[notice] ?? notice, notice)}</div>)}

          <div className="experimental-evidence-list">
            {spec.evidence.map((item) => (
              <div key={item.evidence_id}>
                <span className={`evidence-role role-${item.role}`}>{tr(EVIDENCE_ROLE_LABELS[item.role].chinese, EVIDENCE_ROLE_LABELS[item.role].english)}</span>
                <strong>{tr(EVIDENCE_KIND_LABELS[item.kind].chinese, EVIDENCE_KIND_LABELS[item.kind].english)}</strong>
                <span>{evidenceSummary(item, tr('未填写摘要', 'No summary'))}</span>
                <span className="evidence-source">{item.evidence_artifact_id
                  ? tr('已上传文件', 'Uploaded file')
                  : item.metadata.brief_conclusion
                    ? tr('人工结论', 'Manual conclusion')
                    : tr('仪器信息', 'Instrument note')}</span>
                <button aria-label={tr('删除这项表征', 'Remove measurement')} disabled={busy !== null} onClick={() => void removeEvidence(item.evidence_id)} type="button"><Trash2 size={14} /></button>
              </div>
            ))}
            {!spec.evidence.length && <p className="panel-empty">{tr('还没有添加表征数据。建议优先添加 XRD、ICP、XPS 和 TEM；缺少某一项也可以继续。', 'No measurements added. Start with XRD, ICP, XPS, and TEM when available; missing data does not block the workflow.')}</p>}
          </div>

          <details className="experimental-constraint-editor" open={Boolean(spec.composition_constraints.length || spec.local_environment_constraints.length || spec.lattice_spacing_constraints.length)}>
            <summary>{tr('检查或补充自动提取结果', 'Review or add extracted constraints')}</summary>

            <h4 className="experimental-subheading">{tr('组成范围 · ICP / EDS / XPS', 'Composition · ICP / EDS / XPS')}</h4>
            <div className="experimental-constraint-composer">
              <label>{tr('元素', 'Element')}<input value={constraintElement} onChange={(event) => setConstraintElement(event.target.value)} /></label>
              <label>{tr('最低（%）', 'Minimum (%)')}<input min="0" max="100" step="0.1" type="number" value={constraintMinimum} onChange={(event) => setConstraintMinimum(event.target.value)} /></label>
              <label>{tr('最高（%）', 'Maximum (%)')}<input min="0" max="100" step="0.1" type="number" value={constraintMaximum} onChange={(event) => setConstraintMaximum(event.target.value)} /></label>
              <label>{tr('空间范围', 'Spatial scope')}<select value={constraintScope} onChange={(event) => setConstraintScope(event.target.value as ExperimentalCompositionConstraint['scope'])}>{Object.entries(COMPOSITION_SCOPE_LABELS).map(([value, label]) => <option key={value} value={value}>{tr(label.chinese, label.english)}</option>)}</select></label>
              <label>{tr('归一化方式', 'Composition basis')}<select value={constraintBasis} onChange={(event) => setConstraintBasis(event.target.value as ExperimentalCompositionConstraint['basis'])}>{Object.entries(COMPOSITION_BASIS_LABELS).map(([value, label]) => <option key={value} value={value}>{tr(label.chinese, label.english)}</option>)}</select></label>
              <button className="secondary-button" onClick={addConstraint} type="button"><Plus size={15} /> {tr('添加组成范围', 'Add composition')}</button>
            </div>
            <div className="experimental-constraint-list">
              {spec.composition_constraints.map((item) => (
                <span key={`${item.element}-${item.scope}-${item.basis}`}>{item.element} · {(item.minimum_atomic_fraction * 100).toFixed(1)}–{(item.maximum_atomic_fraction * 100).toFixed(1)}% · {tr(COMPOSITION_SCOPE_LABELS[item.scope].chinese, COMPOSITION_SCOPE_LABELS[item.scope].english)} · {tr(COMPOSITION_BASIS_LABELS[item.basis].chinese, COMPOSITION_BASIS_LABELS[item.basis].english)}<button aria-label={tr('删除成分范围', 'Remove composition range')} onClick={() => setSpec((current) => ({ ...current, composition_constraints: current.composition_constraints.filter((record) => record !== item) }))} type="button">×</button></span>
              ))}
            </div>

            <h4 className="experimental-subheading">{tr('局域化学环境 · XPS', 'Local chemistry · XPS')}</h4>
            <p className="experimental-field-help">{tr('例如“Mo中有30–60%与O相邻”。这只是几何相容性检查，不等同于模拟XPS谱。', 'For example, “30–60% of Mo sites neighbor O.” This is a geometric compatibility check, not a simulated XPS spectrum.')}</p>
            <div className="experimental-constraint-composer">
              <label>{tr('中心元素', 'Center element')}<input value={environmentElement} onChange={(event) => setEnvironmentElement(event.target.value)} /></label>
              <label>{tr('邻近元素', 'Neighbor element')}<input value={environmentNeighbor} onChange={(event) => setEnvironmentNeighbor(event.target.value)} /></label>
              <label>{tr('最低比例（%）', 'Minimum (%)')}<input min="0" max="100" step="0.1" type="number" value={environmentMinimum} onChange={(event) => setEnvironmentMinimum(event.target.value)} /></label>
              <label>{tr('最高比例（%）', 'Maximum (%)')}<input min="0" max="100" step="0.1" type="number" value={environmentMaximum} onChange={(event) => setEnvironmentMaximum(event.target.value)} /></label>
              <label>{tr('邻近距离（Å）', 'Neighbor cutoff (Å)')}<input min="0.5" max="6" step="0.1" type="number" value={environmentCutoff} onChange={(event) => setEnvironmentCutoff(event.target.value)} /></label>
              <label>{tr('空间范围', 'Spatial scope')}<select value={environmentScope} onChange={(event) => setEnvironmentScope(event.target.value as ExperimentalLocalEnvironmentConstraint['scope'])}><option value="surface">{tr('表面', 'Surface')}</option><option value="local">{tr('局部模型', 'Local model')}</option></select></label>
              <button className="secondary-button" onClick={addEnvironmentConstraint} type="button"><Plus size={15} /> {tr('添加局域环境', 'Add environment')}</button>
            </div>
            <div className="experimental-constraint-list">
              {spec.local_environment_constraints.map((item) => (
                <span key={`${item.element}-${item.neighbor_element}-${item.scope}`}>{item.element}–{item.neighbor_element} · {(item.minimum_site_fraction * 100).toFixed(1)}–{(item.maximum_site_fraction * 100).toFixed(1)}% · ≤ {item.cutoff_angstrom.toFixed(2)} Å<button aria-label={tr('删除局域环境', 'Remove local environment')} onClick={() => setSpec((current) => ({ ...current, local_environment_constraints: current.local_environment_constraints.filter((record) => record !== item) }))} type="button">×</button></span>
              ))}
            </div>

            <h4 className="experimental-subheading">{tr('晶格间距 · TEM / SAED', 'Lattice spacing · TEM / SAED')}</h4>
            <div className="experimental-constraint-composer compact">
              <label>d (Å)<input min="0" step="0.001" type="number" value={spacingValue} onChange={(event) => setSpacingValue(event.target.value)} /></label>
              <label>{tr('容差（Å）', 'Tolerance (Å)')}<input min="0" step="0.001" type="number" value={spacingTolerance} onChange={(event) => setSpacingTolerance(event.target.value)} /></label>
              <button className="secondary-button" onClick={addSpacingConstraint} type="button"><Plus size={15} /> {tr('添加晶格间距', 'Add spacing')}</button>
            </div>
            <div className="experimental-constraint-list">
              {spec.lattice_spacing_constraints.map((item) => (
                <span key={`${item.d_spacing_angstrom}-${item.tolerance_angstrom}`}>d = {item.d_spacing_angstrom.toFixed(3)} ± {item.tolerance_angstrom.toFixed(3)} Å<button aria-label={tr('删除晶格间距', 'Remove lattice spacing')} onClick={() => setSpec((current) => ({ ...current, lattice_spacing_constraints: current.lattice_spacing_constraints.filter((record) => record !== item) }))} type="button">×</button></span>
              ))}
            </div>
            <button className="secondary-button accent experimental-save-constraints" disabled={busy !== null} onClick={() => void saveSpec()} type="button"><Save size={15} /> {tr('保存校对结果', 'Save reviewed values')}</button>
          </details>
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
              <details className="experimental-provider-panel">
                <summary><strong>OPTIMADE</strong><span>{tr('其他开放结构数据库', 'Other open structure databases')}</span></summary>
                <div>
                  <p>{tr('从支持 OPTIMADE 的数据库搜索结构。', 'Search a database that supports OPTIMADE.')}</p>
                  <label>{tr('数据库地址', 'Database URL')}<input placeholder="https://provider.example" value={optimadeUrl} onChange={(event) => setOptimadeUrl(event.target.value)} /></label>
                  <label>{tr('来源名称', 'Source name')}<input value={optimadeProvider} onChange={(event) => setOptimadeProvider(event.target.value)} /></label>
                  <label>{tr('包含元素', 'Elements')}<input value={providerElements} onChange={(event) => setProviderElements(event.target.value)} /></label>
                  <button className="secondary-button" disabled={busy !== null || !optimadeUrl.trim() || !providerElements.trim()} onClick={() => void fetchOptimade()} type="button">{busy === 'optimade' ? <LoaderCircle className="spin" size={15} /> : <Search size={15} />}{tr('搜索 OPTIMADE', 'Search OPTIMADE')}</button>
                </div>
              </details>
            </section>
            <section>
              <details className="experimental-provider-panel">
                <summary><strong>Materials Project</strong><span>{capabilities?.providers.materials_project.available ? tr('已连接', 'Connected') : tr('需要 API 密钥', 'API key needed')}</span></summary>
                <div>
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
                  <button className="secondary-button accent" disabled={busy !== null || !providerElements.trim() || !capabilities?.providers.materials_project.available} onClick={() => void fetchMaterialsProject()} type="button">{busy === 'materials-project' ? <LoaderCircle className="spin" size={15} /> : <Database size={15} />}{tr('搜索 Materials Project', 'Search Materials Project')}</button>
                  {!capabilities?.providers.materials_project.client_installed && <small>{tr('需要安装 mp-api 才能连接 Materials Project。', 'Install mp-api to connect to Materials Project.')}</small>}
                </div>
              </details>
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
          <details className="experimental-advanced experimental-ai-settings">
            <summary>{tr('AI 辅助与 API 密钥（可选）', 'AI assistance and API key (optional)')}</summary>
            <CredentialEditor
              busy={busy === 'credential-openai'}
              onDelete={deleteCredential}
              onSave={saveCredential}
              provider="openai"
              savedToSystem={capabilities?.gpt_planner.saved_to_system ?? false}
              source={capabilities?.gpt_planner.credential_source ?? null}
              storeAvailable={capabilities?.credential_store.available ?? false}
            />
          </details>
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
                const applicableChecks = (candidate.assessment.evidence_checks ?? []).filter((item) => item.status !== 'not_applicable')
                const passedChecks = applicableChecks.filter((item) => item.status === 'within_range').length
                return (
                  <article className={`${focusedCandidateId === candidate.candidate_id ? 'focused' : ''} ${!candidate.assessment.valid ? 'invalid' : ''}`} key={candidate.candidate_id}>
                    <label>
                      <input checked={selected} disabled={!representative || !candidate.assessment.valid} onChange={() => setSelectedCandidateIds((current) => current.includes(candidate.candidate_id) ? current.filter((item) => item !== candidate.candidate_id) : [...current, candidate.candidate_id])} type="checkbox" />
                      <span>{representative ? tr('代表性候选', 'Representative') : tr('非代表候选', 'Non-representative')}</span>
                    </label>
                    <button onClick={() => setFocusedCandidateId(candidate.candidate_id)} type="button">
                      <strong>{candidate.assessment.formula}</strong>
                      <span>{localizedRecord(MODEL_KIND_LABELS, candidate.assessment.model_kind, tr)} · {candidate.assessment.num_sites} {tr('个原子', 'atoms')}</span>
                      <small className="candidate-support-summary">
                        {tr('总体', 'Parent')} {formatScore(candidate.assessment.parent_support)} · {tr('表面', 'Surface')} {formatScore(candidate.assessment.surface_support)} · {tr('局部', 'Local')} {formatScore(candidate.assessment.local_support)}
                      </small>
                      <small>{tr('约束符合', 'Checks passed')} {passedChecks}/{applicableChecks.length || '—'} · {tr('来源', 'source')} {candidate.assessment.parent_reference_key}</small>
                    </button>
                  </article>
                )
              })}
            </div>
            <article className="experimental-candidate-viewer">
              <div className="card-heading"><div><span className="eyebrow">{tr('结构预览', 'Structure preview')}</span><h3>{focusedCandidate?.assessment.formula ?? tr('选择候选结构', 'Select a candidate')}</h3></div><Atom size={18} /></div>
              <StructureViewer atomScale={0.66} structure={focusedCandidate?.viewer ?? null} />
              {focusedCandidate && (
                <section className="experimental-support-panel">
                  <div className="experimental-support-heading">
                    <div>
                      <span className="eyebrow">PARETO SUPPORT</span>
                      <h4>{tr('分层证据支持', 'Evidence support by depth')}</h4>
                    </div>
                    <small>{tr('硬约束只淘汰；背景信息不计分', 'Hard constraints only eliminate; context is not scored')}</small>
                  </div>
                  <div className="experimental-support-vector">
                    <article>
                      <span>{tr('总体结构', 'Parent structure')}</span>
                      <strong>{formatScore(focusedCandidate.assessment.parent_support)}</strong>
                      <small>XRD · ICP</small>
                    </article>
                    <article>
                      <span>{tr('表面状态', 'Surface state')}</span>
                      <strong>{formatScore(focusedCandidate.assessment.surface_support)}</strong>
                      <small>XPS</small>
                    </article>
                    <article>
                      <span>{tr('局部结构', 'Local structure')}</span>
                      <strong>{formatScore(focusedCandidate.assessment.local_support)}</strong>
                      <small>TEM · EDS</small>
                    </article>
                  </div>
                  <p>{tr('“—”表示没有该深度的软证据，不按零分处理。代表性候选是在已有证据轴上互不支配的结构。', '“—” means no soft evidence is available at that depth; it is not treated as zero. Representatives are candidates that are non-dominated on their available evidence axes.')}</p>
                </section>
              )}
              {focusedCandidate && <details className="experimental-provenance"><summary>{tr('来源与追溯信息', 'Source and provenance')}</summary><span>{tr('参考结构', 'Reference structure')}</span><code>{focusedCandidate.assessment.parent_reference_key}</code><span>{tr('结构校验码', 'Structure checksum')}</span><code>{shortHash(focusedCandidate.assessment.structure_sha256)}</code></details>}
              {focusedCandidate && (
                <section className="experimental-evidence-checks">
                  <div className="card-heading"><div><span className="eyebrow">{tr('逐项对照', 'Evidence checks')}</span><h4>{tr('计算模型与实验范围', 'Model versus experiment')}</h4></div></div>
                  {(focusedCandidate.assessment.evidence_checks ?? []).map((check) => (
                    <article className={`check-${check.status}`} key={check.check_id}>
                      <span className="evidence-check-status">{localizedRecord(CHECK_STATUS_LABELS, check.status, tr)}</span>
                      <div>
                        <strong>{localizedCheckLabel(check, tr)}</strong>
                        <small>{localizedCheckMessage(check, tr)}</small>
                      </div>
                      <dl>
                        <div><dt>{tr('模型', 'Model')}</dt><dd>{check.predicted_value == null ? '—' : `${check.unit === 'fraction' || check.unit === 'site fraction' ? (check.predicted_value * 100).toFixed(1) : check.predicted_value.toFixed(3)}${check.unit === 'fraction' || check.unit === 'site fraction' ? '%' : ` ${check.unit}`}`}</dd></div>
                        <div><dt>{tr('实验范围', 'Experimental range')}</dt><dd>{check.experimental_minimum == null || check.experimental_maximum == null ? '—' : `${check.unit === 'fraction' || check.unit === 'site fraction' ? (check.experimental_minimum * 100).toFixed(1) : check.experimental_minimum.toFixed(3)}–${check.unit === 'fraction' || check.unit === 'site fraction' ? (check.experimental_maximum * 100).toFixed(1) : check.experimental_maximum.toFixed(3)}${check.unit === 'fraction' || check.unit === 'site fraction' ? '%' : ` ${check.unit}`}`}</dd></div>
                      </dl>
                    </article>
                  ))}
                </section>
              )}
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
