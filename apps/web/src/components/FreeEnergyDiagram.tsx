import type { ReactionAnalysis } from '../types'

interface FreeEnergyDiagramProps {
  analysis: ReactionAnalysis | null
  emptyLabel: string
}

export function FreeEnergyDiagram({ analysis, emptyLabel }: FreeEnergyDiagramProps) {
  if (!analysis || analysis.states.length < 2) {
    return <div className="diagram-empty">{emptyLabel}</div>
  }

  const width = 760
  const height = 360
  const padding = { top: 32, right: 34, bottom: 70, left: 58 }
  const values = analysis.states.map((state) => state.free_energy_eV)
  const rawMin = Math.min(...values, 0)
  const rawMax = Math.max(...values, 0)
  const span = Math.max(0.5, rawMax - rawMin)
  const minimum = rawMin - span * 0.16
  const maximum = rawMax + span * 0.16
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom
  const x = (index: number) =>
    padding.left + (analysis.states.length === 1 ? plotWidth / 2 : (plotWidth * index) / (analysis.states.length - 1))
  const y = (value: number) => padding.top + ((maximum - value) / (maximum - minimum)) * plotHeight
  const ticks = Array.from({ length: 5 }, (_, index) => minimum + ((maximum - minimum) * index) / 4)

  return (
    <div className="free-energy-diagram">
      <svg aria-label="Reaction free-energy diagram" role="img" viewBox={`0 0 ${width} ${height}`}>
        {ticks.map((tick) => (
          <g key={tick}>
            <line className="diagram-gridline" x1={padding.left} x2={width - padding.right} y1={y(tick)} y2={y(tick)} />
            <text className="diagram-tick" x={padding.left - 10} y={y(tick) + 4}>{tick.toFixed(2)}</text>
          </g>
        ))}
        <text className="diagram-axis-label" transform={`translate(17 ${height / 2}) rotate(-90)`}>ΔG (eV)</text>
        {analysis.states.slice(0, -1).map((state, index) => (
          <line
            className={analysis.potential_limiting_step === index + 1 ? 'diagram-link limiting' : 'diagram-link'}
            key={`${state.key}-link`}
            x1={x(index) + 25}
            x2={x(index + 1) - 25}
            y1={y(state.free_energy_eV)}
            y2={y(analysis.states[index + 1].free_energy_eV)}
          />
        ))}
        {analysis.states.map((state, index) => (
          <g key={state.key}>
            <line className="diagram-plateau" x1={x(index) - 25} x2={x(index) + 25} y1={y(state.free_energy_eV)} y2={y(state.free_energy_eV)} />
            <circle className="diagram-point" cx={x(index)} cy={y(state.free_energy_eV)} r="5" />
            <text className="diagram-value" x={x(index)} y={y(state.free_energy_eV) - 13}>{state.free_energy_eV.toFixed(2)}</text>
            <text className="diagram-state" x={x(index)} y={height - 35}>{state.label}</text>
          </g>
        ))}
      </svg>
    </div>
  )
}
