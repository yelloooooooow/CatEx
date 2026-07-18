import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type NodeTypes,
} from '@xyflow/react'
import {
  Activity,
  AlertTriangle,
  Atom,
  BookOpenCheck,
  Check,
  ChevronDown,
  ChevronRight,
  ChartNoAxesCombined,
  Database,
  FileCheck2,
  FileUp,
  FlaskConical,
  FolderOpen,
  FolderPlus,
  Gauge,
  GitBranch,
  Info,
  LayoutDashboard,
  LoaderCircle,
  LockKeyhole,
  Languages,
  MousePointer2,
  Download,
  Settings2,
  Server,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  ServerOff,
  ShieldCheck,
  Sparkles,
  Upload,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from './api'
import { FreeEnergyDiagram } from './components/FreeEnergyDiagram'
import { ScientificNode } from './components/ScientificNode'
import { StructureViewer } from './components/StructureViewer'
import { localizeNodeDefinition, useI18n } from './i18n'
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
import {
  buildConstraintPreview,
  parseAtomIndices,
  toggleAtomIndex,
  type SelectiveDynamicsStrategy,
} from './selectiveDynamics'
import type {
  Capabilities,
  CalculationConfig,
  CalculationResult,
  CalculationPlanResponse,
  Diagnostic,
  EnergyDerivation,
  HpcObservation,
  HpcProfile,
  HarmonicThermochemistry,
  MaterializationResponse,
  NodeDefinition,
  ProjectArtifact,
  ProjectRecord,
  ReferenceCaseSummary,
  ReactionAnalysis,
  ReactionTemplate,
  ReviewedEnergy,
  RemotePotcarMetadata,
  RemoteRunResult,
  RunSummary,
  RuntimeStatus,
  StructureInspectionResponse,
  TemplateResponse,
  VaspDemoResult,
} from './types'
import {
  buildValidationRequest,
  compatibleHandles,
  rehydrateNodes,
  templateEdgeToFlow,
  templateNodeToFlow,
  type ScientificFlowEdge,
  type ScientificFlowNode,
} from './workflow'
import {
  parseIncarFile,
  parseKpointsFile,
  parsePotcarMetadataFile,
  parseSlurmScriptFile,
  type ImportedSlurmProfile,
} from './vaspInputFiles'
import '@xyflow/react/dist/style.css'
import './styles.css'

const nodeTypes: NodeTypes = { scientific: ScientificNode }
const STORAGE_KEY = 'catex.web-poc.workflow.v2'
const ACTIVE_STRUCTURE_STORAGE_PREFIX = 'catex.web-poc.active-structure.'
const REVIEW_NOTE_ZH = '已核对结构、协议、POTCAR 元数据与资源配置。'
const REVIEW_NOTE_EN =
  'Structure, protocol, POTCAR metadata, and resource configuration have been checked.'
const DEFAULT_NOTICE_ZH = 'HPC 默认断开；只有运行中心逐步确认后才会建立连接或提交单个作业。'
const DEFAULT_NOTICE_EN =
  'HPC is disconnected by default. Connection and single-job submission require explicit steps in Run Center.'
const MAX_VASP_INPUT_FILE_BYTES = 1024 * 1024

const SYNTHETIC_POSCAR = `Synthetic NaCl Web POC
1.0
5.640000 0.000000 0.000000
0.000000 5.640000 0.000000
0.000000 0.000000 5.640000
Na Cl
1 1
Direct
0.000000 0.000000 0.000000 Na
0.500000 0.500000 0.500000 Cl
`

type WorkspaceView = 'projects' | 'workflow' | 'structure' | 'protocol' | 'runs' | 'results' | 'analysis'
type NoticeTone = 'neutral' | 'success' | 'warning' | 'error'

interface Notice {
  tone: NoticeTone
  message: string
}

interface SavedWorkflow {
  schema_version: 'catex.web-local-workflow.v1'
  nodes: ScientificFlowNode[]
  edges: ScientificFlowEdge[]
}

type InputFileKey = 'poscar' | 'incar' | 'kpoints' | 'potcar' | 'slurm'

interface WorkspaceFileHandle {
  kind: 'file'
  name: string
  getFile: () => Promise<File>
  createWritable: () => Promise<{ write: (data: string | Blob) => Promise<void>; close: () => Promise<void> }>
}

interface WorkspaceDirectoryHandle {
  name: string
  values: () => AsyncIterableIterator<WorkspaceFileHandle | { kind: 'directory'; name: string }>
  getFileHandle: (name: string, options?: { create?: boolean }) => Promise<WorkspaceFileHandle>
}

const NODE_VIEW: Record<string, WorkspaceView> = {
  'structure.upload': 'structure',
  'structure.inspect': 'structure',
  'hpc.connect': 'runs',
  'vasp.validate.auto': 'protocol',
  'vasp.validate': 'protocol',
  'slurm.plan': 'protocol',
  'slurm.submit': 'runs',
  'execution.mock': 'runs',
  'vasp.parse': 'results',
  'results.summarize': 'results',
}

function serializeIncar(config: CalculationConfig | null): string {
  const incar = (config?.protocol as { incar?: Record<string, string> } | undefined)?.incar ?? {}
  return Object.entries(incar)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([tag, value]) => `${tag} = ${value}`)
    .join('\n') + '\n'
}

function serializeKpoints(config: CalculationConfig | null): string {
  const kpoints = (config?.protocol as {
    kpoints?: { comment?: string; generation_mode?: string; subdivisions?: number[]; shift?: number[] }
  } | undefined)?.kpoints
  const mode = kpoints?.generation_mode === 'monkhorst-pack' ? 'Monkhorst-Pack' : 'Gamma'
  return [
    kpoints?.comment || 'CatEx automatic mesh',
    '0',
    mode,
    (kpoints?.subdivisions ?? [1, 1, 1]).join(' '),
    (kpoints?.shift ?? [0, 0, 0]).join(' '),
    '',
  ].join('\n')
}

function applyImportedSlurmProfile(config: CalculationConfig, imported: ImportedSlurmProfile) {
  const execution = config.execution_profile as Record<string, unknown>
  const policy = config.cluster_policy as Record<string, unknown>
  for (const key of [
    'job_name',
    'partition',
    'nodes',
    'tasks_per_node',
    'cpus_per_task',
    'walltime',
    'executable',
    'mpi_plugin',
  ] as const) {
    const value = imported[key]
    if (value !== undefined) execution[key] = value
  }
  if (imported.module_loads.length) execution.module_loads = imported.module_loads
  if (imported.partition) {
    policy.allowed_partitions = [
      ...new Set([...(policy.allowed_partitions as string[] ?? []), imported.partition]),
    ]
  }
  if (imported.executable) {
    policy.allowed_executables = [
      ...new Set([...(policy.allowed_executables as string[] ?? []), imported.executable]),
    ]
  }
  if (imported.mpi_plugin) {
    policy.allowed_mpi_plugins = [
      ...new Set([...(policy.allowed_mpi_plugins as string[] ?? []), imported.mpi_plugin]),
    ]
  }
  policy.allowed_modules = [
    ...new Set([...(policy.allowed_modules as string[] ?? []), ...imported.module_loads]),
  ]
  policy.max_nodes = Math.max(Number(policy.max_nodes ?? 1), Number(imported.nodes ?? 1))
  policy.max_cores_per_node = Math.max(
    Number(policy.max_cores_per_node ?? 1),
    Number(imported.tasks_per_node ?? execution.tasks_per_node ?? 1)
      * Number(imported.cpus_per_task ?? execution.cpus_per_task ?? 1),
  )
}

async function writeWorkspaceFile(directory: WorkspaceDirectoryHandle, name: string, content: string | Blob) {
  const handle = await directory.getFileHandle(name, { create: true })
  const writable = await handle.createWritable()
  await writable.write(content)
  await writable.close()
}

const navItems: Array<{
  id: WorkspaceView
  labelZh: string
  labelEn: string
  shortLabelZh: string
  shortLabelEn: string
  icon: typeof GitBranch
}> = [
  { id: 'projects', labelZh: '项目', labelEn: 'Projects', shortLabelZh: '项', shortLabelEn: 'P', icon: FolderOpen },
  { id: 'workflow', labelZh: '工作流', labelEn: 'Workflow', shortLabelZh: '流', shortLabelEn: 'W', icon: GitBranch },
  { id: 'structure', labelZh: '结构工作台', labelEn: 'Structures', shortLabelZh: '构', shortLabelEn: 'S', icon: Atom },
  { id: 'protocol', labelZh: '协议与输入', labelEn: 'VASP Inputs', shortLabelZh: '议', shortLabelEn: 'V', icon: Settings2 },
  { id: 'runs', labelZh: '运行中心', labelEn: 'Run Center', shortLabelZh: '运', shortLabelEn: 'R', icon: Server },
  { id: 'results', labelZh: '计算结果', labelEn: 'Results', shortLabelZh: '果', shortLabelEn: 'E', icon: Gauge },
  { id: 'analysis', labelZh: '反应分析', labelEn: 'Reaction Analysis', shortLabelZh: '析', shortLabelEn: 'A', icon: ChartNoAxesCombined },
]

function formatNumber(value: number | null | undefined, digits = 3): string {
  return value == null ? '—' : value.toFixed(digits)
}

function shortenHash(value: string | null | undefined): string {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : '—'
}

function severityCount(diagnostics: Diagnostic[] | undefined, severity: string): number {
  return diagnostics?.filter((item) => item.severity === severity).length ?? 0
}

function projectArtifactInspection(artifact: ProjectArtifact): StructureInspectionResponse {
  return {
    schema_version: 'catex.structure-upload-inspection.v1',
    retained: true,
    source: {
      filename: artifact.original_filename,
      size_bytes: artifact.size_bytes,
      sha256: artifact.sha256,
    },
    inspection: artifact.inspection,
    viewer: artifact.viewer,
  }
}

async function readSmallTextFile(file: File): Promise<string> {
  if (file.size === 0) throw new Error('The selected file is empty')
  if (file.size > MAX_VASP_INPUT_FILE_BYTES) throw new Error('The selected file exceeds the 1 MiB import limit')
  const text = await file.text()
  if (text.includes('\0')) throw new Error('Binary files are not supported')
  return text
}

function App() {
  const { language, setLanguage, tr } = useI18n()
  const [nodes, setNodes, onNodesChange] = useNodesState<ScientificFlowNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<ScientificFlowEdge>([])
  const [registry, setRegistry] = useState<Map<string, NodeDefinition>>(new Map())
  const [templateResponse, setTemplateResponse] = useState<TemplateResponse | null>(null)
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [connectionState, setConnectionState] = useState<'loading' | 'online' | 'offline'>('loading')
  const [activeView, setActiveView] = useState<WorkspaceView>('workflow')
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [structure, setStructure] = useState<StructureInspectionResponse | null>(null)
  const [result, setResult] = useState<VaspDemoResult | null>(null)
  const [structureReady, setStructureReady] = useState(false)
  const [resultReviewed, setResultReviewed] = useState(false)
  const [resultDecision, setResultDecision] = useState<'accepted' | 'rejected' | null>(null)
  const [reviewedEnergies, setReviewedEnergies] = useState<ReviewedEnergy[]>([])
  const [derivationId, setDerivationId] = useState('adsorption-energy-001')
  const [coefficientText, setCoefficientText] = useState('{\n  "product-energy-id": 1,\n  "reactant-energy-id": -1\n}')
  const [confirmDerivationWrite, setConfirmDerivationWrite] = useState(false)
  const [energyDerivation, setEnergyDerivation] = useState<EnergyDerivation | null>(null)
  const [projects, setProjects] = useState<ProjectRecord[]>([])
  const [artifacts, setArtifacts] = useState<ProjectArtifact[]>([])
  const [activeStructureArtifactId, setActiveStructureArtifactId] = useState('')
  const [currentProject, setCurrentProject] = useState<ProjectRecord | null>(null)
  const [paper4Case, setPaper4Case] = useState<ReferenceCaseSummary | null>(null)
  const [projectTitle, setProjectTitle] = useState('NiZn 全流程验收')
  const [projectPurpose, setProjectPurpose] = useState<ProjectRecord['purpose']>('training')
  const [calculationConfigText, setCalculationConfigText] = useState('')
  const [calculationPlan, setCalculationPlan] = useState<CalculationPlanResponse | null>(null)
  const [, setMaterialization] = useState<MaterializationResponse | null>(null)
  const [reviewer, setReviewer] = useState('local-user')
  const [reviewNote, setReviewNote] = useState(REVIEW_NOTE_ZH)
  const [newIncarTag, setNewIncarTag] = useState('')
  const [newIncarValue, setNewIncarValue] = useState('')
  const [importedInputNames, setImportedInputNames] = useState({ incar: '', kpoints: '', potcar: '' })
  const [poscarSource, setPoscarSource] = useState<string>('')
  const [workDirectory, setWorkDirectory] = useState<WorkspaceDirectoryHandle | null>(null)
  const [workFileSources, setWorkFileSources] = useState<Record<InputFileKey, string>>({
    poscar: '', incar: '', kpoints: '', potcar: '', slurm: '',
  })
  const [localPotcarReceipt, setLocalPotcarReceipt] = useState<{ filename: string; sha256?: string } | null>(null)
  const [selectiveDynamicsEnabled, setSelectiveDynamicsEnabled] = useState(false)
  const [constraintStrategy, setConstraintStrategy] = useState<SelectiveDynamicsStrategy>('adsorbate_indices')
  const [mobileAtomText, setMobileAtomText] = useState('')
  const [bottomLayerCount, setBottomLayerCount] = useState(2)
  const [layerTolerance, setLayerTolerance] = useState(0.5)
  const [constraintSummary, setConstraintSummary] = useState('')
  const [focusedConstraintAtom, setFocusedConstraintAtom] = useState<number | null>(null)
  const [showAllConstraintAtomIndices, setShowAllConstraintAtomIndices] = useState(false)
  const [potcarLabelText, setPotcarLabelText] = useState('')
  const [projectMaxWalltimeText, setProjectMaxWalltimeText] = useState('')
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selectedRunId, setSelectedRunId] = useState('')
  const [hpcProfile, setHpcProfile] = useState<HpcProfile>({
    host: '',
    port: 22,
    username: '',
    private_key_path: '',
    allowed_root: '',
    potcar_builder: '',
    potcar_root: '',
    host_key_sha256: '',
    connect_timeout_seconds: 15,
  })
  const [hpcConnected, setHpcConnected] = useState(false)
  const [hpcStaged, setHpcStaged] = useState(false)
  const [hpcJobId, setHpcJobId] = useState<string | null>(null)
  const [hpcObservation, setHpcObservation] = useState<HpcObservation | null>(null)
  const [remoteResult, setRemoteResult] = useState<RemoteRunResult | null>(null)
  const [calculationResults, setCalculationResults] = useState<CalculationResult[]>([])
  const [thermochemistry, setThermochemistry] = useState<HarmonicThermochemistry | null>(null)
  const [thermoTemperature, setThermoTemperature] = useState('298.15')
  const [thermoCutoff, setThermoCutoff] = useState('50')
  const [reactionTemplates, setReactionTemplates] = useState<ReactionTemplate[]>([])
  const [reactionTemplateId, setReactionTemplateId] = useState<ReactionTemplate['template_id']>('oer-aem-che')
  const [reactionBindings, setReactionBindings] = useState<Record<string, string>>({})
  const [reactionEnergies, setReactionEnergies] = useState<Record<string, string>>({
    slab: '-100.000',
    h_star: '-103.450',
    oh_star: '-106.000',
    o_star: '-104.000',
    ooh_star: '-107.000',
  })
  const [reactionCorrections, setReactionCorrections] = useState<Record<string, string>>({})
  const [h2Energy, setH2Energy] = useState('-6.800')
  const [h2oEnergy, setH2oEnergy] = useState('-14.200')
  const [reactionTemperature, setReactionTemperature] = useState('298.15')
  const [reactionPotential, setReactionPotential] = useState('0.00')
  const [reactionPh, setReactionPh] = useState('0.00')
  const [referenceElectrode, setReferenceElectrode] = useState<'RHE' | 'SHE'>('RHE')
  const [reactionAnalysis, setReactionAnalysis] = useState<ReactionAnalysis | null>(null)
  const [confirmRemoteWrite, setConfirmRemoteWrite] = useState(false)
  const [confirmSubmit, setConfirmSubmit] = useState(false)
  const [confirmResultPull, setConfirmResultPull] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice>({
    tone: 'neutral',
    message: tr(DEFAULT_NOTICE_ZH, DEFAULT_NOTICE_EN),
  })
  const [bootstrapKey, setBootstrapKey] = useState(0)
  const [languageMenuOpen, setLanguageMenuOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const incarInputRef = useRef<HTMLInputElement>(null)
  const kpointsInputRef = useRef<HTMLInputElement>(null)
  const potcarMetadataInputRef = useRef<HTMLInputElement>(null)
  const slurmInputRef = useRef<HTMLInputElement>(null)
  const hpcProfileInputRef = useRef<HTMLInputElement>(null)
  const languageMenuRef = useRef<HTMLDivElement>(null)
  const currentProjectId = currentProject?.project_id ?? null

  useEffect(() => {
    setReviewNote((current) => {
      if (current !== REVIEW_NOTE_ZH && current !== REVIEW_NOTE_EN) return current
      return language === 'zh-CN' ? REVIEW_NOTE_ZH : REVIEW_NOTE_EN
    })
    setNotice((current) => {
      if (current.message !== DEFAULT_NOTICE_ZH && current.message !== DEFAULT_NOTICE_EN) return current
      return {
        ...current,
        message: language === 'zh-CN' ? DEFAULT_NOTICE_ZH : DEFAULT_NOTICE_EN,
      }
    })
  }, [language])

  useEffect(() => {
    if (!languageMenuOpen) return
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!languageMenuRef.current?.contains(event.target as Node)) setLanguageMenuOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setLanguageMenuOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [languageMenuOpen])

  const loadTemplate = useCallback(
    (response: TemplateResponse, definitions: Map<string, NodeDefinition>, allowSaved = true) => {
      let nextNodes = response.template.nodes.map((node) => templateNodeToFlow(node, definitions))
      let nextEdges = response.template.edges.map((edge) =>
        templateEdgeToFlow(edge, response.template, definitions),
      )
      if (allowSaved) {
        try {
          const raw = localStorage.getItem(STORAGE_KEY)
          if (raw) {
            const saved = JSON.parse(raw) as SavedWorkflow
            if (saved.schema_version === 'catex.web-local-workflow.v1') {
              nextNodes = rehydrateNodes(saved.nodes, definitions)
              nextEdges = saved.edges
            }
          }
        } catch {
          localStorage.removeItem(STORAGE_KEY)
        }
      }
      setNodes(nextNodes)
      setEdges(nextEdges)
      setSelectedNodeId(nextNodes[0]?.id ?? null)
    },
    [setEdges, setNodes],
  )

  useEffect(() => {
    let cancelled = false
    setConnectionState('loading')
    Promise.all([
      api.capabilities(),
      api.registry(),
      api.defaultTemplate(),
      api.projects(),
      api.paper4ReferenceCase(),
      api.reactionTemplates(),
    ])
      .then(([capabilityPayload, definitions, templatePayload, projectPayload, referenceCase, templates]) => {
        if (cancelled) return
        const definitionMap = new Map(definitions.map((item) => [item.type_id, item]))
        setCapabilities(capabilityPayload)
        setRegistry(definitionMap)
        setTemplateResponse(templatePayload)
        loadTemplate(templatePayload, definitionMap)
        setProjects(projectPayload)
        setPaper4Case(referenceCase)
        setReactionTemplates(templates)
        setCurrentProject((current) => current ?? projectPayload[0] ?? null)
        setConnectionState('online')
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setConnectionState('offline')
        setNotice({
          tone: 'error',
          message: error instanceof Error
            ? tr(`本地 API 未连接：${error.message}`, `Local API unavailable: ${error.message}`)
            : tr('本地 API 未连接。', 'Local API unavailable.'),
        })
      })
    return () => {
      cancelled = true
    }
  }, [bootstrapKey, loadTemplate, tr])

  useEffect(() => {
    if (!currentProjectId || !templateResponse || registry.size === 0) return
    let cancelled = false
    Promise.all([
      api.projectArtifacts(currentProjectId),
      api.projectWorkflow(currentProjectId),
      api.projectCalculationConfig(currentProjectId),
      api.defaultCalculationConfig(),
      api.projectRuns(currentProjectId),
      api.reviewedEnergies(currentProjectId),
      api.calculationResults(currentProjectId),
    ])
      .then(async ([projectArtifacts, savedWorkflow, savedConfig, defaultConfig, projectRuns, projectEnergies, projectResults]) => {
        if (cancelled) return
        setArtifacts(projectArtifacts)
        const rememberedStructureId = localStorage.getItem(
          `${ACTIVE_STRUCTURE_STORAGE_PREFIX}${currentProjectId}`,
        ) ?? ''
        const latestStructure = selectActiveStructureArtifact(projectArtifacts, rememberedStructureId)
        setActiveStructureArtifactId(latestStructure?.artifact_id ?? '')
        let restoredStructure: StructureInspectionResponse | null = null
        if (latestStructure) {
          restoredStructure = projectArtifactInspection(latestStructure)
          setStructure(restoredStructure)
          const source = await api.projectArtifactSource(currentProjectId, latestStructure.artifact_id)
          setPoscarSource(source.content)
          setStructureReady(restoredStructure.inspection.status !== 'error')
        } else {
          setStructure(null)
          setPoscarSource('')
          setStructureReady(false)
        }
        const savedTypeIds = new Set(savedWorkflow?.nodes.map((node) => node.type_id) ?? [])
        if (savedWorkflow && savedTypeIds.has('hpc.connect') && savedTypeIds.has('slurm.submit')) {
          loadTemplate(
            {
              ...templateResponse,
              template: {
                ...templateResponse.template,
                nodes: savedWorkflow.nodes,
                edges: savedWorkflow.edges,
              },
            },
            registry,
            false,
          )
        }
        if (restoredStructure && latestStructure) {
          const inspectionStatus: RuntimeStatus =
            restoredStructure.inspection.status === 'error'
              ? 'blocked'
              : restoredStructure.inspection.status === 'warning'
                ? 'warning'
                : 'success'
          setNodes((current) =>
            current.map((node) => {
              const typeId = node.data.definition.type_id
              if (typeId === 'structure.upload') {
                return {
                  ...node,
                  data: {
                    ...node.data,
                    status: 'success',
                    detail: tr(
                      `${latestStructure.original_filename} · 已从项目恢复`,
                      `${latestStructure.original_filename} · restored from project`,
                    ),
                  },
                }
              }
              if (typeId === 'structure.inspect') {
                return {
                  ...node,
                  data: {
                    ...node.data,
                    status: inspectionStatus,
                    detail: restoredStructure.inspection.record
                      ? `${restoredStructure.inspection.record.reduced_formula} · ${restoredStructure.inspection.record.num_sites} atoms`
                      : tr('结构无法解析', 'Structure could not be parsed'),
                  },
                }
              }
              return node
            }),
          )
        }
        const restoredConfig = savedConfig ?? defaultConfig
        const preferredRunId = String(
          (restoredConfig.execution_profile as { job_name?: string } | undefined)?.job_name ?? '',
        )
        setCalculationConfigText(JSON.stringify(restoredConfig, null, 2))
        setImportedInputNames({ incar: '', kpoints: '', potcar: '' })
        setCalculationPlan(null)
        setMaterialization(null)
        setLocalPotcarReceipt(null)
        setRuns(projectRuns)
        setSelectedRunId((current) =>
          projectRuns.some((run) => run.run_id === current)
            ? current
            : (projectRuns.find((run) => run.run_id === preferredRunId)?.run_id ?? projectRuns[0]?.run_id ?? ''),
        )
        setHpcStaged(false)
        setHpcJobId(projectRuns.find((run) => run.run_id === preferredRunId)?.job_id ?? null)
        setHpcObservation(null)
        setRemoteResult(null)
        setReviewedEnergies(projectEnergies)
        setCalculationResults(projectResults)
        setEnergyDerivation(null)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setNotice({
            tone: 'error',
            message: error instanceof Error ? error.message : tr('项目恢复失败。', 'Failed to restore project.'),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [currentProjectId, loadTemplate, registry, setNodes, templateResponse, tr])

  const latestStructureArtifact = useMemo(
    () => selectActiveStructureArtifact(artifacts, activeStructureArtifactId) ?? null,
    [activeStructureArtifactId, artifacts],
  )

  const selectedRun = useMemo(
    () => runs.find((run) => run.run_id === selectedRunId) ?? null,
    [runs, selectedRunId],
  )

  useEffect(() => {
    setHpcStaged(Boolean(selectedRun?.potcar_materialized || selectedRun?.submitted))
    setHpcJobId(selectedRun?.job_id ?? null)
  }, [selectedRun?.job_id, selectedRun?.potcar_materialized, selectedRun?.submitted])

  const activeReactionTemplate = useMemo(
    () => reactionTemplates.find((item) => item.template_id === reactionTemplateId) ?? null,
    [reactionTemplateId, reactionTemplates],
  )

  const calculationConfig = useMemo<CalculationConfig | null>(() => {
    try {
      return JSON.parse(calculationConfigText) as CalculationConfig
    } catch {
      return null
    }
  }, [calculationConfigText])

  const clusterMaxWalltimeMinutes = Number(
    (calculationConfig?.cluster_policy as { max_walltime_minutes?: number } | undefined)
      ?.max_walltime_minutes ?? 0,
  )

  useEffect(() => {
    setProjectMaxWalltimeText(formatSlurmWalltime(clusterMaxWalltimeMinutes))
  }, [clusterMaxWalltimeMinutes, currentProjectId])

  const diagnosticMessage = useCallback(
    (diagnostic: Diagnostic | undefined): string => {
      if (!diagnostic) return ''
      if (diagnostic.code === 'SLURM_WALLTIME_LIMIT_EXCEEDED') {
        const requested = Number(diagnostic.context?.requested_minutes)
        const maximum = Number(diagnostic.context?.maximum_minutes)
        if (Number.isFinite(requested) && Number.isFinite(maximum)) {
          return tr(
            `任务申请时长 ${formatSlurmWalltime(requested)}（${requested} 分钟），超过项目允许的最大时长 ${formatSlurmWalltime(maximum)}（${maximum} 分钟）。`,
            `Requested walltime ${formatSlurmWalltime(requested)} (${requested} minutes) exceeds the project maximum ${formatSlurmWalltime(maximum)} (${maximum} minutes).`,
          )
        }
      }
      return diagnostic.message
    },
    [tr],
  )

  const incarEntries = useMemo(() => {
    const protocol = calculationConfig?.protocol as { incar?: Record<string, string> } | undefined
    return Object.entries(protocol?.incar ?? {}).sort(([left], [right]) => left.localeCompare(right))
  }, [calculationConfig])

  const constraintPreview = useMemo(
    () => buildConstraintPreview(
      structure?.viewer ?? null,
      constraintStrategy,
      mobileAtomText,
      bottomLayerCount,
      layerTolerance,
    ),
    [bottomLayerCount, constraintStrategy, layerTolerance, mobileAtomText, structure?.viewer],
  )

  const expectedPotcarSpeciesOrder = useMemo(
    () => {
      const declaredOrder = poscarSpeciesOrder(poscarSource)
      return declaredOrder.length ? declaredOrder : uniqueSpeciesOrder(structure?.viewer?.species)
    },
    [poscarSource, structure?.viewer?.species],
  )
  const configuredPotcarMetadata = calculationConfig?.potcar_metadata as
    | { potential_family?: string; datasets?: Array<Record<string, unknown>> }
    | undefined
  const configuredPotcarOrder = potcarDatasetOrder(configuredPotcarMetadata)
  const potcarMetadataCompatible = potcarMetadataMatchesSpecies(
    configuredPotcarMetadata,
    expectedPotcarSpeciesOrder,
  )

  useEffect(() => {
    setFocusedConstraintAtom(null)
    setPotcarLabelText('')
  }, [structure?.source.sha256])

  const kpointsConfig = useMemo(() => {
    const protocol = calculationConfig?.protocol as {
      kpoints?: {
        comment?: string
        generation_mode?: string
        subdivisions?: number[]
        shift?: number[]
      }
    } | undefined
    return protocol?.kpoints ?? null
  }, [calculationConfig])

  const mutateCalculationConfig = useCallback(
    (mutator: (config: CalculationConfig) => void) => {
      if (!calculationConfig) {
        setNotice({
          tone: 'error',
          message: tr('请先修复高级 JSON 中的语法错误。', 'Fix the syntax error in Advanced JSON first.'),
        })
        return
      }
      const next = structuredClone(calculationConfig)
      mutator(next)
      setCalculationConfigText(JSON.stringify(next, null, 2))
      setCalculationPlan(null)
      setMaterialization(null)
    },
    [calculationConfig, tr],
  )

  const updateIncarValue = useCallback(
    (tag: string, value: string) => {
      mutateCalculationConfig((config) => {
        const protocol = config.protocol as { incar: Record<string, string> }
        protocol.incar[tag] = value
      })
    },
    [mutateCalculationConfig],
  )

  const removeIncarTag = useCallback(
    (tag: string) => {
      mutateCalculationConfig((config) => {
        const protocol = config.protocol as { incar: Record<string, string> }
        delete protocol.incar[tag]
      })
    },
    [mutateCalculationConfig],
  )

  const addIncarTag = useCallback(() => {
    const tag = newIncarTag.trim().toUpperCase()
    const value = newIncarValue.trim()
    if (!/^[A-Z][A-Z0-9_]{0,31}$/.test(tag) || !value) {
      setNotice({
        tone: 'error',
        message: tr('请输入合法的 INCAR 标签和非空值。', 'Enter a valid INCAR tag and a non-empty value.'),
      })
      return
    }
    updateIncarValue(tag, value)
    setNewIncarTag('')
    setNewIncarValue('')
  }, [newIncarTag, newIncarValue, tr, updateIncarValue])

  const updateKpoints = useCallback(
    (field: 'comment' | 'generation_mode' | 'subdivisions' | 'shift', value: string | number[]) => {
      mutateCalculationConfig((config) => {
        const protocol = config.protocol as { kpoints: Record<string, string | number[]> }
        protocol.kpoints[field] = value
      })
    },
    [mutateCalculationConfig],
  )

  const updateExecutionProfile = useCallback(
    (field: string, value: string | number | string[]) => {
      mutateCalculationConfig((config) => {
        const execution = config.execution_profile as Record<string, unknown>
        const policy = config.cluster_policy as Record<string, unknown>
        execution[field] = value
        if (field === 'partition' && typeof value === 'string') {
          policy.allowed_partitions = [...new Set([...(policy.allowed_partitions as string[] ?? []), value])]
        }
        if (field === 'module_loads' && Array.isArray(value)) {
          policy.allowed_modules = [...new Set([...(policy.allowed_modules as string[] ?? []), ...value])]
        }
        if (field === 'executable' && typeof value === 'string') {
          policy.allowed_executables = [...new Set([...(policy.allowed_executables as string[] ?? []), value])]
        }
        if (field === 'mpi_plugin' && typeof value === 'string') {
          policy.allowed_mpi_plugins = [...new Set([...(policy.allowed_mpi_plugins as string[] ?? []), value])]
        }
        if (field === 'nodes' && typeof value === 'number') {
          policy.max_nodes = Math.max(Number(policy.max_nodes ?? 1), value)
        }
        if ((field === 'tasks_per_node' || field === 'cpus_per_task') && typeof value === 'number') {
          const tasks = Number(field === 'tasks_per_node' ? value : execution.tasks_per_node ?? 1)
          const cpus = Number(field === 'cpus_per_task' ? value : execution.cpus_per_task ?? 1)
          policy.max_cores_per_node = Math.max(Number(policy.max_cores_per_node ?? 1), tasks * cpus)
        }
      })
    },
    [mutateCalculationConfig],
  )

  const commitProjectMaxWalltime = useCallback(() => {
    const minutes = parseSlurmWalltimeMinutes(projectMaxWalltimeText)
    if (minutes === null || minutes <= 0) {
      setProjectMaxWalltimeText(formatSlurmWalltime(clusterMaxWalltimeMinutes))
      setNotice({
        tone: 'error',
        message: tr(
          '项目允许的最大时间必须使用 Slurm 格式 [天-]时:分:秒，例如 7-00:00:00。',
          'Project maximum walltime must use Slurm format [D-]HH:MM:SS, for example 7-00:00:00.',
        ),
      })
      return
    }
    mutateCalculationConfig((config) => {
      const policy = config.cluster_policy as Record<string, unknown>
      policy.max_walltime_minutes = minutes
    })
    setProjectMaxWalltimeText(formatSlurmWalltime(minutes))
  }, [clusterMaxWalltimeMinutes, mutateCalculationConfig, projectMaxWalltimeText, tr])

  const importIncar = useCallback(
    async (file: File, fromFolder = false) => {
      try {
        if (!fromFolder && importedInputNames.incar && !window.confirm(tr(
          `当前 INCAR 来自 ${importedInputNames.incar}。是否替换？`,
          `The current INCAR came from ${importedInputNames.incar}. Replace it?`,
        ))) return
        if (!calculationConfig) throw new Error(tr('当前计算配置 JSON 无效。', 'The current calculation configuration JSON is invalid.'))
        const incar = parseIncarFile(await readSmallTextFile(file))
        mutateCalculationConfig((config) => {
          const protocol = config.protocol as { incar: Record<string, string> }
          protocol.incar = incar
        })
        setImportedInputNames((current) => ({ ...current, incar: file.name }))
        setWorkFileSources((current) => ({ ...current, incar: file.name }))
        setNotice({
          tone: 'success',
          message: tr(
            `已从 ${file.name} 导入并替换当前 INCAR，共 ${Object.keys(incar).length} 个参数；保存前仍需后端校验。`,
            `Imported ${file.name} and replaced the current INCAR with ${Object.keys(incar).length} parameters; backend validation is still required before saving.`,
          ),
        })
      } catch (error) {
        setNotice({
          tone: 'error',
          message: error instanceof Error ? error.message : tr('INCAR 导入失败。', 'INCAR import failed.'),
        })
      }
    },
    [calculationConfig, importedInputNames.incar, mutateCalculationConfig, tr],
  )

  const importKpoints = useCallback(
    async (file: File, fromFolder = false) => {
      try {
        if (!fromFolder && importedInputNames.kpoints && !window.confirm(tr(
          `当前 KPOINTS 来自 ${importedInputNames.kpoints}。是否替换？`,
          `The current KPOINTS came from ${importedInputNames.kpoints}. Replace it?`,
        ))) return
        if (!calculationConfig) throw new Error(tr('当前计算配置 JSON 无效。', 'The current calculation configuration JSON is invalid.'))
        const kpoints = parseKpointsFile(await readSmallTextFile(file))
        mutateCalculationConfig((config) => {
          const protocol = config.protocol as { kpoints: unknown }
          protocol.kpoints = kpoints
        })
        setImportedInputNames((current) => ({ ...current, kpoints: file.name }))
        setWorkFileSources((current) => ({ ...current, kpoints: file.name }))
        setNotice({
          tone: 'success',
          message: tr(
            `已从 ${file.name} 导入并替换当前自动网格 KPOINTS；保存前仍需后端校验。`,
            `Imported ${file.name} and replaced the current automatic-mesh KPOINTS; backend validation is still required before saving.`,
          ),
        })
      } catch (error) {
        setNotice({
          tone: 'error',
          message: error instanceof Error ? error.message : tr('KPOINTS 导入失败。', 'KPOINTS import failed.'),
        })
      }
    },
    [calculationConfig, importedInputNames.kpoints, mutateCalculationConfig, tr],
  )

  const importPotcarMetadata = useCallback(
    async (file: File, fromFolder = false) => {
      try {
        if (!fromFolder && importedInputNames.potcar && !window.confirm(tr(
          `当前 POTCAR 元数据来自 ${importedInputNames.potcar}。是否替换？`,
          `The current POTCAR metadata came from ${importedInputNames.potcar}. Replace it?`,
        ))) return
        if (!calculationConfig) throw new Error(tr('当前计算配置 JSON 无效。', 'The current calculation configuration JSON is invalid.'))
        if (!file.name.toLowerCase().endsWith('.json')) {
          throw new Error(
            tr(
              '只允许选择脱敏的 POTCAR metadata JSON；原始 POTCAR 不会被读取。',
              'Select sanitized POTCAR metadata JSON only; raw POTCAR will not be read.',
            ),
          )
        }
        const metadata = parsePotcarMetadataFile(await readSmallTextFile(file))
        mutateCalculationConfig((config) => {
          config.potcar_metadata = metadata as unknown as Record<string, unknown>
        })
        setImportedInputNames((current) => ({ ...current, potcar: file.name }))
        setNotice({
          tone: 'success',
          message: tr(
            `已从 ${file.name} 导入并替换 POTCAR metadata，共 ${metadata.datasets.length} 个数据集；未读取原始 POTCAR。`,
            `Imported ${file.name} and replaced POTCAR metadata with ${metadata.datasets.length} datasets; no raw POTCAR was read.`,
          ),
        })
      } catch (error) {
        setNotice({
          tone: 'error',
          message: error instanceof Error ? error.message : tr('POTCAR metadata 导入失败。', 'POTCAR metadata import failed.'),
        })
      }
    },
    [calculationConfig, importedInputNames.potcar, mutateCalculationConfig, tr],
  )

  const importSlurm = useCallback(
    async (file: File, fromFolder = false) => {
      try {
        if (!fromFolder && workFileSources.slurm && !window.confirm(tr(
          `当前提交设置来自 ${workFileSources.slurm}。是否替换？`,
          `The current submission settings came from ${workFileSources.slurm}. Replace them?`,
        ))) return
        const imported = parseSlurmScriptFile(await readSmallTextFile(file))
        mutateCalculationConfig((config) => {
          applyImportedSlurmProfile(config, imported)
        })
        setWorkFileSources((current) => ({ ...current, slurm: file.name }))
        setNotice({
          tone: imported.ignored_lines.length ? 'warning' : 'success',
          message: tr(
            `已读取 ${file.name} 的安全资源字段；${imported.ignored_lines.length} 行自定义 shell/邮件设置未导入。`,
            `Imported safe resource fields from ${file.name}; ${imported.ignored_lines.length} custom shell/email lines were ignored.`,
          ),
        })
      } catch (error) {
        setNotice({ tone: 'error', message: error instanceof Error ? error.message : tr('Slurm 脚本导入失败。', 'Slurm import failed.') })
      }
    },
    [mutateCalculationConfig, tr, workFileSources.slurm],
  )

  const importHpcProfile = useCallback(
    async (file: File) => {
      try {
        const payload = JSON.parse(await file.text()) as Partial<HpcProfile>
        if (
          typeof payload.host !== 'string' ||
          typeof payload.port !== 'number' ||
          typeof payload.username !== 'string' ||
          typeof payload.private_key_path !== 'string' ||
          typeof payload.allowed_root !== 'string'
        ) {
          throw new Error('invalid HPC profile')
        }
        setHpcProfile({
          host: payload.host,
          port: payload.port,
          username: payload.username,
          private_key_path: payload.private_key_path,
          allowed_root: payload.allowed_root,
          potcar_builder: payload.potcar_builder ?? '',
          potcar_root: payload.potcar_root ?? '',
          host_key_sha256: payload.host_key_sha256 ?? '',
          connect_timeout_seconds: payload.connect_timeout_seconds ?? 15,
        })
        setHpcConnected(false)
        setNotice({
          tone: 'success',
          message: tr(
            '已将本机连接配置读入当前页面内存；未上传、未持久化。',
            'The local connection profile was loaded into page memory only; it was not uploaded or persisted.',
          ),
        })
      } catch {
        setNotice({
          tone: 'error',
          message: tr('HPC 连接配置 JSON 无效。', 'The HPC connection profile JSON is invalid.'),
        })
      }
    },
    [tr],
  )

  const completedCount = useMemo(
    () => nodes.filter((node) => node.data.status !== 'idle').length,
    [nodes],
  )

  const updateNode = useCallback(
    (typeId: string, status: RuntimeStatus, detail?: string) => {
      setNodes((current) =>
        current.map((node) =>
          node.data.definition.type_id === typeId
            ? { ...node, data: { ...node.data, status, detail } }
            : node,
        ),
      )
    },
    [setNodes],
  )

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!compatibleHandles(connection.sourceHandle, connection.targetHandle)) {
        setNotice({
          tone: 'error',
          message: tr(
            '端口科学类型不兼容，连接已拒绝。',
            'Connection rejected because the scientific port types are incompatible.',
          ),
        })
        return
      }
      setEdges((current) =>
        addEdge(
          {
            ...connection,
            id: `edge-${crypto.randomUUID()}`,
            type: 'smoothstep',
            markerEnd: { type: MarkerType.ArrowClosed, color: '#6e8f86' },
            style: { stroke: '#5d756f', strokeWidth: 1.6 },
          },
          current,
        ),
      )
    },
    [setEdges, tr],
  )

  const inspectFile = useCallback(
    async (file: File) => {
      setBusy('structure')
      updateNode('structure.upload', 'running', tr(`正在读取 ${file.name}`, `Reading ${file.name}`))
      updateNode(
        'structure.inspect',
        'running',
        tr('CatEx 正在进行只读检查', 'CatEx is running a read-only inspection'),
      )
      try {
        let structureFile = file
        if (file.name.toLowerCase().endsWith('.cif')) {
          const converted = await api.convertCifToPoscar(file.name, await readSmallTextFile(file))
          structureFile = new File([converted.poscar_text], 'POSCAR', { type: 'text/plain' })
          if (workDirectory) {
            await writeWorkspaceFile(workDirectory, 'POSCAR', converted.poscar_text)
            setWorkFileSources((current) => ({ ...current, poscar: `${file.name} → POSCAR` }))
          }
        }
        let payload: StructureInspectionResponse
        if (currentProject) {
          const artifact = await api.addProjectStructure(currentProject.project_id, structureFile)
          payload = projectArtifactInspection(artifact)
          setArtifacts((current) => [artifact, ...current.filter((item) => item.artifact_id !== artifact.artifact_id)])
          setActiveStructureArtifactId(artifact.artifact_id)
          localStorage.setItem(
            `${ACTIVE_STRUCTURE_STORAGE_PREFIX}${currentProject.project_id}`,
            artifact.artifact_id,
          )
          const refreshed = await api.projects()
          setProjects(refreshed)
          setCurrentProject(
            refreshed.find((item) => item.project_id === currentProject.project_id) ?? currentProject,
          )
        } else {
          payload = await api.inspectStructure(structureFile)
        }
        setStructure(payload)
        setPoscarSource(await structureFile.text())
        setWorkFileSources((current) => ({ ...current, poscar: current.poscar || structureFile.name }))
        setStructureReady(payload.inspection.status !== 'error')
        setResult(null)
        setResultReviewed(false)
        updateNode(
          'structure.upload',
          'success',
          `${file.name}${structureFile !== file ? ' → POSCAR' : ''} · ${payload.retained ? '已保存到项目' : '临时检查后不保留'}`,
        )
        const inspectionStatus: RuntimeStatus =
          payload.inspection.status === 'error'
            ? 'blocked'
            : payload.inspection.status === 'warning'
              ? 'warning'
              : 'success'
        updateNode(
          'structure.inspect',
          inspectionStatus,
          payload.inspection.record
            ? `${payload.inspection.record.reduced_formula} · ${payload.inspection.record.num_sites} atoms`
            : tr('结构无法解析', 'Structure could not be parsed'),
        )
        setSelectedNodeId('node-2')
        setNotice({
          tone: payload.inspection.status === 'error' ? 'error' : 'success',
          message: payload.inspection.record
            ? payload.retained
              ? tr(
                  `已检查 ${file.name}${structureFile !== file ? ' 并转换为 POSCAR' : ''}，并保存到项目 ${currentProject?.title}。`,
                  `${file.name} was inspected${structureFile !== file ? ' and converted to POSCAR' : ''}, then saved to project ${currentProject?.title}.`,
                )
              : tr(
                  `已完成 ${file.name} 的只读检查，源内容未持久化。`,
                  `${file.name} was inspected read-only; its source was not persisted.`,
                )
            : tr('文件已读取，但结构解析失败。', 'The file was read, but structure parsing failed.'),
        })
        return true
      } catch (error) {
        updateNode('structure.upload', 'blocked', tr('上传被拒绝', 'Upload rejected'))
        updateNode('structure.inspect', 'blocked', tr('没有可检查的结构', 'No inspectable structure'))
        setNotice({
          tone: 'error',
          message: error instanceof Error ? error.message : tr('结构检查失败。', 'Structure inspection failed.'),
        })
        return false
      } finally {
        setBusy(null)
      }
    },
    [currentProject, tr, updateNode, workDirectory],
  )

  const selectWorkDirectory = useCallback(async () => {
    const picker = (window as unknown as {
      showDirectoryPicker?: (options: { mode: 'readwrite' }) => Promise<WorkspaceDirectoryHandle>
    }).showDirectoryPicker
    if (!picker) {
      setNotice({
        tone: 'error',
        message: tr('当前浏览器不支持工作文件夹访问；请使用随 CatEx 启动的 Chromium/Edge。', 'This browser does not support work-folder access; use the Chromium/Edge browser launched with CatEx.'),
      })
      return
    }
    try {
      const directory = await picker({ mode: 'readwrite' })
      const files = new Map<string, File>()
      for await (const entry of directory.values()) {
        if (entry.kind === 'file') files.set(entry.name.toLowerCase(), await entry.getFile())
      }
      setWorkDirectory(directory)
      const sources: Record<InputFileKey, string> = { poscar: '', incar: '', kpoints: '', potcar: '', slurm: '' }
      const errors: string[] = []
      const poscar = files.get('poscar') ?? files.get('contcar') ?? [...files.values()].find((item) => /\.(poscar|vasp)$/i.test(item.name))
      const cif = [...files.values()].find((item) => item.name.toLowerCase().endsWith('.cif'))
      if (poscar) {
        if (await inspectFile(poscar)) sources.poscar = poscar.name
        else errors.push(tr('POSCAR：结构检查失败', 'POSCAR: structure inspection failed'))
      } else if (cif) {
        try {
          const converted = await api.convertCifToPoscar(cif.name, await readSmallTextFile(cif))
          if (await inspectFile(new File([converted.poscar_text], 'POSCAR', { type: 'text/plain' }))) {
            await writeWorkspaceFile(directory, 'POSCAR', converted.poscar_text)
            sources.poscar = `${cif.name} → POSCAR`
          } else errors.push(tr('CIF：转换后的 POSCAR 检查失败', 'CIF: converted POSCAR inspection failed'))
        } catch (error) {
          errors.push(`CIF: ${error instanceof Error ? error.message : tr('无法转换', 'could not be converted')}`)
        }
      }

      let parsedIncar: ReturnType<typeof parseIncarFile> | undefined
      let parsedKpoints: ReturnType<typeof parseKpointsFile> | undefined
      let parsedPotcar: ReturnType<typeof parsePotcarMetadataFile> | undefined
      let parsedSlurm: ReturnType<typeof parseSlurmScriptFile> | undefined
      const incar = files.get('incar')
      if (incar) {
        try {
          parsedIncar = parseIncarFile(await readSmallTextFile(incar))
          sources.incar = incar.name
        } catch (error) {
          errors.push(`INCAR: ${error instanceof Error ? error.message : tr('无法解析', 'could not be parsed')}`)
        }
      }
      const kpoints = files.get('kpoints')
      if (kpoints) {
        try {
          parsedKpoints = parseKpointsFile(await readSmallTextFile(kpoints))
          sources.kpoints = kpoints.name
        } catch (error) {
          errors.push(`KPOINTS: ${error instanceof Error ? error.message : tr('无法解析', 'could not be parsed')}`)
        }
      }
      const potcarMetadata = files.get('potcar-metadata.json') ?? files.get('catex-potcar-metadata.json')
      if (potcarMetadata) {
        try {
          parsedPotcar = parsePotcarMetadataFile(await readSmallTextFile(potcarMetadata))
        } catch (error) {
          errors.push(`POTCAR metadata: ${error instanceof Error ? error.message : tr('无法解析', 'could not be parsed')}`)
        }
      }
      if (files.has('potcar')) sources.potcar = 'POTCAR (detected; content not read)'
      setLocalPotcarReceipt(files.has('potcar') ? { filename: 'POTCAR' } : null)
      const slurm = files.get('run.slurm') ?? files.get('submit.slurm') ?? files.get('slurm.sh') ?? [...files.values()].find((item) => item.name.toLowerCase().endsWith('.slurm'))
      if (slurm) {
        try {
          parsedSlurm = parseSlurmScriptFile(await readSmallTextFile(slurm))
          sources.slurm = slurm.name
        } catch (error) {
          errors.push(`Slurm: ${error instanceof Error ? error.message : tr('无法解析', 'could not be parsed')}`)
        }
      }

      if ((parsedIncar || parsedKpoints || parsedPotcar || parsedSlurm) && !calculationConfig) {
        errors.push(tr('当前计算配置 JSON 无效，其他输入未合并', 'the current calculation JSON is invalid, so other inputs were not merged'))
      } else if (parsedIncar || parsedKpoints || parsedPotcar || parsedSlurm) {
        mutateCalculationConfig((config) => {
          const protocol = config.protocol as { incar: Record<string, string>; kpoints: unknown }
          if (parsedIncar) protocol.incar = parsedIncar
          if (parsedKpoints) protocol.kpoints = parsedKpoints
          if (parsedPotcar) config.potcar_metadata = parsedPotcar as unknown as Record<string, unknown>
          if (parsedSlurm) applyImportedSlurmProfile(config, parsedSlurm)
        })
      }
      setImportedInputNames({
        incar: parsedIncar ? incar?.name ?? '' : '',
        kpoints: parsedKpoints ? kpoints?.name ?? '' : '',
        potcar: parsedPotcar ? potcarMetadata?.name ?? '' : '',
      })
      setWorkFileSources(sources)
      const loaded = Object.entries(sources)
        .filter(([, value]) => Boolean(value))
        .map(([key, value]) => `${key.toUpperCase()}: ${value}`)
      setNotice({
        tone: errors.length ? 'warning' : 'success',
        message: tr(
          `已读取工作文件夹 ${directory.name}；自动载入 ${loaded.join('、') || '0 类输入'}。${errors.length ? ` 未载入：${errors.join('；')}` : ''}`,
          `Opened work folder ${directory.name}; auto-loaded ${loaded.join(', ') || '0 input types'}.${errors.length ? ` Not loaded: ${errors.join('; ')}` : ''}`,
        ),
      })
    } catch (error) {
      if ((error as { name?: string }).name === 'AbortError') return
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : tr('工作文件夹读取失败。', 'Failed to read the work folder.') })
    }
  }, [calculationConfig, inspectFile, mutateCalculationConfig, tr])

  const applyStructureConstraints = useCallback(async () => {
    if (!selectiveDynamicsEnabled) {
      setNotice({ tone: 'warning', message: tr('请先勾选启用原子约束。', 'Enable atom constraints first.') })
      return
    }
    if (!poscarSource) {
      setNotice({ tone: 'error', message: tr('请先导入 POSCAR 或 CIF。', 'Import a POSCAR or CIF first.') })
      return
    }
    if (constraintPreview.error) {
      setNotice({ tone: 'error', message: tr(`当前约束选择无效：${constraintPreview.error}`, `Invalid constraint selection: ${constraintPreview.error}`) })
      return
    }
    try {
      const response = await api.applySelectiveDynamics({
        poscar_text: poscarSource,
        strategy: constraintStrategy,
        mobile_indices_1based: constraintStrategy === 'adsorbate_indices' ? parseAtomIndices(mobileAtomText) : [],
        bottom_layer_count: bottomLayerCount,
        layer_tolerance_angstrom: layerTolerance,
      })
      if (workDirectory) await writeWorkspaceFile(workDirectory, 'POSCAR', response.poscar_text)
      await inspectFile(new File([response.poscar_text], 'POSCAR', { type: 'text/plain' }))
      setConstraintSummary(tr(
        `固定 ${response.fixed_count} 个原子，放开 ${response.mobile_count} 个原子。`,
        `${response.fixed_count} atoms fixed and ${response.mobile_count} atoms mobile.`,
      ))
      setNotice({ tone: 'success', message: tr('已写入 Selective dynamics 标记并重新检查 POSCAR。', 'Selective-dynamics flags were applied and the POSCAR was re-inspected.') })
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : tr('原子固定设置失败。', 'Failed to apply atom constraints.') })
    }
  }, [bottomLayerCount, constraintPreview.error, constraintStrategy, inspectFile, layerTolerance, mobileAtomText, poscarSource, selectiveDynamicsEnabled, tr, workDirectory])

  const handleConstraintAtomClick = useCallback((index1Based: number) => {
    setFocusedConstraintAtom(index1Based)
    if (selectiveDynamicsEnabled && constraintStrategy === 'adsorbate_indices') {
      setMobileAtomText((current) => toggleAtomIndex(current, index1Based))
    }
  }, [constraintStrategy, selectiveDynamicsEnabled])

  const importStructureReplacement = useCallback((file: File) => {
    if (workFileSources.poscar && !window.confirm(tr(
      `当前 POSCAR 来自 ${workFileSources.poscar}。是否替换？`,
      `The current POSCAR came from ${workFileSources.poscar}. Replace it?`,
    ))) return
    void inspectFile(file)
  }, [inspectFile, tr, workFileSources.poscar])

  const loadSyntheticStructure = useCallback(() => {
    const file = new File([SYNTHETIC_POSCAR], 'POSCAR', { type: 'text/plain' })
    void inspectFile(file)
  }, [inspectFile])

  const runSyntheticWorkflow = useCallback(async () => {
    if (!structureReady) {
      setNotice({
        tone: 'error',
        message: tr(
          '请先上传一个通过自动诊断的有效结构。',
          'Upload a valid structure that passes automatic diagnostics first.',
        ),
      })
      return
    }
    setBusy('workflow')
    setResultReviewed(false)
    try {
      const validation = await api.validateWorkflow(buildValidationRequest(nodes, edges))
      if (!validation.valid) {
        setNotice({
          tone: 'error',
          message: tr(
            `工作流未通过后端校验：${selectActionableDiagnostic(validation.diagnostics)?.message ?? '未知错误'}`,
            `Backend workflow validation failed: ${selectActionableDiagnostic(validation.diagnostics)?.message ?? 'unknown error'}`,
          ),
        })
        return
      }
      updateNode('hpc.connect', 'warning', tr('合成流程不连接超算', 'The synthetic flow does not connect to HPC'))
      updateNode('slurm.plan', 'running', tr('准备合成计划', 'Preparing the synthetic plan'))
      updateNode('slurm.submit', 'running', tr('合成执行中', 'Synthetic execution in progress'))
      const payload = await api.demoVaspOutput()
      setResult(payload)
      updateNode('vasp.validate.auto', 'warning', tr('合成示例输入已自动诊断', 'Synthetic inputs diagnosed automatically'))
      updateNode('results.summarize', payload.scientifically_complete ? 'success' : 'warning', tr('结果已自动汇总', 'Results summarized automatically'))
      updateNode(
        'slurm.plan',
        'warning',
        tr('未生成或提交真实 Slurm 脚本', 'No real Slurm script was generated or submitted'),
      )
      updateNode(
        'slurm.submit',
        'success',
        tr('Mock 完成 · 未执行任何命令', 'Mock complete · no command executed'),
      )
      updateNode(
        'vasp.parse',
        payload.scientifically_complete ? 'success' : 'warning',
        `${payload.status} · ${payload.detected_vasp_version ?? tr('版本未知', 'unknown version')}`,
      )
      updateNode('review.result', 'review', tr('等待 POC 人工结果审核', 'Waiting for POC result review'))
      setSelectedNodeId('node-7')
      setNotice({
        tone: 'success',
        message: tr(
          '合成结果已由 CatEx 解析；没有连接 HPC，也没有运行 VASP。',
          'CatEx parsed the synthetic result without connecting to HPC or running VASP.',
        ),
      })
    } catch (error) {
      updateNode('slurm.submit', 'blocked', tr('合成流程失败', 'Synthetic workflow failed'))
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('合成流程失败。', 'Synthetic workflow failed.'),
      })
    } finally {
      setBusy(null)
    }
  }, [edges, nodes, structureReady, tr, updateNode])

  const reviewResult = useCallback(async (accepted: boolean) => {
    if (!result) return
    if (!remoteResult) {
      setResultReviewed(true)
      setResultDecision('rejected')
      updateNode(
        'review.result',
        'success',
        tr('POC 审核完成 · 永久不可用于科研', 'POC review complete · permanently ineligible for science'),
      )
      setNotice({
        tone: 'warning',
        message: tr(
          '已记录 POC 结果审核演示；scientific_result_eligible 仍为 false。',
          'The POC result-review demo was recorded; scientific_result_eligible remains false.',
        ),
      })
      return
    }
    if (!currentProject) return
    setBusy('result-review')
    try {
      const response = await api.reviewResult(
        currentProject.project_id,
        remoteResult.run_id,
        accepted,
        reviewer,
        reviewNote,
      )
      setResultReviewed(true)
      setResultDecision(response.decision)
      if (accepted) {
        setReviewedEnergies(await api.reviewedEnergies(currentProject.project_id))
      }
      setNotice({
        tone: accepted ? 'success' : 'warning',
        message: accepted
          ? tr(
              '科学结果已人工接受，并绑定为可审计 reviewed energy。',
              'The scientific result was accepted and bound as an auditable reviewed energy.',
            )
          : tr(
              '科学结果已人工拒绝；不会进入能量推导。',
              'The scientific result was rejected and will not enter energy derivation.',
            ),
      })
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('结果审核失败。', 'Result review failed.'),
      })
    } finally {
      setBusy(null)
    }
  }, [currentProject, remoteResult, result, reviewNote, reviewer, tr, updateNode])

  const deriveEnergy = useCallback(async () => {
    if (!currentProject) return
    setBusy('energy-derive')
    try {
      const coefficients = JSON.parse(coefficientText) as Record<string, number>
      const response = await api.deriveEnergy(
        currentProject.project_id,
        derivationId,
        coefficients,
        confirmDerivationWrite,
      )
      setEnergyDerivation(response)
      setNotice({
        tone: response.status === 'derived' ? 'success' : 'warning',
        message: response.status === 'derived'
          ? tr(
              '同 energy family 的线性能量组合已生成并保存；尚未赋予吸附能或自由能科学解释。',
              'A linear combination within one energy family was generated and saved without assigning adsorption-energy or free-energy meaning.',
            )
          : selectActionableDiagnostic(response.diagnostics)?.message ??
            tr('能量组合被兼容性门禁阻断。', 'The energy combination was blocked by compatibility gates.'),
      })
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('能量推导失败。', 'Energy derivation failed.'),
      })
    } finally {
      setBusy(null)
    }
  }, [coefficientText, confirmDerivationWrite, currentProject, derivationId, tr])

  const calculateThermochemistry = useCallback(async () => {
    if (!result?.vibrations) return
    setBusy('thermochemistry')
    try {
      const response = await api.harmonicThermochemistry(
        result.vibrations.modes.map((mode) => ({
          wavenumber_cm1: mode['wavenumber_cm-1'],
          energy_mev: mode.energy_meV,
          imaginary: mode.imaginary,
        })),
        Number(thermoTemperature),
        Number(thermoCutoff),
      )
      setThermochemistry(response)
      setNotice({ tone: response.warnings.length ? 'warning' : 'success', message: tr('振动热化学校正已更新。', 'Vibrational thermochemistry was updated.') })
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : tr('热化学校正失败。', 'Thermochemistry failed.') })
    } finally {
      setBusy(null)
    }
  }, [result, thermoCutoff, thermoTemperature, tr])

  const bindReactionResult = useCallback((stateKey: string, runId: string) => {
    setReactionBindings((current) => ({ ...current, [stateKey]: runId }))
    const selected = calculationResults.find((item) => item.run_id === runId)
    if (selected?.energy_eV != null) {
      setReactionEnergies((current) => ({ ...current, [stateKey]: String(selected.energy_eV) }))
    }
    setReactionAnalysis(null)
  }, [calculationResults])

  const calculateReactionAnalysis = useCallback(async () => {
    if (!activeReactionTemplate) return
    setBusy('reaction-analysis')
    try {
      const states = Object.fromEntries(activeReactionTemplate.state_keys.map((key) => {
        const bound = calculationResults.find((item) => item.run_id === reactionBindings[key])
        return [key, {
          energy_eV: Number(reactionEnergies[key]),
          correction_eV: Number(reactionCorrections[key] ?? 0),
          ...(bound ? { run_id: bound.run_id, energy_family_id: bound.energy_family_id ?? undefined } : {}),
        }]
      }))
      const response = await api.analyzeReaction({
        template_id: reactionTemplateId,
        states,
        h2_free_energy_eV: Number(h2Energy),
        ...(reactionTemplateId === 'oer-aem-che' ? { h2o_free_energy_eV: Number(h2oEnergy) } : {}),
        oer_equilibrium_free_energy_eV: 4.92,
        temperature_kelvin: Number(reactionTemperature),
        potential_volts: Number(reactionPotential),
        pH: Number(reactionPh),
        reference_electrode: referenceElectrode,
      })
      setReactionAnalysis(response)
      setNotice({ tone: 'success', message: tr('反应自由能和台阶图已更新。', 'Reaction free energies and the step diagram were updated.') })
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : tr('反应分析失败。', 'Reaction analysis failed.') })
    } finally {
      setBusy(null)
    }
  }, [activeReactionTemplate, calculationResults, h2Energy, h2oEnergy, reactionBindings, reactionCorrections, reactionEnergies, reactionPh, reactionPotential, reactionTemperature, reactionTemplateId, referenceElectrode, tr])

  const saveWorkflow = useCallback(async () => {
    const payload: SavedWorkflow = {
      schema_version: 'catex.web-local-workflow.v1',
      nodes,
      edges,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
    if (currentProject) {
      try {
        await api.saveProjectWorkflow(currentProject.project_id, buildValidationRequest(nodes, edges))
        const refreshed = await api.projects()
        setProjects(refreshed)
        setCurrentProject(
          refreshed.find((project) => project.project_id === currentProject.project_id) ??
            currentProject,
        )
        setNotice({
          tone: 'success',
          message: tr('工作流已持久化到当前 CatEx 项目。', 'The workflow was persisted to the current CatEx project.'),
        })
        return
      } catch (error) {
        setNotice({
          tone: 'error',
          message: error instanceof Error ? error.message : tr('项目工作流保存失败。', 'Failed to save the project workflow.'),
        })
        return
      }
    }
    setNotice({
      tone: 'success',
      message: tr('工作流布局已保存在当前浏览器。', 'The workflow layout was saved in this browser.'),
    })
  }, [currentProject, edges, nodes, tr])

  const createProject = useCallback(async () => {
    setBusy('project')
    try {
      const created = await api.createProject({
        title: projectTitle,
        purpose: projectPurpose,
        description: tr(
          '由 CatEx Workbench 创建的全流程项目。',
          'An end-to-end project created by CatEx Workbench.',
        ),
      })
      const refreshed = await api.projects()
      setProjects(refreshed)
      setCurrentProject(created)
      setActiveView('workflow')
      setNotice({
        tone: 'success',
        message: tr(
          `项目“${created.title}”已创建并持久化。`,
          `Project “${created.title}” was created and persisted.`,
        ),
      })
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('项目创建失败。', 'Project creation failed.'),
      })
    } finally {
      setBusy(null)
    }
  }, [projectPurpose, projectTitle, tr])

  const createPaper4Project = useCallback(async () => {
    setBusy('project')
    try {
      const created = await api.createPaper4Project()
      const refreshed = await api.projects()
      setProjects(refreshed)
      setCurrentProject(created)
      setNotice({
        tone: 'warning',
        message: tr(
          'Paper 4 验收项目已创建；10 个生产就绪阻断项被原样保留，未授权计算。',
          'The Paper 4 acceptance project was created with all 10 production-readiness blockers preserved; no calculation is authorized.',
        ),
      })
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('验收项目创建失败。', 'Failed to create the acceptance project.'),
      })
    } finally {
      setBusy(null)
    }
  }, [tr])

  const selectProject = useCallback((project: ProjectRecord) => {
    setCurrentProject(project)
    setStructureReady(false)
    setResult(null)
    setResultReviewed(false)
    setNotice({
      tone: 'neutral',
      message: tr(`已打开项目“${project.title}”。`, `Opened project “${project.title}”.`),
    })
  }, [tr])

  const resetWorkflow = useCallback(() => {
    if (!templateResponse || registry.size === 0) return
    localStorage.removeItem(STORAGE_KEY)
    loadTemplate(templateResponse, registry, false)
    setStructure(null)
    setPoscarSource('')
    setImportedInputNames({ incar: '', kpoints: '', potcar: '' })
    setResult(null)
    setStructureReady(false)
    setResultReviewed(false)
    setNotice({
      tone: 'neutral',
      message: tr('已恢复只读 POC 默认模板。', 'The read-only default POC template was restored.'),
    })
  }, [loadTemplate, registry, templateResponse, tr])

  const validateCurrentWorkflow = useCallback(async () => {
    try {
      const validation = await api.validateWorkflow(buildValidationRequest(nodes, edges))
      setNotice({
        tone: validation.valid ? 'success' : 'error',
        message: validation.valid
          ? tr(
              '后端已确认节点身份、端口类型、必需输入和 DAG 拓扑。',
              'The backend confirmed node identities, port types, required inputs, and DAG topology.',
            )
          : selectActionableDiagnostic(validation.diagnostics)?.message ?? tr('工作流校验失败。', 'Workflow validation failed.'),
      })
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('校验失败。', 'Validation failed.'),
      })
    }
  }, [edges, nodes, tr])

  const parseCalculationConfig = useCallback((): CalculationConfig => {
    const payload = JSON.parse(calculationConfigText) as CalculationConfig
    if (payload.schema_version !== 'catex.web-calculation-config.v1') {
      throw new Error(
        tr(
          '计算配置 schema_version 不正确。',
          'The calculation configuration schema_version is invalid.',
        ),
      )
    }
    return payload
  }, [calculationConfigText, tr])

  const saveCalculationConfig = useCallback(async () => {
    if (!currentProject) {
      setNotice({ tone: 'error', message: tr('请先创建或打开一个项目。', 'Create or open a project first.') })
      return
    }
    setBusy('protocol')
    try {
      const response = await api.saveCalculationConfig(currentProject.project_id, parseCalculationConfig())
      setCalculationPlan(null)
      setMaterialization(null)
      setNotice({
        tone: 'success',
        message: tr(
          `计算协议已校验并保存，修订 ${shortenHash(response.revision_sha256)}。`,
          `The calculation protocol was validated and saved as revision ${shortenHash(response.revision_sha256)}.`,
        ),
      })
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('协议保存失败。', 'Failed to save the protocol.'),
      })
    } finally {
      setBusy(null)
    }
  }, [currentProject, parseCalculationConfig, tr])

  const prepareCalculationRun = useCallback(async (configOverride?: CalculationConfig) => {
    const config = configOverride ?? calculationConfig
    const execution = config?.execution_profile as Record<string, unknown> | undefined
    const protocol = config?.protocol as {
      incar?: Record<string, string>
      kpoints?: Record<string, unknown>
    } | undefined
    const potcarMetadata = config?.potcar_metadata as
      | { potential_family?: string; datasets?: Array<Record<string, unknown>> }
      | undefined
    const remoteName = String(execution?.job_name ?? '')
    const missing: string[] = []
    if (!currentProject) missing.push(tr('项目', 'project'))
    if (!workDirectory) missing.push(tr('工作文件夹', 'work folder'))
    if (!poscarSource || !latestStructureArtifact) missing.push('POSCAR')
    if (!Object.keys(protocol?.incar ?? {}).length) missing.push('INCAR')
    if (!protocol?.kpoints) missing.push('KPOINTS')
    if (!potcarMetadata?.datasets?.length) {
      missing.push(tr('POTCAR 元数据（先执行超算只读探测）', 'POTCAR metadata (run the read-only HPC probe first)'))
    } else if (!potcarMetadataMatchesSpecies(potcarMetadata, expectedPotcarSpeciesOrder)) {
      missing.push(tr(
        `POTCAR 元数据顺序（需要 ${expectedPotcarSpeciesOrder.join(' → ') || 'POSCAR 元素顺序'}）`,
        `POTCAR metadata order (expected ${expectedPotcarSpeciesOrder.join(' → ') || 'POSCAR species order'})`,
      ))
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(remoteName)) missing.push(tr('远端项目名称', 'remote project name'))
    if (!hpcConnected) missing.push(tr('超算只读连接', 'read-only HPC connection'))
    if (missing.length) {
      throw new Error(tr(`还不能继续，请补齐：${missing.join('、')}。`, `Cannot continue yet. Complete: ${missing.join(', ')}.`))
    }
    await writeWorkspaceFile(workDirectory!, 'POSCAR', poscarSource)
    await writeWorkspaceFile(workDirectory!, 'INCAR', serializeIncar(config))
    await writeWorkspaceFile(workDirectory!, 'KPOINTS', serializeKpoints(config))
    await api.saveCalculationConfig(currentProject!.project_id, config!)
    setCalculationConfigText(JSON.stringify(config, null, 2))
    let response = await api.planCalculation(currentProject!.project_id, latestStructureArtifact!.artifact_id)
    if (!response.resolution.resolved) {
      throw new Error(diagnosticMessage(selectActionableDiagnostic(response.resolution.diagnostics)) || tr('VASP 输入诊断未通过。', 'VASP input diagnostics failed.'))
    }
    await api.approveProtocol(
      currentProject!.project_id,
      latestStructureArtifact!.artifact_id,
      reviewer || 'local-user',
      tr('用户已确认校验后的输入可以进入受控运行生命周期。', 'The user confirmed that the validated inputs can enter the controlled run lifecycle.'),
    )
    response = await api.planCalculation(currentProject!.project_id, latestStructureArtifact!.artifact_id)
    if (!response.plan) throw new Error(tr('后端未生成计算计划。', 'The backend did not produce a calculation plan.'))
    let refreshedRuns = await api.projectRuns(currentProject!.project_id)
    let preparedRun = refreshedRuns.find((run) => run.run_id === response.plan!.job_name)
    let materialized: MaterializationResponse | null = null
    if (preparedRun && preparedRun.plan_sha256 !== response.plan.plan_sha256) {
      throw new Error(tr(
        `远端项目名称 ${remoteName} 已用于另一份输入；请更换项目名称。`,
        `Remote project name ${remoteName} is already bound to different inputs; choose another name.`,
      ))
    }
    const reusedExistingRun = canResumeExistingRun(response.plan, preparedRun)
    if (!response.plan.ready_for_materialization && !reusedExistingRun) {
      const diagnostics = preparedRun
        ? response.plan.diagnostics.filter((item) => item.code !== 'MATERIALIZATION_DESTINATION_EXISTS')
        : response.plan.diagnostics
      throw new Error(diagnosticMessage(selectActionableDiagnostic(diagnostics)) || tr('计算输入仍有阻断项。', 'The calculation inputs still contain blockers.'))
    }
    if (!preparedRun) {
      materialized = await api.materializeCalculation(
        currentProject!.project_id,
        latestStructureArtifact!.artifact_id,
        response.plan.plan_sha256,
        true,
      )
      refreshedRuns = await api.projectRuns(currentProject!.project_id)
      preparedRun = refreshedRuns.find((run) => run.run_id === response.plan!.job_name)
    }
    if (!preparedRun) throw new Error(tr('未能恢复刚刚生成的本地运行。', 'Could not restore the newly materialized local run.'))
    setCalculationPlan(response)
    setMaterialization(materialized)
    setRuns(refreshedRuns)
    setSelectedRunId(preparedRun.run_id)
    updateNode('vasp.validate.auto', 'success', tr('INCAR、POSCAR、KPOINTS 与 POTCAR 元数据已通过诊断', 'INCAR, POSCAR, KPOINTS, and POTCAR metadata passed diagnostics'))
    updateNode(
      'slurm.plan',
      'success',
      reusedExistingRun
        ? tr('同一计划的已有运行已安全恢复', 'The existing run for the identical plan was safely resumed')
        : tr('提交脚本已生成并通过静态校验', 'The submission script was generated and statically validated'),
    )
    return { remoteName, run: preparedRun, reusedExistingRun }
  }, [calculationConfig, currentProject, diagnosticMessage, expectedPotcarSpeciesOrder, hpcConnected, latestStructureArtifact, poscarSource, reviewer, tr, updateNode, workDirectory])

  const continueToRunCenter = useCallback(async () => {
    setBusy('continue')
    try {
      const { remoteName, run, reusedExistingRun } = await prepareCalculationRun()
      setActiveView('runs')
      setNotice({
        tone: 'success',
        message: reusedExistingRun
          ? run.submitted
            ? tr(
                `已恢复同一计划的运行 ${remoteName}；作业 ${run.job_id ?? ''} 已提交，不会重复提交。`,
                `Resumed the identical run ${remoteName}; job ${run.job_id ?? ''} is already submitted and will not be submitted again.`,
              )
            : tr(
                `已恢复同一计划的运行 ${remoteName}，可在运行中心继续未完成的步骤。`,
                `Resumed the identical run ${remoteName}; continue its unfinished steps in Run Center.`,
              )
          : tr(
              `输入完整，已保存 POSCAR/INCAR/KPOINTS 并准备远端项目 ${remoteName}。下一步在运行中心上传和提交。`,
              `Inputs are complete. POSCAR/INCAR/KPOINTS were saved and remote project ${remoteName} is ready for staging in Run Center.`,
            ),
      })
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : tr('进入下一步失败。', 'Failed to continue.') })
    } finally {
      setBusy(null)
    }
  }, [prepareCalculationRun, tr])

  const updateHpcProfile = useCallback(
    <K extends keyof HpcProfile>(field: K, value: HpcProfile[K]) => {
      setHpcProfile((current) => ({ ...current, [field]: value }))
      setHpcConnected(false)
    },
    [],
  )

  const probeHpc = useCallback(async () => {
    setBusy('hpc-probe')
    try {
      const response = await api.probeHpc(hpcProfile)
      setHpcConnected(response.connected)
      updateNode('hpc.connect', 'success', tr('SSH、远端根目录和 POTCAR 构建器已只读验证', 'SSH, remote root, and POTCAR builder verified read-only'))
      setNotice({
        tone: 'success',
        message: tr(
          'SSH/SFTP 只读探测成功；密钥路径和连接参数未持久化。',
          'The read-only SSH/SFTP probe succeeded; the key path and connection parameters were not persisted.',
        ),
      })
    } catch (error) {
      setHpcConnected(false)
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('HPC 探测失败。', 'HPC probe failed.'),
      })
    } finally {
      setBusy(null)
    }
  }, [hpcProfile, tr, updateNode])

  const fetchRemotePotcarMetadata = useCallback(async (): Promise<RemotePotcarMetadata> => {
    const labels = (potcarLabelText.trim() ? potcarLabelText.split(/[\s,]+/) : expectedPotcarSpeciesOrder).filter(Boolean)
    if (!hpcConnected || !labels.length) {
      throw new Error(tr('请先连接超算并确认 POSCAR 元素顺序。', 'Connect HPC and confirm the POSCAR species order first.'))
    }
    return api.remotePotcarMetadata(hpcProfile, labels)
  }, [expectedPotcarSpeciesOrder, hpcConnected, hpcProfile, potcarLabelText, tr])

  const applyRemotePotcarMetadata = useCallback((metadata: RemotePotcarMetadata): CalculationConfig => {
    if (!calculationConfig) throw new Error(tr('当前计算配置 JSON 无效。', 'The current calculation configuration JSON is invalid.'))
    const nextConfig = JSON.parse(JSON.stringify(calculationConfig)) as CalculationConfig
    nextConfig.potcar_metadata = {
      schema_version: metadata.schema_version,
      potential_family: metadata.potential_family,
      datasets: metadata.datasets,
    }
    setCalculationConfigText(JSON.stringify(nextConfig, null, 2))
    setCalculationPlan(null)
    setMaterialization(null)
    setImportedInputNames((current) => ({ ...current, potcar: tr('超算只读元数据', 'HPC read-only metadata') }))
    return nextConfig
  }, [calculationConfig, tr])

  const probeRemotePotcarMetadata = useCallback(async () => {
    setBusy('potcar-probe')
    try {
      const metadata = await fetchRemotePotcarMetadata()
      applyRemotePotcarMetadata(metadata)
      setNotice({
        tone: 'success',
        message: tr(
          `已从超算只读提取 ${metadata.datasets.length} 个 POTCAR 数据集的标题、ENMAX 与哈希；原始内容未返回浏览器。`,
          `Read title, ENMAX, and hashes for ${metadata.datasets.length} POTCAR datasets; raw content was not returned to the browser.`,
        ),
      })
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : tr('远端 POTCAR 探测失败。', 'Remote POTCAR probe failed.') })
    } finally {
      setBusy(null)
    }
  }, [applyRemotePotcarMetadata, fetchRemotePotcarMetadata, tr])

  const buildAndCopyRemotePotcar = useCallback(async (
    run: RunSummary,
    approvedRemoteWrite: boolean,
  ) => {
    if (!currentProject) throw new Error(tr('请先打开项目。', 'Open a project first.'))
    if (!workDirectory) throw new Error(tr('请先选择本地工作文件夹。', 'Choose a local work folder first.'))
    if (!run.potcar_materialized && !run.submitted) {
      await api.stageRemoteRun(
        currentProject.project_id,
        hpcProfile,
        run.run_id,
        run.plan_sha256,
        approvedRemoteWrite,
      )
      setHpcStaged(true)
      const stagedRuns = await api.projectRuns(currentProject.project_id)
      setRuns(stagedRuns)
    }
    if (localPotcarReceipt && !window.confirm(tr(
      '本地工作文件夹中已有 POTCAR。是否用超算生成并校验哈希的 POTCAR 替换？',
      'The local work folder already contains POTCAR. Replace it with the hash-verified HPC copy?',
    ))) return null
    const potcar = await api.copyRemotePotcar(currentProject.project_id, hpcProfile, run.run_id)
    const binary = atob(potcar.content_base64)
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0))
    await writeWorkspaceFile(workDirectory, 'POTCAR', new Blob([bytes], { type: 'application/octet-stream' }))
    setLocalPotcarReceipt({ filename: potcar.filename, sha256: potcar.sha256 })
    setWorkFileSources((current) => ({ ...current, potcar: `POTCAR · ${shortenHash(potcar.sha256)}` }))
    setHpcStaged(true)
    updateNode('slurm.submit', 'running', tr('远端输入和 POTCAR 已就绪，等待提交', 'Remote inputs and POTCAR are ready; awaiting submission'))
    return potcar
  }, [currentProject, hpcProfile, localPotcarReceipt, tr, updateNode, workDirectory])

  const generatePotcarFromProtocol = useCallback(async () => {
    const remoteName = String((calculationConfig?.execution_profile as Record<string, unknown> | undefined)?.job_name ?? '')
    if (!window.confirm(tr(
      `将为项目 ${remoteName || '（尚未命名）'} 准备 POTCAR；若同一计划已经存在，则安全恢复并下载现有 POTCAR，否则新建远端目录并生成。不会新提交 Slurm 作业。是否继续？`,
      `This will prepare POTCAR for ${remoteName || '(unnamed)'}. An identical existing run will be safely resumed and its POTCAR downloaded; otherwise a new remote directory is created. No new Slurm job will be submitted. Continue?`,
    ))) return
    setBusy('potcar-build')
    try {
      const metadata = await fetchRemotePotcarMetadata()
      const nextConfig = applyRemotePotcarMetadata(metadata)
      if (!potcarMetadataMatchesSpecies(nextConfig.potcar_metadata as { datasets?: Array<Record<string, unknown>> }, expectedPotcarSpeciesOrder)) {
        throw new Error(tr(
          `超算返回的势函数顺序与 POSCAR 不一致；需要 ${expectedPotcarSpeciesOrder.join(' → ')}。`,
          `The HPC potential order does not match POSCAR; expected ${expectedPotcarSpeciesOrder.join(' → ')}.`,
        ))
      }
      const { run } = await prepareCalculationRun(nextConfig)
      const copied = await buildAndCopyRemotePotcar(run, true)
      if (!copied) {
        setNotice({
          tone: 'warning',
          message: tr('远端 POTCAR 已生成，但按你的选择没有替换本地文件。', 'Remote POTCAR was built, but the local file was not replaced.'),
        })
        return
      }
      setNotice({
        tone: 'success',
        message: tr(
          `POTCAR 已按 ${expectedPotcarSpeciesOrder.join(' → ')} 校验并保存到本地工作文件夹；${run.submitted ? `已有作业 ${run.job_id ?? ''}，未重复提交。` : '尚未提交作业。'}`,
          `POTCAR was verified in ${expectedPotcarSpeciesOrder.join(' → ')} order and saved to the local work folder; ${run.submitted ? `existing job ${run.job_id ?? ''} was not resubmitted.` : 'no job has been submitted.'}`,
        ),
      })
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : tr('POTCAR 生成失败。', 'Failed to build POTCAR.') })
    } finally {
      setBusy(null)
    }
  }, [applyRemotePotcarMetadata, buildAndCopyRemotePotcar, calculationConfig, expectedPotcarSpeciesOrder, fetchRemotePotcarMetadata, prepareCalculationRun, tr])

  const stageRemoteRun = useCallback(async () => {
    if (!currentProject || !selectedRun) return
    setBusy('hpc-stage')
    try {
      const copied = await buildAndCopyRemotePotcar(selectedRun, confirmRemoteWrite)
      if (!copied) {
        setNotice({ tone: 'warning', message: tr('远端准备完成，但按你的选择没有替换本地 POTCAR。', 'Remote staging completed, but the local POTCAR was not replaced.') })
        return
      }
      setNotice({
        tone: 'success',
        message: selectedRun.potcar_materialized || selectedRun.submitted
          ? tr(
              '已从现有远端运行下载并校验 POTCAR；没有修改远端，也没有重复提交作业。',
              'Downloaded and verified POTCAR from the existing remote run without modifying it or resubmitting the job.',
            )
          : tr(
              '已新建远端项目目录、上传输入、生成并校验 POTCAR，并复制到本地工作文件夹；尚未提交作业。',
              'Created the remote project directory, uploaded inputs, built and verified POTCAR, and copied it to the local work folder; no job was submitted.',
            ),
      })
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('远端准备失败。', 'Remote staging failed.'),
      })
    } finally {
      setBusy(null)
    }
  }, [buildAndCopyRemotePotcar, confirmRemoteWrite, currentProject, selectedRun, tr])

  const submitRemoteRun = useCallback(async () => {
    if (!currentProject || !selectedRun) return
    setBusy('hpc-submit')
    try {
      const response = await api.submitRemoteRun(
        currentProject.project_id,
        hpcProfile,
        selectedRun.run_id,
        selectedRun.plan_sha256,
        confirmSubmit,
      )
      setHpcJobId(response.job_id)
      updateNode('slurm.submit', 'success', tr(`Slurm 作业 ${response.job_id} 已提交`, `Slurm job ${response.job_id} submitted`))
      const refreshedRuns = await api.projectRuns(currentProject.project_id)
      setRuns(refreshedRuns)
      setNotice({
        tone: 'success',
        message: tr(
          `Slurm 作业 ${response.job_id} 已提交并生成本地审计回执。`,
          `Slurm job ${response.job_id} was submitted and a local audit receipt was created.`,
        ),
      })
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('Slurm 提交失败。', 'Slurm submission failed.'),
      })
    } finally {
      setBusy(null)
    }
  }, [confirmSubmit, currentProject, hpcProfile, selectedRun, tr, updateNode])

  const observeRemoteRun = useCallback(async () => {
    if (!currentProject || !selectedRun) return
    setBusy('hpc-observe')
    try {
      const response = await api.observeRemoteRun(currentProject.project_id, hpcProfile, selectedRun.run_id)
      setHpcObservation(response)
      setNotice({
        tone: 'success',
        message: tr(
          `调度器状态：${response.report.observation?.state ?? response.report.status}。`,
          `Scheduler state: ${response.report.observation?.state ?? response.report.status}.`,
        ),
      })
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('作业观测失败。', 'Job observation failed.'),
      })
    } finally {
      setBusy(null)
    }
  }, [currentProject, hpcProfile, selectedRun, tr])

  const pullRemoteResults = useCallback(async () => {
    if (!currentProject || !selectedRun) return
    setBusy('hpc-pull')
    try {
      const response = await api.pullRemoteResults(
        currentProject.project_id,
        hpcProfile,
        selectedRun.run_id,
        confirmResultPull,
      )
      setRemoteResult(response)
      setResult(response.vasp)
      setThermochemistry(null)
      setCalculationResults(await api.calculationResults(currentProject.project_id))
      setActiveView('results')
      setNotice({
        tone: response.vasp.scientifically_complete ? 'success' : 'warning',
        message: tr(
          '受限输出已下载并解析；POTCAR 未下载，结果仍等待人工科学审核。',
          'Allowlisted outputs were downloaded and parsed; POTCAR was not downloaded. Results and automatic diagnostics are ready.',
        ),
      })
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : tr('结果拉取失败。', 'Result retrieval failed.'),
      })
    } finally {
      setBusy(null)
    }
  }, [confirmResultPull, currentProject, hpcProfile, selectedRun, tr])

  const renderProjects = () => (
    <section className="project-workbench">
      <div className="section-heading">
        <div>
          <span className="eyebrow">PERSISTENT PROJECTS</span>
          <h2>{tr('项目与 Artifact', 'Projects and artifacts')}</h2>
          <p>{tr('项目、结构和工作流写入本地受控目录；没有删除接口。', 'Projects, structures, and workflows are stored in a controlled local directory; no delete API is exposed.')}</p>
        </div>
        {currentProject && (
          <a
            className="secondary-button"
            href={api.projectExportUrl(currentProject.project_id)}
          >
            <Download size={16} /> {tr('导出项目', 'Export project')}
          </a>
        )}
      </div>
      <div className="project-grid">
        <article className="project-create-card">
          <span className="eyebrow">NEW PROJECT</span>
          <h3>{tr('创建全流程项目', 'Create an end-to-end project')}</h3>
          <label>
            {tr('项目名称', 'Project name')}
            <input
              maxLength={120}
              onChange={(event) => setProjectTitle(event.target.value)}
              value={projectTitle}
            />
          </label>
          <label>
            {tr('科研目的', 'Research purpose')}
            <select
              onChange={(event) => setProjectPurpose(event.target.value as ProjectRecord['purpose'])}
              value={projectPurpose}
            >
              <option value="training">{tr('全流程训练', 'End-to-end training')}</option>
              <option value="literature_reproduction">{tr('文献复现', 'Literature reproduction')}</option>
              <option value="original_research">{tr('原创研究', 'Original research')}</option>
              <option value="experimental_interpretation">{tr('实验解释', 'Experimental interpretation')}</option>
            </select>
          </label>
          <button
            className="primary-button"
            disabled={busy !== null || !projectTitle.trim()}
            onClick={() => void createProject()}
            type="button"
          >
            <FolderPlus size={16} /> {tr('创建并打开', 'Create and open')}
          </button>
        </article>
        <div className="project-list-card">
          <div className="project-list-heading">
            <div>
              <span className="eyebrow">LOCAL LIBRARY</span>
              <h3>{tr('本地项目', 'Local projects')}</h3>
            </div>
            <strong>{projects.length}</strong>
          </div>
          {projects.length === 0 ? (
            <div className="project-empty"><Database size={28} />{tr('尚未创建持久化项目', 'No persistent project yet')}</div>
          ) : (
            <div className="project-list">
              {projects.map((project) => (
                <button
                  className={currentProject?.project_id === project.project_id ? 'selected' : ''}
                  key={project.project_id}
                  onClick={() => selectProject(project)}
                  type="button"
                >
                  <span>
                    <strong>{project.title}</strong>
                    <small>{project.purpose} · {project.project_id}</small>
                  </span>
                  <span className="project-counts">
                    {project.artifact_count} Artifact<br />{project.run_count} Run
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      {paper4Case && (
        <article className="reference-case-card">
          <div>
            <span className="eyebrow">REFERENCE IMPLEMENTATION</span>
            <h3>{paper4Case.title}</h3>
            <p>{tr('这是平台的首个真实科研验收案例，不是通用核心；缺失参数保持为空，阻断项不会被自动绕过。', 'This is the first real scientific acceptance case, not the generic core. Missing parameters remain empty and blockers are never bypassed.')}</p>
          </div>
          <div className="readiness-numbers">
            <span><strong>{paper4Case.readiness.satisfied_requirement_ids.length}</strong> {tr('已满足', 'satisfied')}</span>
            <span className="blocked"><strong>{paper4Case.readiness.blocking_requirement_ids.length}</strong> {tr('阻断', 'blocked')}</span>
          </div>
          <div className="reference-blockers">
            {paper4Case.readiness.requirements
              .filter((item) => item.status === 'blocked')
              .slice(0, 5)
              .map((item) => <span key={item.requirement_id}>{item.requirement_id}</span>)}
          </div>
          <button className="secondary-button" disabled={busy !== null} onClick={() => void createPaper4Project()} type="button">
            <FlaskConical size={16} /> {tr('创建 Paper 4 验收项目', 'Create Paper 4 acceptance project')}
          </button>
        </article>
      )}
    </section>
  )

  const renderWorkflow = () => (
    <section className="canvas-card">
      <div className="canvas-toolbar">
        <div>
          <span className="eyebrow">ADVANCED GRAPH</span>
          <h2>{tr('结构到计算结果', 'Structure to calculation results')}</h2>
        </div>
        <div className="toolbar-actions">
          <button className="ghost-button" onClick={() => void validateCurrentWorkflow()} type="button">
            <ShieldCheck size={15} /> {tr('校验', 'Validate')}
          </button>
          <button className="ghost-button" onClick={() => void saveWorkflow()} type="button">
            <Save size={15} /> {tr('保存布局', 'Save layout')}
          </button>
          <button className="ghost-button" onClick={resetWorkflow} type="button">
            <RotateCcw size={15} /> {tr('重置', 'Reset')}
          </button>
        </div>
      </div>
      <div className="workflow-canvas">
        {connectionState !== 'online' ? (
          <div className="connection-empty">
            {connectionState === 'loading' ? (
              <LoaderCircle className="spin" size={28} />
            ) : (
              <ServerOff size={32} />
            )}
            <strong>{connectionState === 'loading' ? tr('正在连接本地 API', 'Connecting to local API') : tr('本地 API 未启动', 'Local API is offline')}</strong>
            <span>{tr('后端只需监听 127.0.0.1:8000', 'The backend only needs to listen on 127.0.0.1:8000')}</span>
            {connectionState === 'offline' && (
              <button onClick={() => setBootstrapKey((value) => value + 1)} type="button">
                <RefreshCw size={14} /> {tr('重试', 'Retry')}
              </button>
            )}
          </div>
        ) : (
          <ReactFlow
            colorMode="dark"
            defaultEdgeOptions={{ type: 'smoothstep' }}
            edges={edges}
            fitView
            fitViewOptions={{ padding: 0.18 }}
            isValidConnection={(connection) =>
              compatibleHandles(connection.sourceHandle ?? null, connection.targetHandle ?? null)
            }
            maxZoom={1.35}
            minZoom={0.28}
            nodeTypes={nodeTypes}
            nodes={nodes}
            onConnect={onConnect}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onNodeDoubleClick={(_, node) => {
              setSelectedNodeId(node.id)
              setActiveView(NODE_VIEW[node.data.definition.type_id] ?? 'workflow')
            }}
            onNodesChange={onNodesChange}
          >
            <Background color="#27423a" gap={22} size={1} />
            <Controls position="bottom-left" showInteractive={false} />
            <MiniMap
              maskColor="rgba(5, 14, 12, 0.78)"
              nodeColor={(node) =>
                node.data?.status === 'success'
                  ? '#57c9a2'
                  : node.data?.status === 'blocked'
                    ? '#db6b67'
                    : '#5c776f'
              }
              pannable
              position="bottom-right"
              zoomable
            />
          </ReactFlow>
        )}
      </div>
    </section>
  )

  const renderStructure = () => (
    <section className="structure-workbench">
      <div className="section-heading">
        <div>
          <span className="eyebrow">STRUCTURE DIAGNOSTICS</span>
          <h2>{tr('周期结构工作台', 'Periodic structure workbench')}</h2>
          <p>{tr('可视化、几何指标和 provenance 同屏展示。当前查看器保持只读。', 'Visualization, geometry metrics, and provenance are shown together in a read-only viewer.')}</p>
        </div>
        <div className="section-actions">
          <button className="secondary-button" onClick={() => void selectWorkDirectory()} type="button">
            <FolderOpen size={16} /> {workDirectory ? workDirectory.name : tr('选择工作文件夹', 'Choose work folder')}
          </button>
          <button className="primary-button" onClick={() => fileInputRef.current?.click()} type="button">
            <Upload size={16} /> {tr('上传结构', 'Upload structure')}
          </button>
        </div>
      </div>
      <div className="structure-grid">
        <div
          className="large-viewer-card"
          onWheelCapture={(event) => {
            if (event.ctrlKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return
            const scrollArea = event.currentTarget.closest('.structure-workbench')
            if (scrollArea instanceof HTMLElement) scrollArea.scrollTop += event.deltaY
          }}
        >
          <StructureViewer structure={structure?.viewer ?? null} />
        </div>
        <div className="metrics-column">
          <article className="metric-card feature-metric">
            <span>{tr('化学式', 'Formula')}</span>
            <strong>{structure?.inspection.record?.reduced_formula ?? '—'}</strong>
            <small>{structure?.inspection.record?.num_sites ?? 0} {tr('个周期位点', 'periodic sites')}</small>
          </article>
          <article className="metric-card">
            <span>{tr('最短周期距离', 'Minimum periodic distance')}</span>
            <strong>{formatNumber(structure?.inspection.metrics?.minimum_distance_angstrom)} Å</strong>
            <small>{tr('异常近接会阻断后续步骤', 'Abnormally close contacts block downstream steps')}</small>
          </article>
          <article className="metric-card">
            <span>{tr('晶胞体积', 'Cell volume')}</span>
            <strong>{formatNumber(structure?.inspection.record?.volume_angstrom3, 2)} Å³</strong>
            <small>{tr('哈希', 'Hash')} {shortenHash(structure?.inspection.record?.canonical_hash)}</small>
          </article>
          <article className="metric-card">
            <span>{tr('诊断', 'Diagnostics')}</span>
            <div className="diagnostic-counts">
              <b className="count-error">{severityCount(structure?.inspection.diagnostics, 'error')} {tr('错误', 'errors')}</b>
              <b className="count-warning">
                {severityCount(structure?.inspection.diagnostics, 'warning')} {tr('警告', 'warnings')}
              </b>
            </div>
            <small>{tr('由 CatEx 只读检查生成', 'Generated by read-only CatEx inspection')}</small>
          </article>
        </div>
      </div>
    </section>
  )

  const renderProtocol = () => {
    const resolved = calculationPlan?.resolution.resolved
    const plan = calculationPlan?.plan
    const potcarConfig = calculationConfig?.potcar_metadata as
      | { potential_family?: string; datasets?: Array<Record<string, unknown>> }
      | undefined
    const executionConfig = calculationConfig?.execution_profile as
      | {
          job_name?: string
          partition?: string
          nodes?: number
          tasks_per_node?: number
           walltime?: string
           executable?: string
           cpus_per_task?: number
           module_loads?: string[]
           mpi_plugin?: string
         }
      | undefined
    const requestedWalltimeMinutes = parseSlurmWalltimeMinutes(executionConfig?.walltime)
    const walltimeExceedsProjectLimit = requestedWalltimeMinutes !== null
      && clusterMaxWalltimeMinutes > 0
      && requestedWalltimeMinutes > clusterMaxWalltimeMinutes
    const subdivisions = kpointsConfig?.subdivisions ?? [1, 1, 1]
    const shift = kpointsConfig?.shift ?? [0, 0, 0]
    const sourceIsPoscar = Boolean(
      latestStructureArtifact && !latestStructureArtifact.original_filename.toLowerCase().endsWith('.cif'),
    )
    const fixedConstraintAtoms = new Set(constraintPreview.fixedIndices1Based)
    const mobileConstraintAtoms = new Set(constraintPreview.mobileIndices1Based)
    const constraintPreviewError = constraintPreview.error
      ? tr(
          constraintPreview.error === 'Select at least one adsorbate atom.'
            ? '请在模型或原子序号列表中至少选择一个吸附物原子。'
            : constraintPreview.error === 'The fixed-layer count must leave at least one mobile layer.'
              ? '固定层数过多，必须至少保留一层可移动原子。'
              : constraintPreview.error === 'Fix at least one bottom layer.'
                ? '请至少固定一层底层原子。'
                : `约束预览无效：${constraintPreview.error}`,
          constraintPreview.error,
        )
      : null
    return (
      <section className="protocol-workbench">
        <div className="section-heading">
          <div>
            <span className="eyebrow">VISIBLE VASP AUTOMATION</span>
            <h2>{tr('VASP 输入自动化', 'VASP input automation')}</h2>
            <p>{tr(
              '工作文件夹中的输入会自动读取；页面修改可写回 POSCAR、INCAR、KPOINTS，POTCAR 在超算端受控生成。',
              'Inputs are read from the work folder; page edits can be written back to POSCAR, INCAR, and KPOINTS, while POTCAR is built under control on the HPC.',
            )}</p>
          </div>
          <span className={`connection-badge ${hpcConnected ? 'online' : ''}`}>{hpcConnected ? <ShieldCheck size={14} /> : <ServerOff size={14} />} {hpcConnected ? tr('超算已验证', 'HPC verified') : tr('请先连接超算', 'Connect HPC first')}</span>
        </div>

        <div className="work-folder-bar">
          <div><FolderOpen size={18} /><span><strong>{tr('本地工作文件夹', 'Local work folder')}</strong><small>{workDirectory?.name ?? tr('尚未选择；浏览器不会扫描其他目录', 'Not selected; the browser never scans other folders')}</small></span></div>
          <button className="secondary-button" onClick={() => void selectWorkDirectory()} type="button">{workDirectory ? tr('重新选择并读取', 'Choose and scan again') : tr('选择并自动读取', 'Choose and auto-read')}</button>
        </div>
        {workDirectory && (
          <div className="work-folder-file-list" aria-label={tr('工作文件夹读取结果', 'Work-folder scan results')}>
            {(['poscar', 'incar', 'kpoints', 'potcar', 'slurm'] as InputFileKey[]).map((key) => (
              <span className={workFileSources[key] ? 'ready' : ''} key={key}>
                <strong>{key.toUpperCase()}</strong>
                {workFileSources[key] || tr('未检测到', 'Not detected')}
              </span>
            ))}
          </div>
        )}

        <div className="automation-status-grid">
          <article><FileCheck2 size={18} /><strong>POSCAR</strong><span>{poscarSource ? (workFileSources.poscar || tr('已从结构绑定', 'Bound to structure')) : tr('等待结构', 'Waiting for structure')}</span></article>
          <article><Settings2 size={18} /><strong>INCAR</strong><span>{workFileSources.incar ? `${workFileSources.incar} · ` : ''}{incarEntries.length} {tr('个参数', 'parameters')}</span></article>
          <article><Database size={18} /><strong>KPOINTS</strong><span>{workFileSources.kpoints ? `${workFileSources.kpoints} · ` : ''}{subdivisions.join(' × ')}</span></article>
          <article><Server size={18} /><strong>POTCAR</strong><span>{localPotcarReceipt
            ? tr('已生成并保存本地', 'Built and saved locally')
            : potcarMetadataCompatible
              ? tr('元素顺序已匹配', 'Species order matched')
              : hpcConnected
                ? tr('待读取远端元数据', 'Awaiting remote metadata')
                : tr('等待超算连接', 'Waiting for HPC')}</span></article>
        </div>

        <div className="vasp-input-grid">
          <article className="vasp-input-card poscar-card">
            <div className="card-heading">
              <div><span className="eyebrow">STRUCTURE → POSCAR</span><h3>POSCAR</h3></div>
              <div className="input-card-actions">
                <span className={`input-state ${poscarSource && sourceIsPoscar ? 'ready' : ''}`}>
                  {poscarSource && sourceIsPoscar ? tr('只读已绑定', 'Read-only bound') : tr('未就绪', 'Not ready')}
                </span>
                <button
                  className="input-import-button"
                  disabled={busy !== null || connectionState !== 'online'}
                  onClick={() => fileInputRef.current?.click()}
                  type="button"
                >
                  <FileUp size={14} /> {tr('导入/替换', 'Import/replace')}
                </button>
              </div>
            </div>
            <p>{tr(
              '上传的 POSCAR/CONTCAR/.vasp 会按 SHA256 绑定到计算计划；CIF 会显式转换为 POSCAR，不会静默改坐标。',
              'The uploaded POSCAR/CONTCAR/.vasp is SHA256-bound to the plan; CIF is explicitly converted to POSCAR without silent coordinate edits.',
            )}</p>
            {latestStructureArtifact && (
              <div className="input-import-source">
                <FileCheck2 size={13} /> {tr('当前来源', 'Current source')}: {latestStructureArtifact.original_filename}
              </div>
            )}
            {latestStructureArtifact?.original_filename.toLowerCase().endsWith('.cif') && (
              <div className="inline-warning"><AlertTriangle size={15} /> {tr(
                'CIF 可用于结构检查，但 VASP 计划前需要显式转换并重新审核 POSCAR。',
                'CIF can be inspected, but VASP planning requires an explicit POSCAR conversion and a new review.',
              )}</div>
            )}
            <section className="poscar-constraint-panel">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">SELECTIVE DYNAMICS</span>
                  <h4>{tr('固定催化剂 / 放开吸附物', 'Fix catalyst / release adsorbate')}</h4>
                </div>
                <label className="constraint-enable-toggle">
                  <input
                    checked={selectiveDynamicsEnabled}
                    onChange={(event) => setSelectiveDynamicsEnabled(event.target.checked)}
                    type="checkbox"
                  />
                  <span>{tr('启用原子约束', 'Enable atom constraints')}</span>
                </label>
              </div>
              {!selectiveDynamicsEnabled ? (
                <p className="constraint-disabled-note">{tr(
                  '默认关闭，避免误改 POSCAR。勾选后才显示结构选择和应用按钮。',
                  'Off by default to prevent accidental POSCAR edits. Enable it to reveal atom selection and the apply action.',
                )}</p>
              ) : (
                <div className="constraint-preview-layout">
                  <div className="constraint-visual-column">
                    <div className="constraint-viewer-card">
                      <StructureViewer
                        fixedAtomIndices1Based={constraintPreview.fixedIndices1Based}
                        focusedAtomIndex1Based={focusedConstraintAtom}
                        mobileAtomIndices1Based={constraintPreview.mobileIndices1Based}
                        onAtomClick={handleConstraintAtomClick}
                        showAtomIndices={showAllConstraintAtomIndices}
                        structure={structure?.viewer ?? null}
                      />
                    </div>
                    <div className="constraint-viewer-toolbar">
                      <div className="constraint-legend" aria-label={tr('原子约束图例', 'Atom constraint legend')}>
                        <span className="fixed">{tr('固定 F F F', 'Fixed F F F')}</span>
                        <span className="mobile">{tr('放开 T T T', 'Mobile T T T')}</span>
                        <span className="focused">{tr('当前原子', 'Focused atom')}</span>
                      </div>
                      <label className="show-index-toggle">
                        <input checked={showAllConstraintAtomIndices} onChange={(event) => setShowAllConstraintAtomIndices(event.target.checked)} type="checkbox" />
                        {tr('在模型中显示全部序号', 'Show all indices in model')}
                      </label>
                    </div>
                    <div className="focused-atom-readout">
                      <MousePointer2 size={15} />
                      {focusedConstraintAtom
                        ? tr(
                            `当前原子：#${focusedConstraintAtom} ${structure?.viewer?.species[focusedConstraintAtom - 1] ?? ''}`,
                            `Current atom: #${focusedConstraintAtom} ${structure?.viewer?.species[focusedConstraintAtom - 1] ?? ''}`,
                          )
                        : tr('点击三维模型或下方序号查看原子', 'Click the model or an index below to inspect an atom')}
                    </div>
                    <div className="atom-index-picker" aria-label={tr('POSCAR 原子序号', 'POSCAR atom indices')}>
                      {(structure?.viewer?.species ?? []).map((species, index) => {
                        const index1Based = index + 1
                        const classes = [
                          fixedConstraintAtoms.has(index1Based) ? 'fixed' : '',
                          mobileConstraintAtoms.has(index1Based) ? 'mobile' : '',
                          focusedConstraintAtom === index1Based ? 'focused' : '',
                        ].filter(Boolean).join(' ')
                        return (
                          <button
                            aria-label={tr(`原子 ${index1Based} ${species}`, `Atom ${index1Based} ${species}`)}
                            className={classes}
                            key={index1Based}
                            onClick={() => handleConstraintAtomClick(index1Based)}
                            type="button"
                          >
                            <strong>#{index1Based}</strong><span>{species}</span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                  <div className="constraint-controls-column">
                    <p>{tr(
                      '选择会立即在模型中预览，但不会写文件。只有点击“应用”后，CatEx 才把约束写成 Selective dynamics 标记。原子序号按 POSCAR 从 1 开始。',
                      'Selections are previewed immediately without writing a file. CatEx writes Selective dynamics flags only after Apply. POSCAR atom indices start at 1.',
                    )}</p>
                    <div className="constraint-form">
                      <label className="wide">{tr('弛豫方式', 'Relaxation mode')}
                        <select onChange={(event) => setConstraintStrategy(event.target.value as SelectiveDynamicsStrategy)} value={constraintStrategy}>
                          <option value="adsorbate_indices">{tr('固定催化剂，仅放开指定吸附物', 'Fix catalyst; release specified adsorbate')}</option>
                          <option value="bottom_layers">{tr('仅固定底部若干层', 'Fix bottom layers only')}</option>
                          <option value="none">{tr('全部原子自由移动', 'Release all atoms')}</option>
                        </select>
                      </label>
                      {constraintStrategy === 'adsorbate_indices' && (
                        <label className="wide">{tr('吸附物原子序号（从 1 开始）', 'Adsorbate atom indices (start at 1)')}
                          <input onChange={(event) => setMobileAtomText(event.target.value)} placeholder={tr('点击模型选择，或输入 65-70', 'Click the model, or enter 65-70')} value={mobileAtomText} />
                        </label>
                      )}
                      {constraintStrategy === 'bottom_layers' && (
                        <>
                          <label>{tr('固定层数', 'Bottom layers to fix')}<input min={1} onChange={(event) => setBottomLayerCount(Number(event.target.value))} type="number" value={bottomLayerCount} /></label>
                          <label>{tr('分层阈值 (Å)', 'Layer tolerance (Å)')}<input min={0.01} max={5} onChange={(event) => setLayerTolerance(Number(event.target.value))} step={0.05} type="number" value={layerTolerance} /></label>
                        </>
                      )}
                    </div>
                    <div className={`constraint-preview-summary ${constraintPreviewError ? 'invalid' : ''}`}>
                      <span><strong>{constraintPreview.fixedIndices1Based.length}</strong>{tr(' 固定', ' fixed')}</span>
                      <span><strong>{constraintPreview.mobileIndices1Based.length}</strong>{tr(' 放开', ' mobile')}</span>
                      {constraintStrategy === 'bottom_layers' && <span><strong>{constraintPreview.layerCount}</strong>{tr(' 个识别层', ' detected layers')}</span>}
                    </div>
                    {constraintPreviewError && <div className="inline-warning"><AlertTriangle size={15} /> {constraintPreviewError}</div>}
                    {constraintSummary && <div className="constraint-applied-summary"><Check size={15} /> {constraintSummary}</div>}
                    <button
                      className="primary-button constraint-apply-button"
                      disabled={!poscarSource || busy !== null || Boolean(constraintPreviewError)}
                      onClick={() => void applyStructureConstraints()}
                      type="button"
                    >
                      <Atom size={16} /> {tr('应用约束并更新 POSCAR', 'Apply constraints and update POSCAR')}
                    </button>
                  </div>
                </div>
              )}
            </section>
            <details className="input-preview-details">
              <summary>{tr('查看 POSCAR 文本', 'View POSCAR text')}</summary>
              <pre aria-label="POSCAR preview" className="input-preview">{poscarSource || tr('请先上传结构。', 'Upload a structure first.')}</pre>
            </details>
          </article>

          <article className="vasp-input-card incar-card">
            <div className="card-heading">
              <div><span className="eyebrow">PROTOCOL → INCAR</span><h3>INCAR</h3></div>
              <div className="input-card-actions">
                <span className="input-state ready">{tr('表格编辑', 'Form editor')}</span>
                <input
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) void importIncar(file)
                    event.target.value = ''
                  }}
                  ref={incarInputRef}
                  type="file"
                />
                <button className="input-import-button" onClick={() => incarInputRef.current?.click()} type="button">
                  <FileUp size={14} /> {tr('导入/替换', 'Import/replace')}
                </button>
              </div>
            </div>
            <p>{tr('每次修改都会重新校验输入，并在进入运行中心时生成新的可追踪快照。', 'Every change is revalidated and produces a new traceable snapshot when you continue to Run Center.')}</p>
            {importedInputNames.incar && (
              <div className="input-import-source"><FileCheck2 size={13} /> {tr('已导入', 'Imported')}: {importedInputNames.incar}</div>
            )}
            <div className="incar-table" role="table" aria-label="INCAR parameters">
              {incarEntries.map(([tag, value]) => (
                <div className="incar-row" key={tag} role="row">
                  <code>{tag}</code>
                  <input aria-label={`${tag} value`} onChange={(event) => updateIncarValue(tag, event.target.value)} value={value} />
                  <button aria-label={`${tr('删除', 'Remove')} ${tag}`} className="icon-button" onClick={() => removeIncarTag(tag)} type="button">×</button>
                </div>
              ))}
            </div>
            <div className="incar-add-row">
              <input aria-label="New INCAR tag" onChange={(event) => setNewIncarTag(event.target.value)} placeholder={tr('新标签，例如 IBRION', 'New tag, e.g. IBRION')} value={newIncarTag} />
              <input aria-label="New INCAR value" onChange={(event) => setNewIncarValue(event.target.value)} placeholder={tr('值', 'Value')} value={newIncarValue} />
              <button className="secondary-button" onClick={addIncarTag} type="button">{tr('添加', 'Add')}</button>
            </div>
          </article>

          <article className="vasp-input-card kpoints-card">
            <div className="card-heading">
              <div><span className="eyebrow">MESH → KPOINTS</span><h3>KPOINTS</h3></div>
              <div className="input-card-actions">
                <input
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) void importKpoints(file)
                    event.target.value = ''
                  }}
                  ref={kpointsInputRef}
                  type="file"
                />
                <button className="input-import-button" onClick={() => kpointsInputRef.current?.click()} type="button">
                  <FileUp size={14} /> {tr('导入/替换', 'Import/replace')}
                </button>
              </div>
            </div>
            <p>{tr('可导入 Gamma 或 Monkhorst-Pack 自动网格文件；显式 KPOINTS 暂不自动改写。', 'Import a Gamma or Monkhorst-Pack automatic mesh; explicit KPOINTS files are not rewritten automatically.')}</p>
            {importedInputNames.kpoints && (
              <div className="input-import-source"><FileCheck2 size={13} /> {tr('已导入', 'Imported')}: {importedInputNames.kpoints}</div>
            )}
            <div className="compact-form">
              <label>{tr('注释', 'Comment')}<input onChange={(event) => updateKpoints('comment', event.target.value)} value={kpointsConfig?.comment ?? ''} /></label>
              <label>{tr('网格模式', 'Mesh mode')}
                <select onChange={(event) => updateKpoints('generation_mode', event.target.value)} value={kpointsConfig?.generation_mode ?? 'gamma'}>
                  <option value="gamma">Gamma</option>
                  <option value="monkhorst-pack">Monkhorst-Pack</option>
                </select>
              </label>
              <fieldset><legend>{tr('细分', 'Subdivisions')}</legend><div className="triple-input">
                {subdivisions.map((value, index) => <input aria-label={`KPOINTS subdivision ${index + 1}`} key={index} min={1} onChange={(event) => { const next = [...subdivisions]; next[index] = Number(event.target.value); updateKpoints('subdivisions', next) }} type="number" value={value} />)}
              </div></fieldset>
              <fieldset><legend>{tr('偏移', 'Shift')}</legend><div className="triple-input">
                {shift.map((value, index) => <input aria-label={`KPOINTS shift ${index + 1}`} key={index} onChange={(event) => { const next = [...shift]; next[index] = Number(event.target.value); updateKpoints('shift', next) }} step="0.5" type="number" value={value} />)}
              </div></fieldset>
            </div>
          </article>

          <article className="vasp-input-card potcar-card">
            <div className="card-heading">
              <div><span className="eyebrow">METADATA → SERVER BUILD</span><h3>POTCAR</h3></div>
              <div className="input-card-actions">
                <span className={`input-state ${localPotcarReceipt || potcarMetadataCompatible ? 'ready' : ''}`}>
                  {localPotcarReceipt
                    ? tr('本地已有 POTCAR', 'Local POTCAR ready')
                    : potcarMetadataCompatible
                      ? tr('元数据已匹配', 'Metadata matched')
                      : hpcConnected
                        ? tr('待读取元数据', 'Metadata required')
                        : tr('需连接超算', 'HPC required')}
                </span>
                <input
                  accept=".json,application/json"
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) void importPotcarMetadata(file)
                    event.target.value = ''
                  }}
                  ref={potcarMetadataInputRef}
                  type="file"
                />
                <button className="input-import-button" onClick={() => potcarMetadataInputRef.current?.click()} type="button">
                  <FileUp size={14} /> {tr('导入元数据', 'Import metadata')}
                </button>
              </div>
            </div>
            <p>{tr(
              '标签默认严格采用 POSCAR 元素顺序。可先只读确认元数据，也可直接生成：CatEx 会准备本次完整输入，在新的远端项目目录中生成并校验 POTCAR，再保存一份到本地工作文件夹；不会提交作业。',
              'Labels default to the exact POSCAR species order. You can inspect metadata read-only or build immediately: CatEx prepares the complete input, builds and verifies POTCAR in the new remote project directory, then saves a copy to the local work folder without submitting a job.',
            )}</p>
            <div className="potcar-probe-row">
              <label>{tr('势函数标签（按 POSCAR 元素顺序）', 'Potential labels (POSCAR order)')}
                <input
                  onChange={(event) => setPotcarLabelText(event.target.value)}
                  placeholder={expectedPotcarSpeciesOrder.join(', ') || 'Ni, Zn'}
                  value={potcarLabelText || expectedPotcarSpeciesOrder.join(', ')}
                />
              </label>
              <div className="potcar-action-buttons">
                <button className="secondary-button" disabled={!hpcConnected || busy !== null} onClick={() => void probeRemotePotcarMetadata()} type="button">
                  <Server size={15} /> {tr('读取并确认元数据', 'Read and confirm metadata')}
                </button>
                <button
                  className="primary-button"
                  disabled={!hpcConnected || !workDirectory || busy !== null}
                  onClick={() => void generatePotcarFromProtocol()}
                  title={workDirectory ? undefined : tr('请先选择本地工作文件夹', 'Choose a local work folder first')}
                  type="button"
                >
                  {busy === 'potcar-build' ? <LoaderCircle className="spin" size={15} /> : <Download size={15} />} {localPotcarReceipt ? tr('重新下载 POTCAR', 'Download POTCAR again') : tr('生成并保存 POTCAR', 'Build and save POTCAR')}
                </button>
              </div>
            </div>
            {configuredPotcarOrder.length > 0 && !potcarMetadataCompatible && (
              <div className="inline-warning"><AlertTriangle size={15} /> {tr(
                `当前元数据顺序为 ${configuredPotcarOrder.join(' → ')}，但 POSCAR 需要 ${expectedPotcarSpeciesOrder.join(' → ')}。请读取元数据或直接生成后再继续。`,
                `Current metadata order is ${configuredPotcarOrder.join(' → ')}, but POSCAR requires ${expectedPotcarSpeciesOrder.join(' → ')}. Read metadata or build POTCAR before continuing.`,
              )}</div>
            )}
            {importedInputNames.potcar && (
              <div className="input-import-source"><ShieldCheck size={13} /> {tr('已导入脱敏 JSON', 'Sanitized JSON imported')}: {importedInputNames.potcar}</div>
            )}
            <dl className="detail-list">
              <div><dt>{tr('POSCAR 元素顺序', 'POSCAR species order')}</dt><dd>{expectedPotcarSpeciesOrder.join(' → ') || '—'}</dd></div>
              <div><dt>{tr('势函数族', 'Potential family')}</dt><dd>{potcarConfig?.potential_family ?? '—'}</dd></div>
              <div><dt>{tr('数据集顺序', 'Dataset order')}</dt><dd>{potcarConfig?.datasets?.map((item) => String(item.element ?? '?')).join(' → ') ?? '—'}</dd></div>
              <div><dt>{tr('数据集数量', 'Datasets')}</dt><dd>{potcarConfig?.datasets?.length ?? 0}</dd></div>
              <div><dt>{tr('本地文件', 'Local file')}</dt><dd>{localPotcarReceipt ? `${localPotcarReceipt.filename}${localPotcarReceipt.sha256 ? ` · ${shortenHash(localPotcarReceipt.sha256)}` : ''}` : tr('尚未生成', 'Not built yet')}</dd></div>
            </dl>
            <small>{tr('“读取并确认元数据”不写远端；“生成并保存 POTCAR”会在确认后新建最终运行目录并上传输入，但不会执行 sbatch。', '“Read and confirm metadata” performs no remote write. “Build and save POTCAR” creates the final run directory and uploads inputs after confirmation, but never executes sbatch.')}</small>
          </article>

          <article className="vasp-input-card slurm-card">
            <div className="card-heading">
              <div><span className="eyebrow">RESOURCES → SLURM</span><h3>{tr('提交脚本', 'Submission script')}</h3></div>
              <div className="input-card-actions">
                <input
                  accept=".slurm,.sh,text/plain"
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) void importSlurm(file)
                    event.target.value = ''
                  }}
                  ref={slurmInputRef}
                  type="file"
                />
                <button className="input-import-button" onClick={() => slurmInputRef.current?.click()} type="button"><FileUp size={14} /> {tr('读取已有脚本', 'Read existing script')}</button>
              </div>
            </div>
            <p>{tr(
              '只读取作业名、分区、节点、核数、时限、module、MPI 和 VASP 路径。邮件、删除及任意 shell 行不会导入或执行。',
              'Only job name, partition, nodes, cores, walltime, modules, MPI, and VASP path are imported. Email, deletion, and arbitrary shell lines are never imported or executed.',
            )}</p>
            {workFileSources.slurm && <div className="input-import-source"><FileCheck2 size={13} /> {tr('设置来源', 'Settings source')}: {workFileSources.slurm}</div>}
            <div className="submission-form">
              <label className="wide">{tr('远端项目名称（将在允许根目录下创建同名子文件夹）', 'Remote project name (creates a child folder under the allowed root)')}
                <input onChange={(event) => updateExecutionProfile('job_name', event.target.value)} placeholder="NiZn_bare_relax" value={executionConfig?.job_name ?? ''} />
              </label>
              <label>{tr('分区', 'Partition')}<input onChange={(event) => updateExecutionProfile('partition', event.target.value)} value={executionConfig?.partition ?? ''} /></label>
              <label>{tr('节点数', 'Nodes')}<input min={1} onChange={(event) => updateExecutionProfile('nodes', Number(event.target.value))} type="number" value={executionConfig?.nodes ?? 1} /></label>
              <label>{tr('每节点任务数', 'Tasks per node')}<input min={1} onChange={(event) => updateExecutionProfile('tasks_per_node', Number(event.target.value))} type="number" value={executionConfig?.tasks_per_node ?? 1} /></label>
              <label>{tr('每任务 CPU', 'CPUs per task')}<input min={1} onChange={(event) => updateExecutionProfile('cpus_per_task', Number(event.target.value))} type="number" value={executionConfig?.cpus_per_task ?? 1} /></label>
              <label>{tr('任务申请的最长时间', 'Requested job walltime')}<input onChange={(event) => updateExecutionProfile('walltime', event.target.value)} placeholder="7-00:00:00" value={executionConfig?.walltime ?? ''} /></label>
              <label>{tr('项目允许的最大时间', 'Project maximum walltime')}
                <input
                  aria-label={tr('项目允许的最大时间', 'Project maximum walltime')}
                  onBlur={commitProjectMaxWalltime}
                  onChange={(event) => setProjectMaxWalltimeText(event.target.value)}
                  placeholder="7-00:00:00"
                  value={projectMaxWalltimeText}
                />
              </label>
              <label>{tr('MPI 插件', 'MPI plugin')}<input onChange={(event) => updateExecutionProfile('mpi_plugin', event.target.value)} value={executionConfig?.mpi_plugin ?? 'pmi2'} /></label>
              <label className="wide">Module load<input onChange={(event) => updateExecutionProfile('module_loads', event.target.value.split(',').map((item) => item.trim()).filter(Boolean))} placeholder="intel/oneapi2023.2_impi" value={(executionConfig?.module_loads ?? []).join(', ')} /></label>
              <label className="wide">VASP executable<input onChange={(event) => updateExecutionProfile('executable', event.target.value)} value={executionConfig?.executable ?? ''} /></label>
            </div>
            <small className="walltime-format-hint">{tr(
              '两项均使用 Slurm 格式 [天-]时:分:秒；当前广州超算最长支持 7-00:00:00。',
              'Both fields use Slurm format [D-]HH:MM:SS; the configured Guangzhou cluster supports up to 7-00:00:00.',
            )}</small>
            {walltimeExceedsProjectLimit && (
              <div className="inline-warning walltime-warning"><AlertTriangle size={15} /> {tr(
                `任务申请 ${executionConfig?.walltime}（${requestedWalltimeMinutes} 分钟），但项目上限是 ${formatSlurmWalltime(clusterMaxWalltimeMinutes)}（${clusterMaxWalltimeMinutes} 分钟）。请缩短任务时间或调整项目上限。`,
                `The job requests ${executionConfig?.walltime} (${requestedWalltimeMinutes} minutes), but the project maximum is ${formatSlurmWalltime(clusterMaxWalltimeMinutes)} (${clusterMaxWalltimeMinutes} minutes). Shorten the job or adjust the project maximum.`,
              )}</div>
            )}
            <details className="script-preview"><summary>{tr('查看受控脚本预览', 'Show controlled script preview')}</summary><pre>{plan?.slurm.script_text ?? tr('点击下方“检查输入并进入下一步”后生成。', 'Generated after “Check inputs and continue” below.')}</pre></details>
          </article>
        </div>

        <details className="advanced-config-card">
          <summary>{tr('高级：完整计算配置 JSON', 'Advanced: complete calculation configuration JSON')}</summary>
          <div className="card-heading">
            <p>{tr('用于 POTCAR metadata、Slurm profile 和 cluster policy 等完整字段。', 'Use this for full POTCAR metadata, Slurm profile, and cluster policy fields.')}</p>
            <button className="secondary-button" disabled={!currentProject || busy !== null} onClick={() => void saveCalculationConfig()} type="button"><Save size={15} /> {tr('校验并保存', 'Validate and save')}</button>
          </div>
          <textarea aria-label="Calculation configuration JSON" onChange={(event) => { setCalculationConfigText(event.target.value); setCalculationPlan(null); setMaterialization(null) }} spellCheck={false} value={calculationConfigText} />
        </details>

        <article className="input-readiness-card">
          <div>
            <span className="eyebrow">INPUT COMPLETENESS</span>
            <h3>{tr('检查输入并进入下一步', 'Check inputs and continue')}</h3>
            <p>{tr(
              '按钮会校验所有输入，把 POSCAR、INCAR、KPOINTS 写回所选工作文件夹，并准备远端项目；不会在这里提交作业。',
              'This validates all inputs, writes POSCAR, INCAR, and KPOINTS to the selected work folder, and prepares the remote project. It does not submit a job here.',
            )}</p>
          </div>
          <div className="readiness-chips">
            <span className={poscarSource ? 'ready' : ''}>POSCAR</span>
            <span className={incarEntries.length ? 'ready' : ''}>INCAR</span>
            <span className={kpointsConfig ? 'ready' : ''}>KPOINTS</span>
            <span className={potcarMetadataCompatible ? 'ready' : ''}>POTCAR metadata</span>
            <span className={localPotcarReceipt ? 'ready' : ''}>{tr('本地 POTCAR（可选）', 'Local POTCAR (optional)')}</span>
            <span className={workDirectory ? 'ready' : ''}>{tr('工作文件夹', 'Work folder')}</span>
            <span className={hpcConnected ? 'ready' : ''}>{tr('超算连接', 'HPC connection')}</span>
            <span className={/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(executionConfig?.job_name ?? '') ? 'ready' : ''}>{tr('项目名称', 'Project name')}</span>
          </div>
          <button className="primary-button continue-button" disabled={busy !== null} onClick={() => void continueToRunCenter()} type="button">
            {busy === 'continue' ? <LoaderCircle className="spin" size={16} /> : <ChevronRight size={16} />} {tr('检查完整性并进入运行中心', 'Check completeness and open Run Center')}
          </button>
        </article>
        {calculationPlan && (
          <div className="plan-output-grid">
            <article>
              <span className="eyebrow">RESOLUTION</span>
              <h3>{resolved ? tr('输入诊断通过', 'Input diagnostics passed') : tr('输入诊断失败', 'Input diagnostics failed')}</h3>
              <dl className="detail-list">
                <div><dt>Energy family</dt><dd>{resolved?.energy_family_id ?? '—'}</dd></div>
                <div><dt>Resolved digest</dt><dd>{shortenHash(resolved?.resolved_protocol_sha256)}</dd></div>
                <div><dt>{tr('诊断', 'Diagnostics')}</dt><dd>{calculationPlan.resolution.diagnostics.length}</dd></div>
              </dl>
              <h4>POSCAR</h4><pre>{poscarSource || '—'}</pre>
              <h4>INCAR</h4><pre>{resolved?.incar_text ?? '—'}</pre>
              <h4>KPOINTS</h4><pre>{resolved?.kpoints_text ?? '—'}</pre>
            </article>
            <article>
              <span className="eyebrow">SLURM PREVIEW</span>
              <h3>{plan?.job_name ?? tr('未生成计划', 'No plan generated')}</h3>
              <dl className="detail-list">
                <div><dt>Plan digest</dt><dd>{shortenHash(plan?.plan_sha256)}</dd></div>
                <div><dt>{tr('可物化', 'Ready')}</dt><dd>{plan?.ready_for_materialization ? tr('是', 'Yes') : tr('否', 'No')}</dd></div>
                <div><dt>{tr('远端项目文件夹', 'Remote project folder')}</dt><dd>{executionConfig?.job_name ?? '—'}</dd></div>
                <div><dt>{tr('资源', 'Resources')}</dt><dd>{executionConfig?.nodes ?? '—'} × {executionConfig?.tasks_per_node ?? '—'} · {executionConfig?.partition ?? '—'} · {executionConfig?.walltime ?? '—'}</dd></div>
              </dl>
              <pre>{plan?.slurm.script_text ?? '—'}</pre>
            </article>
          </div>
        )}
      </section>
    )
  }

  const renderRuns = () => {
    const profileReady = Boolean(
      hpcProfile.host &&
      hpcProfile.username &&
      hpcProfile.private_key_path &&
      hpcProfile.allowed_root &&
      hpcProfile.potcar_root,
    )
    const terminal = hpcObservation?.report.observation?.terminal === true
    const selectedRunRemoteReady = Boolean(selectedRun?.potcar_materialized || selectedRun?.submitted)
    return (
      <section className="run-workbench">
        <div className="section-heading">
          <div>
            <span className="eyebrow">CONTROLLED HPC GATEWAY</span>
            <h2>{tr('运行中心', 'Run center')}</h2>
            <p>{tr('连接资料只存在于当前页面内存；关闭或刷新页面后清空，永不进入项目文件或导出包。', 'Connection data exists only in page memory, is cleared on refresh, and never enters project files or exports.')}</p>
          </div>
          <span className={`connection-badge ${hpcConnected ? 'online' : ''}`}>
            {hpcConnected ? <ShieldCheck size={14} /> : <ServerOff size={14} />}
            {hpcConnected ? tr('已只读验证', 'Read-only verified') : tr('默认未连接', 'Disconnected by default')}
          </span>
        </div>
        <div className="run-grid">
          <article className="connection-card">
            <span className="eyebrow">EPHEMERAL CONNECTION</span>
            <h3>{tr('SSH 与远端白名单', 'SSH and remote allowlist')}</h3>
            <input
              accept="application/json,.json"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void importHpcProfile(file)
                event.target.value = ''
              }}
              ref={hpcProfileInputRef}
              type="file"
            />
            <button className="ghost-button profile-import-button" onClick={() => hpcProfileInputRef.current?.click()} type="button">
              <FolderOpen size={15} /> {tr('导入本机连接配置', 'Import local connection profile')}
            </button>
            <small>{tr('JSON 只由浏览器读入当前页面内存，不上传、不持久化。', 'The JSON is read into current page memory only; it is not uploaded or persisted.')}</small>
            <div className="connection-form">
              <label>{tr('主机', 'Host')}<input autoComplete="off" onChange={(event) => updateHpcProfile('host', event.target.value)} value={hpcProfile.host} /></label>
              <label>{tr('端口', 'Port')}<input min={1} max={65535} onChange={(event) => updateHpcProfile('port', Number(event.target.value))} type="number" value={hpcProfile.port} /></label>
              <label>{tr('用户名', 'Username')}<input autoComplete="off" onChange={(event) => updateHpcProfile('username', event.target.value)} value={hpcProfile.username} /></label>
              <label className="wide">{tr('本地私钥路径', 'Local private-key path')}<input autoComplete="off" onChange={(event) => updateHpcProfile('private_key_path', event.target.value)} type="password" value={hpcProfile.private_key_path} /></label>
              <label className="wide">{tr('允许的远端项目根目录', 'Allowed remote project root')}<input autoComplete="off" onChange={(event) => updateHpcProfile('allowed_root', event.target.value)} value={hpcProfile.allowed_root} /></label>
              <label className="wide">{tr('远端 PAW-PBE 势函数目录（只读探测）', 'Remote PAW-PBE library (read-only probe)')}<input autoComplete="off" onChange={(event) => updateHpcProfile('potcar_root', event.target.value)} value={hpcProfile.potcar_root ?? ''} /></label>
              <label className="wide">{tr('主机密钥 SHA256（推荐）', 'Host-key SHA256 (recommended)')}<input autoComplete="off" onChange={(event) => updateHpcProfile('host_key_sha256', event.target.value)} placeholder={tr('SHA256:...；留空则必须已在系统 known_hosts', 'SHA256:...; when blank, the host must exist in system known_hosts')} value={hpcProfile.host_key_sha256 ?? ''} /></label>
            </div>
            <button className="secondary-button" disabled={!profileReady || busy !== null} onClick={() => void probeHpc()} type="button">
              <ShieldCheck size={16} /> {tr('只读测试连接', 'Test read-only connection')}
            </button>
            <small>{tr('探测只执行 SFTP stat/list；不会运行 shell 命令或写远端文件。', 'The probe uses only SFTP stat/list; it runs no shell command and writes no remote file.')}</small>
          </article>
          <article className="run-lifecycle-card">
            <span className="eyebrow">SELECTED LOCAL RUN</span>
            <h3>{tr('受控运行生命周期', 'Controlled run lifecycle')}</h3>
            <label>{tr('本地运行', 'Local run')}
              <select onChange={(event) => { setSelectedRunId(event.target.value); setHpcStaged(false); setHpcObservation(null); setRemoteResult(null) }} value={selectedRunId}>
                <option value="">{tr('请选择已物化运行', 'Select a materialized run')}</option>
                {runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id}</option>)}
              </select>
            </label>
            <dl className="detail-list run-summary">
              <div><dt>Plan</dt><dd>{shortenHash(selectedRun?.plan_sha256)}</dd></div>
              <div><dt>{tr('远端目录', 'Remote directory')}</dt><dd>{selectedRun ? `${hpcProfile.allowed_root.replace(/\/$/, '')}/${selectedRun.run_id}` : '—'}</dd></div>
              <div><dt>{tr('本地输入', 'Local inputs')}</dt><dd>{selectedRun ? tr('已生成', 'Generated') : '—'}</dd></div>
              <div><dt>{tr('远端 POTCAR', 'Remote POTCAR')}</dt><dd>{hpcStaged ? tr('已服务器端生成', 'Built on server') : tr('未确认', 'Unconfirmed')}</dd></div>
              <div><dt>Slurm Job</dt><dd>{hpcJobId ?? selectedRun?.job_id ?? tr('未提交', 'Not submitted')}</dd></div>
              <div><dt>{tr('调度状态', 'Scheduler state')}</dt><dd>{hpcObservation?.report.observation?.state ?? tr('未观测', 'Not observed')}</dd></div>
            </dl>
            <div className="run-gates">
              <section>
                <strong>{tr('1. 远端准备', '1. Remote staging')}</strong>
                <label className="confirmation-row"><input checked={confirmRemoteWrite} onChange={(event) => setConfirmRemoteWrite(event.target.checked)} type="checkbox" />{selectedRunRemoteReady
                  ? tr('确认只把现有远端 POTCAR 复制到本地工作文件夹，不修改远端。', 'Copy the existing remote POTCAR to the local work folder without modifying the remote run.')
                  : tr('确认只在白名单根目录新建一个运行目录，禁止覆盖和删除。', 'Create one new run directory only under the allowlisted root; never overwrite or delete.')}</label>
                <button disabled={!hpcConnected || !selectedRun || !confirmRemoteWrite || busy !== null} onClick={() => void stageRemoteRun()} type="button">{selectedRunRemoteReady
                  ? tr('下载现有 POTCAR 到本地', 'Download existing POTCAR')
                  : tr('新建目录、上传输入、生成 POTCAR', 'Create directory, upload inputs, build POTCAR')}</button>
              </section>
              <section>
                <strong>{tr('2. 提交 Slurm', '2. Submit Slurm')}</strong>
                <label className="confirmation-row"><input checked={confirmSubmit} onChange={(event) => setConfirmSubmit(event.target.checked)} type="checkbox" />{tr('确认以当前 plan digest 执行固定的 sbatch 命令。', 'Run the fixed sbatch command for the current plan digest.')}</label>
                <button disabled={!hpcConnected || !selectedRun || selectedRun.submitted || !hpcStaged || !confirmSubmit || busy !== null} onClick={() => void submitRemoteRun()} type="button">{selectedRun?.submitted ? tr('作业已提交', 'Job already submitted') : tr('提交一次作业', 'Submit one job')}</button>
              </section>
              <section>
                <strong>{tr('3. 只读观测', '3. Read-only observation')}</strong>
                <p>{tr('仅运行固定字段的 squeue / sacct，不提供取消、删除或自动续算。', 'Only fixed-field squeue/sacct commands are available; no cancel, delete, or automatic restart.')}</p>
                <button disabled={!hpcConnected || !selectedRun || !(hpcJobId || selectedRun.job_id) || busy !== null} onClick={() => void observeRemoteRun()} type="button">{tr('刷新调度状态', 'Refresh scheduler state')}</button>
              </section>
              <section>
                <strong>{tr('4. 拉取并解析', '4. Pull and parse')}</strong>
                <label className="confirmation-row"><input checked={confirmResultPull} onChange={(event) => setConfirmResultPull(event.target.checked)} type="checkbox" />{tr('确认在本地项目中新建结果快照；不下载 POTCAR/WAVECAR/CHGCAR。', 'Create a new local result snapshot without downloading POTCAR/WAVECAR/CHGCAR.')}</label>
                <button disabled={!hpcConnected || !selectedRun || !terminal || !confirmResultPull || busy !== null} onClick={() => void pullRemoteResults()} type="button">{tr('下载受限输出并解析', 'Download bounded outputs and parse')}</button>
              </section>
            </div>
          </article>
        </div>
      </section>
    )
  }

  const renderLegacyResults = () => (
    <section className="results-workbench">
      <div className="section-heading">
        <div>
          <span className="eyebrow">{remoteResult ? 'BOUND HPC RESULT' : 'SYNTHETIC RESULT'}</span>
          <h2>{tr('结果与科学审核', 'Results and scientific review')}</h2>
          <p>{tr('运行终止、数值收敛与人工科学接受是三个独立状态。', 'Process termination, numerical convergence, and human scientific acceptance are independent states.')}</p>
        </div>
        <span className="nonproduction-badge"><LockKeyhole size={14} /> {remoteResult ? tr('等待人工科学审核', 'Awaiting scientific review') : tr('非生产数据', 'Non-production data')}</span>
      </div>
      <div className="results-grid">
        <article className="result-hero">
          <div className="result-orbit"><Activity size={30} /></div>
          <span>Final TOTEN</span>
          <strong>{result?.energy ? formatNumber(result.energy.free_energy_eV, 6) : '—'} eV</strong>
          <small>{result ? `VASP ${result.detected_vasp_version ?? 'unknown'}` : tr('运行或导入结果后显示', 'Shown after running or importing results')}</small>
        </article>
        <article className="result-card">
          <span>{tr('电子收敛', 'Electronic convergence')}</span>
          <strong>{result?.convergence.electronic ?? '—'}</strong>
          <small>{tr('不等同于科学接受', 'Not equivalent to scientific acceptance')}</small>
        </article>
        <article className="result-card">
          <span>{tr('离子收敛', 'Ionic convergence')}</span>
          <strong>{result?.convergence.ionic ?? '—'}</strong>
          <small>{tr('独立解析证据', 'Independent parsed evidence')}</small>
        </article>
        <article className="result-card">
          <span>{tr('最大受力', 'Maximum force')}</span>
          <strong>{formatNumber(result?.forces?.maximum_norm_eV_per_angstrom, 4)} eV/Å</strong>
          <small>{remoteResult ? tr('来自绑定的远端输出快照', 'From the bound remote output snapshot') : tr('来自合成 OUTCAR', 'From synthetic OUTCAR')}</small>
        </article>
        <article className="review-card">
          <div>
            <span className="eyebrow">HUMAN GATE</span>
            <h3>{resultReviewed ? `${tr('人工审核', 'Human review')}: ${resultDecision}` : tr('等待结果审核', 'Awaiting result review')}</h3>
            <p>
              {remoteResult
                ? tr(`运行绑定状态：${remoteResult.binding.status}。科学接受仍必须由人工单独决定。`, `Run binding status: ${remoteResult.binding.status}. Scientific acceptance still requires a separate human decision.`)
                : <>{tr('即使解析显示正常收敛，这份合成结果也永久保持', 'Even when parsing shows convergence, this synthetic result permanently remains')}<code> scientific_result_eligible=false</code>.</>}
            </p>
            {remoteResult && !resultReviewed && (
              <div className="result-review-form">
                <label>{tr('审核人', 'Reviewer')}<input onChange={(event) => setReviewer(event.target.value)} value={reviewer} /></label>
                <label>{tr('审核说明', 'Review note')}<input onChange={(event) => setReviewNote(event.target.value)} value={reviewNote} /></label>
              </div>
            )}
          </div>
          <div className="review-actions">
            {remoteResult && (
              <button className="secondary-button" disabled={!result || resultReviewed || busy !== null} onClick={() => void reviewResult(false)} type="button">
                {tr('拒绝结果', 'Reject result')}
              </button>
            )}
            <button className="primary-button" disabled={!result || resultReviewed || busy !== null} onClick={() => void reviewResult(Boolean(remoteResult))} type="button">
              <BookOpenCheck size={16} /> {resultReviewed ? tr('已审核', 'Reviewed') : remoteResult ? tr('接受科学结果', 'Accept scientific result') : tr('记录 POC 审核', 'Record POC review')}
            </button>
          </div>
        </article>
      </div>
      <div className="energy-analysis-grid">
        <article className="energy-ledger-card">
          <span className="eyebrow">REVIEWED ENERGY LEDGER</span>
          <h3>{tr('已接受能量账本', 'Accepted energy ledger')}</h3>
          {reviewedEnergies.length === 0 ? (
            <p>{tr('尚无满足“提交资格 + 完整绑定 + 人工接受”的能量记录。', 'No energy record yet satisfies submission eligibility, complete binding, and human acceptance.')}</p>
          ) : (
            <div className="energy-ledger">
              {reviewedEnergies.map((energy) => (
                <div key={energy.record_sha256}>
                  <span><strong>{energy.energy_id}</strong><small>{energy.kind}</small></span>
                  <b>{formatNumber(energy.value_eV, 6)} eV</b>
                  <code>{shortenHash(energy.record_sha256)}</code>
                </div>
              ))}
            </div>
          )}
        </article>
        <article className="energy-derive-card">
          <span className="eyebrow">SAME-FAMILY DERIVATION</span>
          <h3>{tr('线性能量组合', 'Linear energy combination')}</h3>
          <label>{tr('推导 ID', 'Derivation ID')}<input onChange={(event) => setDerivationId(event.target.value)} value={derivationId} /></label>
          <label>{tr('系数 JSON', 'Coefficient JSON')}<textarea onChange={(event) => setCoefficientText(event.target.value)} spellCheck={false} value={coefficientText} /></label>
          <label className="confirmation-row"><input checked={confirmDerivationWrite} onChange={(event) => setConfirmDerivationWrite(event.target.checked)} type="checkbox" />{tr('确认保存不可覆盖的推导记录。', 'Save a non-overwriting derivation record.')}</label>
          <button className="secondary-button" disabled={!currentProject || reviewedEnergies.length === 0 || !confirmDerivationWrite || busy !== null} onClick={() => void deriveEnergy()} type="button">
            <Gauge size={15} /> {tr('兼容性检查并推导', 'Check compatibility and derive')}
          </button>
          {energyDerivation && <output>{energyDerivation.status} · {formatNumber(energyDerivation.value_eV, 6)} eV</output>}
          <small>{tr('这里只做同一 energy family、同一能量字段的可审计线性组合。吸附能、形成能、自由能、CHE 与反应网络还需要显式参考态和热化学校正审核。', 'This is an auditable linear combination within one energy family and energy field. Adsorption, formation, free-energy, CHE, and reaction-network interpretations still require explicit reference-state and thermochemistry review.')}</small>
        </article>
      </div>
    </section>
  )

  const renderResults = () => {
    const convergence = result?.convergence
    const criteria = convergence?.criteria
    const finalStructure = remoteResult?.final_structure?.viewer ?? structure?.viewer ?? null
    const initialStructure = remoteResult?.initial_structure?.viewer ?? structure?.viewer ?? null
    const outcomeTone = result?.scientifically_complete ? 'success' : result ? 'warning' : 'neutral'
    return (
      <section className="results-workbench result-first-page">
        <div className="section-heading">
          <div>
            <span className="eyebrow">{remoteResult ? 'BOUND HPC RESULT' : 'RESULT SUMMARY'}</span>
            <h2>{tr('计算结果', 'Calculation Results')}</h2>
            <p>{tr('直接展示能量、结束原因、收敛状态、最终结构和自动诊断。', 'Energy, completion reason, convergence, final structure, and automatic diagnostics in one place.')}</p>
          </div>
          <span className={`result-outcome-badge ${outcomeTone}`}>
            {result ? (result.scientifically_complete ? tr('满足收敛标准并正常结束', 'Converged and completed normally') : tr('计算完成但需要查看诊断', 'Inspect diagnostics')) : tr('等待计算结果', 'Waiting for results')}
          </span>
        </div>

        <div className={`result-conclusion ${outcomeTone}`}>
          <div><Activity size={24} /></div>
          <span>
            <strong>{result ? tr(`结束原因：${result.completion_reason}`, `Completion: ${result.completion_reason}`) : tr('尚无结果', 'No result loaded')}</strong>
            <small>{result ? `${convergence?.calculation_type ?? 'unknown'} · VASP ${result.detected_vasp_version ?? 'unknown'} · ${result.termination.outcome}` : tr('从运行中心拉取结果，或运行合成示例。', 'Pull a run result or execute the synthetic example.')}</small>
          </span>
        </div>

        <div className="results-grid compact-results-grid">
          <article className="result-hero">
            <span>{tr('自由能 TOTEN', 'Free energy TOTEN')}</span>
            <strong>{formatNumber(result?.energy?.free_energy_eV, 6)} eV</strong>
            <small>{tr('OUTCAR 最终完整能量块', 'Final complete OUTCAR energy block')}</small>
          </article>
          <article className="result-card"><span>{tr('无熵能量', 'Energy without entropy')}</span><strong>{formatNumber(result?.energy?.energy_without_entropy_eV, 6)} eV</strong><small>energy without entropy</small></article>
          <article className="result-card"><span>{tr('σ→0 能量', 'Sigma→0 energy')}</span><strong>{formatNumber(result?.energy?.sigma_zero_energy_eV, 6)} eV</strong><small>{tr('跨结构比较时保持同一能量字段', 'Use one consistent energy field across structures')}</small></article>
          <article className="result-card"><span>{tr('最大受力', 'Maximum force')}</span><strong>{formatNumber(result?.forces?.maximum_norm_eV_per_angstrom, 4)} eV/Å</strong><small>{result?.forces ? `atom ${result.forces.maximum_atom_index_1based}` : '—'}</small></article>
        </div>

        <div className="result-structure-grid">
          <article className="result-structure-card">
            <div className="card-heading"><div><span className="eyebrow">{remoteResult ? 'POSCAR' : 'INPUT'}</span><h3>{tr('初始结构', 'Initial structure')}</h3></div><span className="model-badge">{tr('球棍', 'Ball-stick')}</span></div>
            <StructureViewer structure={initialStructure} />
          </article>
          <article className="result-structure-card featured">
            <div className="card-heading"><div><span className="eyebrow">{remoteResult ? 'CONTCAR' : 'CURRENT'}</span><h3>{tr('最终结果结构', 'Final result structure')}</h3></div><span className="model-badge">{remoteResult?.final_structure?.inspection.record?.reduced_formula ?? structure?.inspection.record?.reduced_formula ?? '—'}</span></div>
            <StructureViewer structure={finalStructure} />
          </article>
        </div>

        <div className="convergence-panel">
          <article>
            <span className="eyebrow">ELECTRONIC</span>
            <h3>{convergence?.electronic ?? '—'}</h3>
            <dl className="detail-list">
              <div><dt>EDIFF</dt><dd>{criteria?.EDIFF_eV ?? '—'} eV</dd></div>
              <div><dt>{tr('最终电子步', 'Final electronic step')}</dt><dd>{convergence?.final_electronic_step ?? '—'} / {criteria?.NELM ?? '—'}</dd></div>
            </dl>
          </article>
          <article>
            <span className="eyebrow">IONIC / TASK</span>
            <h3>{convergence?.ionic ?? '—'}</h3>
            <dl className="detail-list">
              <div><dt>EDIFFG</dt><dd>{criteria?.EDIFFG_eV_per_angstrom ?? '—'} eV/Å</dd></div>
              <div><dt>{tr('离子步', 'Ionic steps')}</dt><dd>{convergence?.ionic_steps_completed ?? '—'} / {criteria?.NSW ?? '—'}</dd></div>
              <div><dt>IBRION</dt><dd>{criteria?.IBRION ?? '—'}</dd></div>
            </dl>
          </article>
          <article>
            <span className="eyebrow">AUTOMATIC DIAGNOSTICS</span>
            <h3>{result ? `${severityCount(result.diagnostics, 'error')} ${tr('错误', 'errors')} · ${severityCount(result.diagnostics, 'warning')} ${tr('警告', 'warnings')}` : '—'}</h3>
            <div className="diagnostic-list compact">
              {result?.diagnostics.length ? result.diagnostics.map((item) => <div className={`diagnostic ${item.severity}`} key={item.code}><strong>{item.code}</strong><span>{item.message}</span></div>) : <p>{tr('没有解析诊断。', 'No parser diagnostics.')}</p>}
            </div>
          </article>
        </div>

        {result?.vibrations && (
          <article className="vibration-panel">
            <div className="card-heading"><div><span className="eyebrow">VIBRATIONAL THERMOCHEMISTRY</span><h3>{tr('振动频率与热化学校正', 'Frequencies and thermochemical correction')}</h3></div><span className={result.vibrations.imaginary_mode_count ? 'warning-chip' : 'success-chip'}>{result.vibrations.imaginary_mode_count} {tr('个虚频', 'imaginary')}</span></div>
            <div className="thermo-controls">
              <label>{tr('温度 (K)', 'Temperature (K)')}<input min="1" onChange={(event) => setThermoTemperature(event.target.value)} type="number" value={thermoTemperature} /></label>
              <label>{tr('低频截止 (cm⁻¹)', 'Low-frequency cutoff (cm⁻¹)')}<input min="0" onChange={(event) => setThermoCutoff(event.target.value)} type="number" value={thermoCutoff} /></label>
              <button className="secondary-button" disabled={busy !== null} onClick={() => void calculateThermochemistry()} type="button">{tr('计算校正', 'Calculate correction')}</button>
            </div>
            <div className="thermo-summary">
              <div><span>ZPE</span><strong>{formatNumber(thermochemistry?.zero_point_energy_eV ?? result.vibrations.zero_point_energy_eV, 5)} eV</strong></div>
              <div><span>U<sub>vib</sub>(T)</span><strong>{formatNumber(thermochemistry?.thermal_vibrational_energy_eV, 5)} eV</strong></div>
              <div><span>T·S<sub>vib</sub></span><strong>{formatNumber(thermochemistry?.entropy_term_eV, 5)} eV</strong></div>
              <div><span>G<sub>corr</sub></span><strong>{formatNumber(thermochemistry?.free_energy_correction_eV, 5)} eV</strong></div>
            </div>
            <div className="mode-table"><div className="mode-table-head"><span>Mode</span><span>cm⁻¹</span><span>meV</span><span>{tr('状态', 'Status')}</span></div>{result.vibrations.modes.map((mode) => <div key={mode.mode_index}><span>{mode.mode_index}</span><span>{formatNumber(mode['wavenumber_cm-1'], 2)}</span><span>{formatNumber(mode.energy_meV, 3)}</span><span className={mode.imaginary ? 'mode-imaginary' : ''}>{mode.imaginary ? tr('虚频', 'imaginary') : tr('实频', 'real')}</span></div>)}</div>
            <small>{tr('当前模型仅包含谐振动贡献；气相平动、转动和标准态需要另行配置。', 'This model contains harmonic vibrations only; gas translation, rotation, and standard-state terms require separate treatment.')}</small>
          </article>
        )}
      </section>
    )
  }

  const renderAnalysis = () => (
    <section className="reaction-analysis-page">
      <div className="section-heading">
        <div><span className="eyebrow">TEMPLATE-DRIVEN CHE</span><h2>{tr('反应自由能与台阶图', 'Reaction Free Energy')}</h2><p>{tr('用同一个通用引擎绑定多次计算结果；HER 与 OER 只切换反应模板。', 'Bind multiple calculation results to one generic engine; HER and OER differ only by the mechanism template.')}</p></div>
        <span className="nonproduction-badge"><ChartNoAxesCombined size={14} /> CHE · HER / OER</span>
      </div>
      <div className="analysis-layout">
        <article className="analysis-form-card">
          <label>{tr('反应模板', 'Reaction template')}<select onChange={(event) => { setReactionTemplateId(event.target.value as ReactionTemplate['template_id']); setReactionAnalysis(null) }} value={reactionTemplateId}>{reactionTemplates.map((template) => <option key={template.template_id} value={template.template_id}>{template.template_id === 'her-che' ? 'HER · CHE' : 'OER · AEM/CHE'}</option>)}</select></label>
          <div className="state-binding-list">
            {activeReactionTemplate?.state_keys.map((key) => (
              <section className="state-binding-row" key={key}>
                <strong>{key.replace('_star', '*')}</strong>
                <label>{tr('绑定计算结果', 'Bind result')}<select onChange={(event) => bindReactionResult(key, event.target.value)} value={reactionBindings[key] ?? ''}><option value="">{tr('手动输入', 'Manual value')}</option>{calculationResults.map((item) => <option disabled={item.energy_eV == null} key={item.run_id} value={item.run_id}>{item.run_id} · {formatNumber(item.energy_eV, 4)} eV</option>)}</select></label>
                <label>E<sub>DFT</sub> (eV)<input onChange={(event) => { setReactionEnergies((current) => ({ ...current, [key]: event.target.value })); setReactionAnalysis(null) }} type="number" value={reactionEnergies[key] ?? ''} /></label>
                <label>G<sub>corr</sub> (eV)<input onChange={(event) => { setReactionCorrections((current) => ({ ...current, [key]: event.target.value })); setReactionAnalysis(null) }} placeholder="0.000" type="number" value={reactionCorrections[key] ?? ''} /></label>
              </section>
            ))}
          </div>
          <div className="reservoir-grid">
            <label>G(H₂) (eV)<input onChange={(event) => setH2Energy(event.target.value)} type="number" value={h2Energy} /></label>
            {reactionTemplateId === 'oer-aem-che' && <label>G(H₂O) (eV)<input onChange={(event) => setH2oEnergy(event.target.value)} type="number" value={h2oEnergy} /></label>}
            <label>T (K)<input onChange={(event) => setReactionTemperature(event.target.value)} type="number" value={reactionTemperature} /></label>
            <label>U (V)<input onChange={(event) => setReactionPotential(event.target.value)} step="0.01" type="number" value={reactionPotential} /></label>
            <label>pH<input max="14" min="0" onChange={(event) => setReactionPh(event.target.value)} step="0.1" type="number" value={reactionPh} /></label>
            <label>{tr('电极标尺', 'Potential scale')}<select onChange={(event) => setReferenceElectrode(event.target.value as 'RHE' | 'SHE')} value={referenceElectrode}><option value="RHE">RHE</option><option value="SHE">SHE</option></select></label>
          </div>
          <button className="primary-button" disabled={!activeReactionTemplate || busy !== null} onClick={() => void calculateReactionAnalysis()} type="button"><ChartNoAxesCombined size={16} /> {tr('计算并绘制台阶图', 'Calculate and plot')}</button>
          <small>{tr('绑定结果时自动检查 energy family；外部 H₂/H₂O 参考能和热化学校正始终显式显示。', 'Bound results are checked for a shared energy family; external H₂/H₂O references and corrections remain explicit.')}</small>
        </article>
        <article className="diagram-card">
          <div className="card-heading"><div><span className="eyebrow">FREE-ENERGY LANDSCAPE</span><h3>{reactionTemplateId === 'her-che' ? 'HER' : 'OER'} · {referenceElectrode}</h3></div>{reactionAnalysis && <span className="model-badge">U = {reactionAnalysis.conditions.potential_volts.toFixed(2)} V · pH {reactionAnalysis.conditions.pH}</span>}</div>
          <FreeEnergyDiagram analysis={reactionAnalysis} emptyLabel={tr('填入或绑定各状态能量，然后生成台阶图。', 'Enter or bind state energies, then generate the diagram.')} />
          {reactionAnalysis && <div className="analysis-metrics"><div><span>{tr('势限制步骤', 'Potential-limiting step')}</span><strong>{reactionAnalysis.potential_limiting_step}</strong></div><div><span>{reactionTemplateId === 'her-che' ? '|ΔG(H*)|' : tr('限制电位', 'Limiting potential')}</span><strong>{formatNumber(reactionAnalysis.descriptor_eV ?? reactionAnalysis.limiting_potential_volts, 3)} {reactionTemplateId === 'her-che' ? 'eV' : 'V'}</strong></div><div><span>{tr('过电位', 'Overpotential')}</span><strong>{formatNumber(reactionAnalysis.overpotential_volts, 3)} V</strong></div></div>}
          {reactionAnalysis && <div className="step-table">{reactionAnalysis.step_free_energies_eV.map((step, index) => <div className={reactionAnalysis.potential_limiting_step === index + 1 ? 'limiting' : ''} key={index}><span>Step {index + 1}</span><strong>{formatNumber(step, 3)} eV</strong></div>)}</div>}
        </article>
      </div>
    </section>
  )

  void renderLegacyResults
  void reviewResult

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"><Atom size={24} /></div>
          <div>
            <strong>CatEx</strong>
            <span>Catalysis Exploration Workbench</span>
          </div>
        </div>
        <nav className="view-tabs" aria-label={tr('工作台视图', 'Workbench views')}>
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <button
                className={activeView === item.id ? 'active' : ''}
                key={item.id}
                onClick={() => setActiveView(item.id)}
                type="button"
              >
                <Icon size={15} /> {language === 'zh-CN' ? item.labelZh : item.labelEn}
              </button>
            )
          })}
        </nav>
        <div className="environment-status">
          <div className="language-menu" ref={languageMenuRef}>
            <button
              aria-expanded={languageMenuOpen}
              aria-haspopup="menu"
              aria-label={tr('切换语言', 'Switch language')}
              className="language-menu-trigger"
              onClick={() => setLanguageMenuOpen((current) => !current)}
              type="button"
            >
              <Languages size={14} />
              <span>{language === 'zh-CN' ? '中文' : 'EN'}</span>
              <ChevronDown className={languageMenuOpen ? 'open' : ''} size={13} />
            </button>
            {languageMenuOpen && (
              <div className="language-menu-popover" role="menu" aria-label={tr('语言选择', 'Language selector')}>
                <button
                  aria-checked={language === 'zh-CN'}
                  className={language === 'zh-CN' ? 'active' : ''}
                  onClick={() => {
                    setLanguage('zh-CN')
                    setNotice({ tone: 'neutral', message: DEFAULT_NOTICE_ZH })
                    setLanguageMenuOpen(false)
                  }}
                  role="menuitemradio"
                  type="button"
                >
                  <span><strong>中文</strong><small>简体中文</small></span>
                  {language === 'zh-CN' && <Check size={14} />}
                </button>
                <button
                  aria-checked={language === 'en'}
                  className={language === 'en' ? 'active' : ''}
                  onClick={() => {
                    setLanguage('en')
                    setNotice({ tone: 'neutral', message: DEFAULT_NOTICE_EN })
                    setLanguageMenuOpen(false)
                  }}
                  role="menuitemradio"
                  type="button"
                >
                  <span><strong>EN</strong><small>English</small></span>
                  {language === 'en' && <Check size={14} />}
                </button>
              </div>
            )}
          </div>
          <span className={`connection-light ${connectionState}`} />
          <div className="environment-copy">
            <strong>{connectionState === 'online' ? tr('本地工作台', 'Local workbench') : tr('API 状态', 'API status')}</strong>
            <span>{capabilities ? `core v${capabilities.catex_version}` : connectionState}</span>
          </div>
        </div>
      </header>

      <aside className="icon-rail" aria-label={tr('主要导航', 'Primary navigation')}>
        <button
          className={`rail-button ${activeView === 'projects' ? 'active' : ''}`}
          onClick={() => setActiveView('projects')}
          title={tr('项目工作台', 'Project workbench')}
          type="button"
        >
          <LayoutDashboard size={19} />
        </button>
        <button
          className="rail-button"
          onClick={() => setActiveView('projects')}
          title="Artifact"
          type="button"
        >
          <Database size={19} />
        </button>
        <button
          className={`rail-button ${activeView === 'runs' ? 'active' : ''}`}
          onClick={() => setActiveView('runs')}
          title={tr('运行中心', 'Run center')}
          type="button"
        >
          <Activity size={19} />
        </button>
        <div className="rail-spacer" />
        <button className="rail-button safety" onClick={() => setActiveView('runs')} title={tr('HPC 默认未连接', 'HPC disconnected by default')} type="button">
          {hpcConnected ? <Server size={19} /> : <ServerOff size={19} />}
        </button>
      </aside>

      <aside className="project-panel">
        <div className="project-kicker">
          <FlaskConical size={14} /> {currentProject ? tr('持久化项目', 'Persistent project') : tr('合成验收项目', 'Synthetic acceptance')}
        </div>
        <h1>{currentProject?.title ?? tr('NaCl 结构到计算结果', 'NaCl structure to calculation results')}</h1>
        <p>
          {currentProject
            ? `${currentProject.purpose} · ${currentProject.artifact_count} ${tr('个 Artifact', 'artifacts')}`
            : tr('用最小案例验证交互、科学门禁与 CatEx 核心边界。', 'Validate interaction, scientific gates, and CatEx boundaries with a minimal case.')}
        </p>

        <div className="progress-block">
          <div className="progress-label">
            <span>{tr('流程进度', 'Workflow progress')}</span>
            <strong>{completedCount}/{nodes.length || 8}</strong>
          </div>
          <div className="progress-track">
            <span style={{ width: `${(completedCount / Math.max(nodes.length, 1)) * 100}%` }} />
          </div>
        </div>

        <div className="wizard-heading">
          <span>{tr('模板向导', 'Template guide')}</span>
          <small>{tr('按顺序完成', 'Complete in order')}</small>
        </div>
        <ol className="wizard-steps">
          {nodes.map((node, index) => (
            <li
              className={`${node.data.status} ${selectedNodeId === node.id ? 'selected' : ''}`}
              key={node.id}
            >
              <button onClick={() => { setSelectedNodeId(node.id); setActiveView(NODE_VIEW[node.data.definition.type_id] ?? 'workflow') }} type="button">
                <span className="step-index">
                  {node.data.status === 'success' ? <Check size={13} /> : index + 1}
                </span>
                <span>
                  <strong>{localizeNodeDefinition(node.data.definition, language).title}</strong>
                  <small>{node.data.detail ?? tr('尚未开始', 'Not started')}</small>
                </span>
                <ChevronRight size={14} />
              </button>
            </li>
          ))}
        </ol>

        <div className="safety-summary">
          <LockKeyhole size={15} />
          <div>
            <strong>{tr('本地持久化', 'Local persistence')}</strong>
            <span>{tr('SSH 默认断开；远端写入和提交需逐步确认', 'SSH is disconnected by default; remote writes and submission require separate approval.')}</span>
          </div>
        </div>
      </aside>

      <main className="workspace">
        <section className="project-strip">
          <div className="breadcrumb">
            <span>{tr('项目', 'Project')}</span><ChevronRight size={12} />
            <strong>{currentProject?.title ?? tr('未保存 POC', 'Unsaved POC')}</strong>
          </div>
          <div className="action-row">
            <input
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) importStructureReplacement(file)
                event.target.value = ''
              }}
              ref={fileInputRef}
              type="file"
            />
            <button
              className="secondary-button"
              disabled={busy !== null || connectionState !== 'online'}
              onClick={() => fileInputRef.current?.click()}
              type="button"
            >
              <FileUp size={15} /> {tr('上传结构', 'Upload structure')}
            </button>
            <button
              className="secondary-button accent"
              disabled={busy !== null || connectionState !== 'online'}
              onClick={loadSyntheticStructure}
              type="button"
            >
              <Sparkles size={15} /> {tr('载入示例', 'Load example')}
            </button>
            <button
              className="primary-button"
              disabled={!structureReady || busy !== null}
              onClick={() => void runSyntheticWorkflow()}
              type="button"
            >
              {busy === 'workflow' ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}
              {tr('运行合成流程', 'Run synthetic workflow')}
            </button>
          </div>
        </section>

        <div className={`notice tone-${notice.tone}`}>
          {notice.tone === 'error' || notice.tone === 'warning' ? (
            <AlertTriangle size={15} />
          ) : notice.tone === 'success' ? (
            <Check size={15} />
          ) : (
            <Info size={15} />
          )}
          <span>{notice.message}</span>
        </div>

        <div className="workspace-content">
          {activeView === 'projects' && renderProjects()}
          {activeView === 'workflow' && renderWorkflow()}
          {activeView === 'structure' && renderStructure()}
          {activeView === 'protocol' && renderProtocol()}
          {activeView === 'runs' && renderRuns()}
          {activeView === 'results' && renderResults()}
          {activeView === 'analysis' && renderAnalysis()}
        </div>
      </main>

    </div>
  )
}

export default App
