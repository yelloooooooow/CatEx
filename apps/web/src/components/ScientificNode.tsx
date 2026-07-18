import { Handle, Position, type NodeProps } from '@xyflow/react'
import {
  Braces,
  CheckCircle2,
  CircleDot,
  FileUp,
  FlaskConical,
  Microscope,
  Play,
  ScanSearch,
  ShieldCheck,
} from 'lucide-react'

import { handleId, type ScientificFlowNode } from '../workflow'
import {
  categoryLabels,
  localizeNodeDefinition,
  statusLabels,
  useI18n,
} from '../i18n'

const categoryIcons = {
  source: FileUp,
  structure: ScanSearch,
  review: ShieldCheck,
  protocol: Braces,
  execution: Play,
  parsing: Microscope,
}

export function ScientificNode({ data, selected }: NodeProps<ScientificFlowNode>) {
  const { language } = useI18n()
  const definition = localizeNodeDefinition(data.definition, language)
  const Icon = categoryIcons[definition.category] ?? FlaskConical
  return (
    <article
      className={`scientific-node category-${data.definition.category} status-${data.status} ${selected ? 'is-selected' : ''}`}
    >
      {definition.inputs.map((port, index) => (
        <Handle
          className="scientific-handle input-handle"
          id={handleId('in', port.kind, port.port_id)}
          key={port.port_id}
          position={Position.Left}
          style={{ top: `${44 + index * 24}px` }}
          title={`${port.label} · ${port.kind}`}
          type="target"
        />
      ))}

      <header className="node-header">
        <span className="node-icon"><Icon size={17} strokeWidth={1.8} /></span>
        <span className="node-category">{categoryLabels[language][definition.category]}</span>
        {definition.review_gate && <ShieldCheck className="gate-icon" size={14} />}
      </header>

      <div className="node-body">
        <h3>{definition.title}</h3>
        <p>{data.detail ?? definition.description}</p>
      </div>

      <footer className="node-footer">
        <span className={`runtime-dot status-${data.status}`} />
        <span>{statusLabels[language][data.status]}</span>
        {data.status === 'success' ? <CheckCircle2 size={13} /> : <CircleDot size={12} />}
      </footer>

      {definition.outputs.map((port, index) => (
        <Handle
          className="scientific-handle output-handle"
          id={handleId('out', port.kind, port.port_id)}
          key={port.port_id}
          position={Position.Right}
          style={{ top: `${44 + index * 24}px` }}
          title={`${port.label} · ${port.kind}`}
          type="source"
        />
      ))}
    </article>
  )
}
