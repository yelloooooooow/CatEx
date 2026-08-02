import type { Language } from './i18n'
import type { NodeDefinition } from './types'

export type WorkflowNodeGroupId =
  | 'experimental'
  | 'input'
  | 'preparation'
  | 'calculation'
  | 'analysis'

export interface WorkflowNodeGroup {
  id: WorkflowNodeGroupId
  labelZh: string
  labelEn: string
  typeIds: string[]
}

export interface WorkflowNodeGuidance {
  purposeZh: string
  purposeEn: string
  useWhenZh: string
  useWhenEn: string
  requirementsZh: string[]
  requirementsEn: string[]
  outputsZh: string[]
  outputsEn: string[]
  cautionZh?: string
  cautionEn?: string
}

export const WORKFLOW_NODE_GROUPS: WorkflowNodeGroup[] = [
  {
    id: 'experimental',
    labelZh: '实验约束建模',
    labelEn: 'Experimental modeling',
    typeIds: [
      'experiment.evidence.prepare',
      'structure.catalog.prepare',
      'experiment.model.infer',
      'review.candidate_models',
    ],
  },
  {
    id: 'input',
    labelZh: '输入',
    labelEn: 'Input',
    typeIds: ['vasp.input.prepare'],
  },
  {
    id: 'preparation',
    labelZh: '可选预处理',
    labelEn: 'Optional preparation',
    typeIds: ['mlip.chgnet.relax'],
  },
  {
    id: 'calculation',
    labelZh: 'VASP 计算',
    labelEn: 'VASP calculations',
    typeIds: ['vasp.relax', 'vasp.static', 'vasp.frequency', 'vasp.dos', 'vasp.md'],
  },
  {
    id: 'analysis',
    labelZh: '结果',
    labelEn: 'Results',
    typeIds: ['results.collect'],
  },
]

const guidance: Record<string, WorkflowNodeGuidance> = {
  'experiment.evidence.prepare': {
    purposeZh: '导入现有的 XRD、ICP、EDS、XPS、TEM 等表征，并检查自动提取的范围。',
    purposeEn: 'Import available XRD, ICP, EDS, XPS, TEM, and other measurements, then review the extracted ranges.',
    useWhenZh: '实验制备的材料需要先转换为可计算的结构假设时使用。双击进入“实验建模”页面。',
    useWhenEn: 'Use when an experimentally prepared material must be translated into calculable structure hypotheses. Double-click to open Experimental Models.',
    requirementsZh: ['已打开项目', '至少一项数据文件或简短实验结论；其他表征可逐步补充'],
    requirementsEn: ['An open project', 'At least one data file or short conclusion; other measurements may be added progressively'],
    outputsZh: ['版本化实验约束集', '自动提取范围与缺失信息提示'],
    outputsEn: ['Versioned experimental constraint set', 'Extracted ranges and missing-evidence warnings'],
    cautionZh: '不同样品或处理条件的数据应在结论或测试条件中明确说明。',
    cautionEn: 'Identify data from materially different specimens or treatments in the conclusion or conditions.',
  },
  'structure.catalog.prepare': {
    purposeZh: '组合项目结构、论文结构、OPTIMADE 和可选 Materials Project 快照。',
    purposeEn: 'Combine project structures, literature structures, OPTIMADE, and optional Materials Project snapshots.',
    useWhenZh: '需要为实验约束寻找可追溯母体结构时使用。',
    useWhenEn: 'Use when traceable parent structures are needed for the experimental constraints.',
    requirementsZh: ['元素范围', '至少一个项目结构或数据库快照', '来源与引用信息'],
    requirementsEn: ['Element scope', 'At least one project structure or database snapshot', 'Source and citation metadata'],
    outputsZh: ['不可变结构目录快照'],
    outputsEn: ['Immutable structure catalog snapshot'],
    cautionZh: '数据库结构只是母体假设，不等于实验样品的真实原子结构。',
    cautionEn: 'A database structure is a parent hypothesis, not the real atomic structure of the sample.',
  },
  'experiment.model.infer': {
    purposeZh: '用本地规则或可选 GPT 规划器生成有限、可复核的结构候选。',
    purposeEn: 'Generate a bounded, reviewable candidate set with the local rule planner or optional GPT planner.',
    useWhenZh: '实验约束版本和母体结构目录都已准备好时使用。',
    useWhenEn: 'Use after both an evidence revision and a parent-structure catalog are ready.',
    requirementsZh: ['实验约束集', '结构目录', '明确候选数量与 XRD nuisance 参数'],
    requirementsEn: ['Evidence set', 'Structure catalog', 'Explicit candidate limits and XRD nuisance settings'],
    outputsZh: ['不可变推断报告', '候选结构与未解决假设'],
    outputsEn: ['Immutable inference report', 'Candidate structures and unresolved hypotheses'],
    cautionZh: '分数用于排序，不是后验概率，也不是通用实验误差阈值。',
    cautionEn: 'Scores rank evidence; they are neither posterior probabilities nor universal experimental error tolerances.',
  },
  'review.candidate_models': {
    purposeZh: '人工选择可进入项目结构库的代表性候选，并追加审核依据。',
    purposeEn: 'Select representative candidates for the project structure library and append a review rationale.',
    useWhenZh: '检查相匹配、成分、几何诊断和假设后使用。',
    useWhenEn: 'Use after inspecting phase support, composition, geometry diagnostics, and assumptions.',
    requirementsZh: ['不可变推断 run', '至少一个有效代表性候选', '审核者与依据'],
    requirementsEn: ['Immutable inference run', 'At least one valid representative', 'Reviewer and rationale'],
    outputsZh: ['已审核模型集'],
    outputsEn: ['Reviewed model set'],
    cautionZh: '审核代表“足以用于当前计算问题”，不代表确认唯一真实结构。',
    cautionEn: 'Approval means fit for the current calculation question, not confirmation of a unique real structure.',
  },
  'vasp.input.prepare': {
    purposeZh: '把当前项目中的结构、INCAR、KPOINTS、POTCAR 元数据和提交脚本整理成可验证的 VASP 输入状态。',
    purposeEn: 'Turn the project structure, INCAR, KPOINTS, POTCAR metadata, and job script into a validated VASP input state.',
    useWhenZh: '每条 VASP 计算链通常从这里开始。双击节点进入“协议与输入”页面导入或生成文件。',
    useWhenEn: 'Usually the first node in every VASP chain. Double-click it to open VASP Inputs and import or generate files.',
    requirementsZh: ['已创建项目', '有效 POSCAR 或项目结构', '计算协议与资源设置'],
    requirementsEn: ['An open project', 'A valid POSCAR or project structure', 'Protocol and resource settings'],
    outputsZh: ['已验证的计算状态', '可供下游计算复用的输入 provenance'],
    outputsEn: ['Validated calculation state', 'Input provenance reusable by downstream calculations'],
    cautionZh: 'POTCAR 原始内容不会写入工作流 JSON；只记录数据集顺序和校验信息。',
    cautionEn: 'Raw POTCAR content is never embedded in workflow JSON; only dataset order and verification metadata are recorded.',
  },
  'mlip.chgnet.relax': {
    purposeZh: '在本机使用 CHGNet 做快速预弛豫，为后续 VASP 优化提供更合理的初始几何。',
    purposeEn: 'Run a fast local CHGNet pre-relaxation to give VASP a better starting geometry.',
    useWhenZh: '初始结构可能存在较大应力或不合理近接、且希望减少昂贵 DFT 离子步时使用。',
    useWhenEn: 'Use when the initial geometry may be strained or have close contacts and you want to reduce expensive DFT ionic steps.',
    requirementsZh: ['上游计算状态', '本机 CHGNet 环境可用', '确认它只承担预弛豫角色'],
    requirementsEn: ['Upstream calculation state', 'Available local CHGNet runtime', 'Confirmation that this is pre-relaxation only'],
    outputsZh: ['预弛豫 POSCAR', '能量、最大力和位移摘要'],
    outputsEn: ['Pre-relaxed POSCAR', 'Energy, maximum-force, and displacement summary'],
    cautionZh: 'CHGNet 能量不能与 VASP 总能量混用；最终科学结论仍应由一致的 DFT 协议验证。',
    cautionEn: 'Do not mix CHGNet energies with VASP total energies; final scientific conclusions still require a consistent DFT protocol.',
  },
  'vasp.relax': {
    purposeZh: '执行离子弛豫并把最终 CONTCAR 作为下游结构来源。',
    purposeEn: 'Run ionic relaxation and provide the final CONTCAR to downstream stages.',
    useWhenZh: '需要优化吸附构型、表面、体相或缺陷结构时使用。',
    useWhenEn: 'Use for optimizing adsorbates, surfaces, bulk structures, or defects.',
    requirementsZh: ['上游计算状态', 'INCAR 中明确 NSW、IBRION、EDIFFG 与 ISIF', 'Slurm 与 VASP 可执行文件设置'],
    requirementsEn: ['Upstream calculation state', 'Explicit NSW, IBRION, EDIFFG, and ISIF', 'Slurm and VASP executable settings'],
    outputsZh: ['CONTCAR 最终结构', 'OUTCAR/OSZICAR', '能量、力、收敛结论与可选重启文件'],
    outputsEn: ['Final CONTCAR', 'OUTCAR/OSZICAR', 'Energy, forces, convergence conclusion, and optional restart files'],
    cautionZh: '“作业正常结束”不等同于“离子收敛”；结果页会分别展示终止原因和收敛状态。',
    cautionEn: 'A normally terminated job is not necessarily ionically converged; Results reports termination and convergence separately.',
  },
  'vasp.static': {
    purposeZh: '在固定几何上执行高精度单点能计算。',
    purposeEn: 'Run a high-accuracy single-point calculation on a fixed geometry.',
    useWhenZh: '需要可比较的最终总能量、CHGCAR 或后续电子结构分析时使用。',
    useWhenEn: 'Use for comparable final energies, CHGCAR generation, or downstream electronic-structure analysis.',
    requirementsZh: ['上游最终结构', '与比较对象一致的能量家族', '静态计算协议'],
    requirementsEn: ['Upstream final structure', 'An energy family consistent with comparison targets', 'Static calculation protocol'],
    outputsZh: ['静态总能量', '可选 CHGCAR/WAVECAR', '固定结构的计算 provenance'],
    outputsEn: ['Static total energy', 'Optional CHGCAR/WAVECAR', 'Fixed-geometry provenance'],
    cautionZh: '吸附能与反应自由能只能混合使用协议兼容、POTCAR 顺序一致的结果。',
    cautionEn: 'Adsorption and reaction energies may only combine protocol-compatible results with consistent POTCAR ordering.',
  },
  'vasp.frequency': {
    purposeZh: '通过有限差分得到振动频率、零点能和热力学校正所需数据。',
    purposeEn: 'Use finite differences to obtain vibrational frequencies, zero-point energy, and thermochemical corrections.',
    useWhenZh: '需要对吸附中间体或分子做 ZPE/熵校正时使用。',
    useWhenEn: 'Use when adsorbates or molecules need ZPE and entropy corrections.',
    requirementsZh: ['已优化结构', '明确参与振动的原子', '严格电子收敛与有限差分设置'],
    requirementsEn: ['Relaxed structure', 'Explicit atoms included in vibration', 'Tight electronic convergence and finite-difference settings'],
    outputsZh: ['振动模式与虚频标记', 'ZPE 与谐振子热力学校正'],
    outputsEn: ['Vibrational modes and imaginary-mode flags', 'ZPE and harmonic thermochemistry corrections'],
    cautionZh: '应检查虚频及低频模式；自动数值汇总不能替代对不稳定构型的科学判断。',
    cautionEn: 'Inspect imaginary and low-frequency modes; a numerical summary cannot replace scientific assessment of unstable structures.',
  },
  'vasp.dos': {
    purposeZh: '准备并运行总态密度或投影态密度计算。',
    purposeEn: 'Prepare and run total or projected density-of-states calculations.',
    useWhenZh: '需要分析费米能级附近电子态、轨道贡献或金属位点电子结构时使用。',
    useWhenEn: 'Use to analyze states near the Fermi level, orbital contributions, or metal-site electronic structure.',
    requirementsZh: ['可靠的静态结构/电荷状态', '足够密的 KPOINTS', 'LORBIT、NEDOS 等显式设置'],
    requirementsEn: ['Reliable static geometry/charge state', 'Sufficiently dense KPOINTS', 'Explicit LORBIT and NEDOS settings'],
    outputsZh: ['DOS/PDOS 数据', '费米能级与投影信息'],
    outputsEn: ['DOS/PDOS data', 'Fermi level and projection metadata'],
    cautionZh: 'DOS 的展宽、k 点和自旋设置必须与体系类型匹配。',
    cautionEn: 'DOS smearing, k-point density, and spin settings must suit the system.',
  },
  'vasp.md': {
    purposeZh: '执行显式配置的从头算分子动力学并保留轨迹。',
    purposeEn: 'Run explicitly configured ab initio molecular dynamics and retain the trajectory.',
    useWhenZh: '研究有限温度稳定性、溶剂/界面动态或采样构型时使用。',
    useWhenEn: 'Use for finite-temperature stability, solvent/interface dynamics, or configuration sampling.',
    requirementsZh: ['初始结构', '温度、步长、系综与总步数', '足够的计算资源和存储预算'],
    requirementsEn: ['Initial structure', 'Temperature, timestep, ensemble, and step count', 'Adequate compute and storage budget'],
    outputsZh: ['XDATCAR/轨迹', '温度与能量时间序列'],
    outputsEn: ['XDATCAR/trajectory', 'Temperature and energy time series'],
    cautionZh: 'AIMD 成本和输出体积都很高；应在提交前核对资源、最长时间和存储位置。',
    cautionEn: 'AIMD is expensive and output-heavy; verify resources, walltime, and storage before submission.',
  },
  'results.collect': {
    purposeZh: '统一收集上游阶段的最终结构、能量、振动、DOS 和 provenance。',
    purposeEn: 'Collect final structures, energies, vibrations, DOS, and provenance from upstream stages.',
    useWhenZh: '放在一条或多条计算分支末端，作为结果页和反应分析的数据入口。',
    useWhenEn: 'Place at the end of one or more calculation branches as the data entry point for Results and Reaction Analysis.',
    requirementsZh: ['至少一个上游计算结果', '结果文件可读取', '能量家族信息完整'],
    requirementsEn: ['At least one upstream calculation result', 'Readable result files', 'Complete energy-family metadata'],
    outputsZh: ['统一结果摘要', '可绑定到台阶图的能量与校正项'],
    outputsEn: ['Unified result summary', 'Energies and corrections bindable to reaction diagrams'],
    cautionZh: '汇集节点不改变科学数据，只做解析、索引和 provenance 绑定。',
    cautionEn: 'The collector does not alter scientific data; it only parses, indexes, and binds provenance.',
  },
}

const fallback: WorkflowNodeGuidance = {
  purposeZh: '这是旧版或兼容节点。它仍可在已有工作流中运行，但不会出现在精简的新建节点库中。',
  purposeEn: 'This is a legacy or compatibility node. Existing workflows can still use it, but it is hidden from the simplified creation library.',
  useWhenZh: '仅在打开旧项目或复现历史工作流时使用。',
  useWhenEn: 'Use only when opening an older project or reproducing a historical workflow.',
  requirementsZh: ['检查节点端口与当前工作流是否兼容'],
  requirementsEn: ['Check that its ports remain compatible with the current workflow'],
  outputsZh: ['由节点定义声明的输出'],
  outputsEn: ['Outputs declared by the node definition'],
}

export function nodeGuidance(typeId: string): WorkflowNodeGuidance {
  return guidance[typeId] ?? fallback
}

export function groupedNodeDefinitions(
  registry: Map<string, NodeDefinition>,
): Array<WorkflowNodeGroup & { definitions: NodeDefinition[] }> {
  return WORKFLOW_NODE_GROUPS.map((group) => ({
    ...group,
    definitions: group.typeIds
      .map((typeId) => registry.get(typeId))
      .filter((definition): definition is NodeDefinition => Boolean(definition)),
  })).filter((group) => group.definitions.length > 0)
}

export function guidanceCopy(item: WorkflowNodeGuidance, language: Language) {
  return language === 'zh-CN'
    ? {
        purpose: item.purposeZh,
        useWhen: item.useWhenZh,
        requirements: item.requirementsZh,
        outputs: item.outputsZh,
        caution: item.cautionZh,
      }
    : {
        purpose: item.purposeEn,
        useWhen: item.useWhenEn,
        requirements: item.requirementsEn,
        outputs: item.outputsEn,
        caution: item.cautionEn,
      }
}
