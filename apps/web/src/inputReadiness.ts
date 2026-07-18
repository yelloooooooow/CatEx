import type { Diagnostic } from './types'

export interface PotcarMetadataLike {
  datasets?: Array<Record<string, unknown>>
}

export interface StructureArtifactLike {
  artifact_id: string
  artifact_type: string
  created_at_utc: string
}

export interface CalculationPlanLike {
  plan_sha256: string
  diagnostics?: Diagnostic[]
}

export interface ExistingRunLike {
  plan_sha256: string
  local_materialized: boolean
}

export function selectActionableDiagnostic(diagnostics: Diagnostic[] | undefined): Diagnostic | undefined {
  if (!diagnostics?.length) return undefined
  return diagnostics.find((item) => item.severity === 'error')
    ?? diagnostics.find((item) => item.severity === 'warning')
    ?? diagnostics[0]
}

export function selectActiveStructureArtifact<T extends StructureArtifactLike>(
  artifacts: T[],
  activeArtifactId: string,
): T | undefined {
  const active = artifacts.find(
    (artifact) => artifact.artifact_type === 'structure' && artifact.artifact_id === activeArtifactId,
  )
  if (active) return active
  return [...artifacts]
    .filter((artifact) => artifact.artifact_type === 'structure')
    .sort((left, right) => right.created_at_utc.localeCompare(left.created_at_utc))[0]
}

export function canResumeExistingRun(
  plan: CalculationPlanLike | null | undefined,
  run: ExistingRunLike | null | undefined,
): boolean {
  if (!plan || !run?.local_materialized || run.plan_sha256 !== plan.plan_sha256) return false
  return !(plan.diagnostics ?? []).some(
    (diagnostic) => diagnostic.severity === 'error'
      && diagnostic.code !== 'MATERIALIZATION_DESTINATION_EXISTS',
  )
}

export function parseSlurmWalltimeMinutes(value: string | null | undefined): number | null {
  const match = /^(?:(\d+)-)?(\d{2}):(\d{2}):(\d{2})$/.exec(value?.trim() ?? '')
  if (!match) return null
  const days = Number(match[1] ?? 0)
  const hours = Number(match[2])
  const minutes = Number(match[3])
  const seconds = Number(match[4])
  if (minutes >= 60 || seconds >= 60) return null
  return days * 1440 + hours * 60 + minutes + (seconds ? 1 : 0)
}

export function formatSlurmWalltime(minutes: number | null | undefined): string {
  if (!Number.isFinite(minutes) || Number(minutes) <= 0) return ''
  const wholeMinutes = Math.ceil(Number(minutes))
  const days = Math.floor(wholeMinutes / 1440)
  const hours = Math.floor((wholeMinutes % 1440) / 60)
  const remainingMinutes = wholeMinutes % 60
  const time = `${String(hours).padStart(2, '0')}:${String(remainingMinutes).padStart(2, '0')}:00`
  return days ? `${days}-${time}` : time
}

export function uniqueSpeciesOrder(species: string[] | undefined): string[] {
  const seen = new Set<string>()
  const ordered: string[] = []
  for (const symbol of species ?? []) {
    const normalized = symbol.trim()
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    ordered.push(normalized)
  }
  return ordered
}

export function poscarSpeciesOrder(poscarText: string | null | undefined): string[] {
  if (!poscarText) return []
  const lines = poscarText.replace(/\r/g, '').split('\n')
  if (lines.length < 7) return []
  const labels = lines[5].trim().split(/\s+/).filter(Boolean)
  const counts = lines[6].trim().split(/\s+/).filter(Boolean)
  if (
    !labels.length
    || labels.length !== counts.length
    || !labels.every((label) => /^[A-Z][a-z]?$/.test(label))
    || !counts.every((count) => /^\d+$/.test(count))
  ) return []
  return uniqueSpeciesOrder(labels)
}

export function potcarDatasetOrder(metadata: PotcarMetadataLike | null | undefined): string[] {
  return (metadata?.datasets ?? [])
    .map((dataset) => String(dataset.element ?? '').trim())
    .filter(Boolean)
}

export function potcarMetadataMatchesSpecies(
  metadata: PotcarMetadataLike | null | undefined,
  expectedSpeciesOrder: string[],
): boolean {
  const actual = potcarDatasetOrder(metadata)
  return expectedSpeciesOrder.length > 0
    && actual.length === expectedSpeciesOrder.length
    && actual.every((element, index) => element === expectedSpeciesOrder[index])
}
