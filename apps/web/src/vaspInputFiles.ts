const INCAR_TAG = /^[A-Z][A-Z0-9_]{0,31}$/
const SHA256 = /^[0-9a-fA-F]{64}$/

export interface ImportedKpoints {
  comment: string
  generation_mode: 'gamma' | 'monkhorst-pack'
  subdivisions: [number, number, number]
  shift: [number, number, number]
}

export interface ImportedPotcarDataset {
  element: string
  potential_label: string
  titel: string
  lexch: string
  zval: number
  enmax_eV: number
  sha256: string
}

export interface ImportedPotcarMetadata {
  schema_version: 'catex.potcar-metadata.v1'
  potential_family: string
  datasets: ImportedPotcarDataset[]
}

export interface ImportedSlurmProfile {
  job_name?: string
  partition?: string
  nodes?: number
  tasks_per_node?: number
  cpus_per_task?: number
  walltime?: string
  module_loads: string[]
  executable?: string
  mpi_plugin?: string
  ignored_lines: string[]
}

function nonEmptyString(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a non-empty string`)
  return value.trim()
}

function positiveNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
    throw new Error(`${field} must be a positive number`)
  }
  return value
}

export function parseIncarFile(text: string): Record<string, string> {
  const result: Record<string, string> = {}
  const statements = text
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .flatMap((line) => line.replace(/[!#].*$/, '').split(';'))
    .map((statement) => statement.trim())
    .filter(Boolean)

  if (statements.length === 0) throw new Error('INCAR does not contain any assignments')
  if (statements.length > 512) throw new Error('INCAR contains too many assignments')
  for (const statement of statements) {
    const match = /^([^=]+?)\s*=\s*(.+)$/.exec(statement)
    if (!match) throw new Error(`Unsupported INCAR statement: ${statement}`)
    const tag = match[1].trim().toUpperCase()
    const value = match[2].trim()
    if (!INCAR_TAG.test(tag) || !value) throw new Error(`Invalid INCAR assignment: ${statement}`)
    if (Object.hasOwn(result, tag)) throw new Error(`Duplicate INCAR tag: ${tag}`)
    result[tag] = value
  }
  return result
}

function triple(text: string, field: string, integerOnly: boolean): [number, number, number] {
  const tokens = text.trim().split(/\s+/)
  if (tokens.length !== 3) throw new Error(`${field} must contain exactly three numbers`)
  const values = tokens.map(Number)
  if (values.some((value) => !Number.isFinite(value))) throw new Error(`${field} contains an invalid number`)
  if (integerOnly && values.some((value) => !Number.isInteger(value) || value <= 0)) {
    throw new Error(`${field} must contain three positive integers`)
  }
  return values as [number, number, number]
}

export function parseKpointsFile(text: string): ImportedKpoints {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).map((line) => line.trim())
  while (lines.at(-1) === '') lines.pop()
  if (lines.length < 4 || lines.length > 5) {
    throw new Error('Only four- or five-line automatic-mesh KPOINTS files are supported')
  }
  const pointCount = Number(lines[1])
  if (!Number.isInteger(pointCount) || pointCount !== 0) {
    throw new Error('Only automatic-mesh KPOINTS with point count 0 are supported')
  }
  const modeToken = lines[2].toLowerCase()
  const generationMode = modeToken.startsWith('g')
    ? 'gamma'
    : modeToken.startsWith('m')
      ? 'monkhorst-pack'
      : null
  if (!generationMode) throw new Error('KPOINTS mesh mode must be Gamma or Monkhorst-Pack')
  return {
    comment: lines[0] || 'Imported automatic mesh',
    generation_mode: generationMode,
    subdivisions: triple(lines[3], 'KPOINTS subdivisions', true),
    shift: lines[4] ? triple(lines[4], 'KPOINTS shift', false) : [0, 0, 0],
  }
}

export function parsePotcarMetadataFile(text: string): ImportedPotcarMetadata {
  let payload: unknown
  try {
    payload = JSON.parse(text.replace(/^\uFEFF/, ''))
  } catch {
    throw new Error('POTCAR metadata is not valid JSON')
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('POTCAR metadata root must be an object')
  }
  const raw = payload as Record<string, unknown>
  if (raw.schema_version !== 'catex.potcar-metadata.v1') {
    throw new Error('POTCAR metadata schema_version is unsupported')
  }
  if (!Array.isArray(raw.datasets) || raw.datasets.length === 0 || raw.datasets.length > 32) {
    throw new Error('POTCAR metadata must contain one to thirty-two datasets')
  }
  const datasets = raw.datasets.map((item, index): ImportedPotcarDataset => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      throw new Error(`POTCAR dataset ${index + 1} must be an object`)
    }
    const dataset = item as Record<string, unknown>
    const sha256 = nonEmptyString(dataset.sha256, `datasets[${index}].sha256`)
    if (!SHA256.test(sha256)) throw new Error(`datasets[${index}].sha256 must be 64 hexadecimal characters`)
    return {
      element: nonEmptyString(dataset.element, `datasets[${index}].element`),
      potential_label: nonEmptyString(dataset.potential_label, `datasets[${index}].potential_label`),
      titel: nonEmptyString(dataset.titel, `datasets[${index}].titel`),
      lexch: nonEmptyString(dataset.lexch, `datasets[${index}].lexch`),
      zval: positiveNumber(dataset.zval, `datasets[${index}].zval`),
      enmax_eV: positiveNumber(dataset.enmax_eV, `datasets[${index}].enmax_eV`),
      sha256: sha256.toLowerCase(),
    }
  })
  return {
    schema_version: 'catex.potcar-metadata.v1',
    potential_family: nonEmptyString(raw.potential_family, 'potential_family'),
    datasets,
  }
}

export function parseSlurmScriptFile(text: string): ImportedSlurmProfile {
  const profile: ImportedSlurmProfile = { module_loads: [], ignored_lines: [] }
  const physicalLines = text.replace(/^\uFEFF/, '').split(/\r?\n/)
  if (physicalLines.length > 1000) throw new Error('Slurm script is too long')
  const lines: string[] = []
  let continued = ''
  for (const rawLine of physicalLines) {
    const line = rawLine.trimEnd()
    if (line.endsWith('\\')) {
      continued += `${line.slice(0, -1)} `
      continue
    }
    lines.push(continued + line)
    continued = ''
  }
  if (continued.trim()) lines.push(continued)
  let totalTasks: number | undefined
  const integerFields: Record<string, keyof ImportedSlurmProfile> = {
    nodes: 'nodes',
    'ntasks-per-node': 'tasks_per_node',
    'cpus-per-task': 'cpus_per_task',
  }
  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#!')) continue
    const directive = /^#SBATCH\s+--([a-z-]+)(?:=|\s+)(\S+)(?:\s+#.*)?$/i.exec(line)
    if (directive) {
      const [, key, value] = directive
      if (key === 'job-name') profile.job_name = value
      else if (key === 'partition') profile.partition = value
      else if (key === 'time') profile.walltime = value
      else if (key in integerFields) {
        const parsed = Number(value)
        if (!Number.isInteger(parsed) || parsed <= 0) throw new Error(`Invalid Slurm --${key} value`)
        Object.assign(profile, { [integerFields[key]]: parsed })
      } else if (key === 'ntasks') {
        const parsed = Number(value)
        if (!Number.isInteger(parsed) || parsed <= 0) throw new Error('Invalid Slurm --ntasks value')
        totalTasks = parsed
      } else profile.ignored_lines.push(line)
      continue
    }
    const moduleLoad = /^module\s+load\s+([A-Za-z0-9._/+:-]+)$/.exec(line)
    if (moduleLoad) {
      profile.module_loads.push(moduleLoad[1])
      continue
    }
    const srun = /^srun\s+--mpi=([A-Za-z0-9._-]+)\s+(\/[A-Za-z0-9._/+:-]+)$/.exec(line)
    if (srun) {
      profile.mpi_plugin = srun[1]
      profile.executable = srun[2]
      continue
    }
    if (!['set -euo pipefail', 'module purge', 'export OMP_NUM_THREADS=1', 'export MKL_NUM_THREADS=1'].includes(line)) {
      profile.ignored_lines.push(line)
    }
  }
  if (totalTasks !== undefined) {
    const nodes = profile.nodes ?? 1
    if (totalTasks % nodes !== 0) {
      throw new Error('Slurm --ntasks must be divisible by --nodes')
    }
    profile.tasks_per_node = totalTasks / nodes
  }
  if (profile.module_loads.length === 0 && !profile.executable && !profile.partition) {
    throw new Error('No supported Slurm fields were found')
  }
  return profile
}
