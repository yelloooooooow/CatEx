import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { I18nProvider, localizeNodeDefinition, useI18n } from './i18n'
import type { NodeDefinition } from './types'

function Harness() {
  const { language, setLanguage, tr } = useI18n()
  return (
    <div>
      <output>{language}</output>
      <span>{tr('中文', 'English')}</span>
      <button onClick={() => setLanguage('zh-CN')} type="button">zh</button>
      <button onClick={() => setLanguage('en')} type="button">en</button>
    </div>
  )
}

describe('CatEx language support', () => {
  beforeEach(() => window.localStorage.clear())

  it('switches language and persists the choice locally', () => {
    window.localStorage.setItem('catex.language.v1', 'en')
    render(<I18nProvider><Harness /></I18nProvider>)

    expect(screen.getByText('English')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'zh' }))
    expect(screen.getByText('中文')).toBeInTheDocument()
    expect(window.localStorage.getItem('catex.language.v1')).toBe('zh-CN')
  })

  it('localizes workflow definitions without changing scientific identifiers', () => {
    const definition: NodeDefinition = {
      type_id: 'vasp.validate',
      title: 'VASP 输入验证',
      description: '验证输入',
      category: 'protocol',
      review_gate: false,
      inputs: [{ port_id: 'structure', label: '已审核结构', kind: 'reviewed_structure', required: true, multiple: false }],
      outputs: [{ port_id: 'validated', label: '已验证输入', kind: 'validated_input', required: true, multiple: false }],
      parameters: [],
    }

    const localized = localizeNodeDefinition(definition, 'en')
    expect(localized.title).toBe('Validate VASP inputs')
    expect(localized.type_id).toBe(definition.type_id)
    expect(localized.inputs[0].kind).toBe('reviewed_structure')
    expect(localized.inputs[0].label).toBe('Reviewed structure')
  })

  it('localizes experiment-informed workflow nodes and typed ports', () => {
    const definition: NodeDefinition = {
      type_id: 'experiment.model.infer',
      title: '推断候选模型',
      description: '根据实验约束推断有限候选集合',
      category: 'experiment',
      review_gate: false,
      inputs: [
        {
          port_id: 'evidence',
          label: '实验约束集',
          kind: 'experiment_evidence_set',
          required: true,
          multiple: false,
        },
      ],
      outputs: [
        {
          port_id: 'candidates',
          label: '候选模型集',
          kind: 'candidate_model_set',
          required: true,
          multiple: false,
        },
      ],
      parameters: [],
    }

    const localized = localizeNodeDefinition(definition, 'en')
    expect(localized.title).toBe('Infer candidate models')
    expect(localized.inputs[0].label).toBe('Experimental evidence set')
    expect(localized.outputs[0].label).toBe('Candidate model set')
    expect(localized.inputs[0].kind).toBe('experiment_evidence_set')
  })
})
