import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import type { NodeDefinition } from './types'

export type Language = 'zh-CN' | 'en'

const LANGUAGE_STORAGE_KEY = 'catex.language.v1'

interface I18nContextValue {
  language: Language
  setLanguage: (language: Language) => void
  tr: (zh: string, en: string) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

function initialLanguage(): Language {
  const saved = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
  if (saved === 'zh-CN' || saved === 'en') return saved
  return navigator.language.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(initialLanguage)

  useEffect(() => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
    document.documentElement.lang = language
  }, [language])

  const value = useMemo<I18nContextValue>(
    () => ({
      language,
      setLanguage,
      tr: (zh, en) => (language === 'zh-CN' ? zh : en),
    }),
    [language],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nContextValue {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n must be used inside I18nProvider')
  return value
}

const nodeTranslations: Record<string, { title: string; description: string }> = {
  'structure.upload': {
    title: 'Upload structure',
    description: 'Import a POSCAR or CIF while preserving the source artifact.',
  },
  'structure.inspect': {
    title: 'Inspect structure',
    description: 'Run read-only CatEx geometry inspection and diagnostics.',
  },
  'review.structure': {
    title: 'Review structure',
    description: 'Explicitly approve structure, sites, and provenance.',
  },
  'hpc.connect': {
    title: 'Connect Run Center',
    description: 'Open Run Center and verify SSH, remote allowlists, and the POTCAR library read-only.',
  },
  'vasp.validate': {
    title: 'Validate VASP inputs',
    description: 'Validate the protocol and input compatibility without creating POTCAR.',
  },
  'vasp.validate.auto': {
    title: 'Diagnose VASP inputs',
    description: 'Automatically diagnose structure and protocol compatibility before calculation.',
  },
  'slurm.plan': {
    title: 'Plan Slurm job',
    description: 'Generate and inspect a plan without calling the scheduler.',
  },
  'slurm.submit': {
    title: 'Stage and submit',
    description: 'Upload inputs, build POTCAR in the named remote project directory, and submit only after confirmation.',
  },
  'execution.mock': {
    title: 'Synthetic run',
    description: 'Demonstrate state transitions without connecting to HPC or running VASP.',
  },
  'vasp.parse': {
    title: 'Parse results',
    description: 'Parse bounded OUTCAR and OSZICAR evidence with CatEx.',
  },
  'review.result': {
    title: 'Review results',
    description: 'Separate process completion, scientific convergence, and human acceptance.',
  },
  'results.summarize': {
    title: 'Summarize results',
    description: 'Summarize energy, convergence, final structure, vibrations, and diagnostics.',
  },
}

const portTranslations: Record<string, string> = {
  structure_artifact: 'Structure artifact',
  structure_record: 'Structure record',
  reviewed_structure: 'Reviewed structure',
  hpc_ready_context: 'Connected compute context',
  validated_input: 'Validated inputs',
  calculation_plan: 'Calculation plan',
  run_evidence: 'Run evidence',
  parsed_result: 'Parsed result',
  reviewed_result: 'Reviewed result',
  result_summary: 'Result summary',
}

export function localizeNodeDefinition(
  definition: NodeDefinition,
  language: Language,
): NodeDefinition {
  if (language === 'zh-CN') return definition
  const translated = nodeTranslations[definition.type_id]
  return {
    ...definition,
    title: translated?.title ?? definition.title,
    description: translated?.description ?? definition.description,
    inputs: definition.inputs.map((port) => ({
      ...port,
      label: portTranslations[port.kind] ?? port.label,
    })),
    outputs: definition.outputs.map((port) => ({
      ...port,
      label: portTranslations[port.kind] ?? port.label,
    })),
  }
}

export const statusLabels: Record<Language, Record<string, string>> = {
  'zh-CN': {
    idle: '待处理',
    running: '处理中',
    success: '已完成',
    warning: '需留意',
    review: '待审核',
    blocked: '已阻断',
  },
  en: {
    idle: 'Pending',
    running: 'Running',
    success: 'Complete',
    warning: 'Attention',
    review: 'Review',
    blocked: 'Blocked',
  },
}

export const categoryLabels: Record<Language, Record<string, string>> = {
  'zh-CN': {
    source: '来源',
    structure: '结构',
    review: '审核',
    protocol: '协议',
    execution: '执行',
    parsing: '解析',
  },
  en: {
    source: 'source',
    structure: 'structure',
    review: 'review',
    protocol: 'protocol',
    execution: 'execution',
    parsing: 'parsing',
  },
}
