import { MarkerType, type Edge, type Node } from '@xyflow/react'

import type {
  NodeDefinition,
  RuntimeStatus,
  WorkflowTemplate,
  WorkflowTemplateEdge,
  WorkflowTemplateNode,
} from './types'

export type ScientificNodeData = Record<string, unknown> & {
  definition: NodeDefinition
  parameters: Record<string, string | number | boolean>
  status: RuntimeStatus
  detail?: string
}

export type ScientificFlowNode = Node<ScientificNodeData, 'scientific'>
export type ScientificFlowEdge = Edge

export interface WorkflowValidationRequest {
  nodes: Array<{
    node_id: string
    type_id: string
    position: { x: number; y: number }
    parameters: Record<string, string | number | boolean>
  }>
  edges: Array<{
    edge_id: string
    source_node_id: string
    source_port_id: string
    target_node_id: string
    target_port_id: string
  }>
}

const HANDLE_SEPARATOR = '::'

export function handleId(direction: 'in' | 'out', kind: string, portId: string): string {
  return [direction, kind, portId].join(HANDLE_SEPARATOR)
}

export function parseHandleId(value: string | null | undefined) {
  if (!value) return null
  const [direction, kind, portId, ...rest] = value.split(HANDLE_SEPARATOR)
  if ((direction !== 'in' && direction !== 'out') || !kind || !portId || rest.length > 0) {
    return null
  }
  return { direction, kind, portId }
}

export function compatibleHandles(source: string | null, target: string | null): boolean {
  const sourceHandle = parseHandleId(source)
  const targetHandle = parseHandleId(target)
  return Boolean(
    sourceHandle &&
      targetHandle &&
      sourceHandle.direction === 'out' &&
      targetHandle.direction === 'in' &&
      sourceHandle.kind === targetHandle.kind,
  )
}

export function wouldCreateWorkflowCycle(
  edges: ScientificFlowEdge[],
  source: string | null | undefined,
  target: string | null | undefined,
  ignoredEdgeId?: string,
): boolean {
  if (!source || !target) return true
  if (source === target) return true
  const outgoing = new Map<string, string[]>()
  for (const edge of edges) {
    if (edge.id === ignoredEdgeId) continue
    outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target])
  }
  const pending = [target]
  const visited = new Set<string>()
  while (pending.length > 0) {
    const nodeId = pending.pop()!
    if (nodeId === source) return true
    if (visited.has(nodeId)) continue
    visited.add(nodeId)
    pending.push(...(outgoing.get(nodeId) ?? []))
  }
  return false
}

function definitionFor(
  node: WorkflowTemplateNode,
  registry: Map<string, NodeDefinition>,
): NodeDefinition {
  const definition = registry.get(node.type_id)
    if (!definition) throw new Error(`Unregistered node type: ${node.type_id}`)
  return definition
}

export function templateNodeToFlow(
  node: WorkflowTemplateNode,
  registry: Map<string, NodeDefinition>,
): ScientificFlowNode {
  const definition = definitionFor(node, registry)
  return {
    id: node.node_id,
    type: 'scientific',
    position: node.position,
    data: {
      definition,
      parameters: {
        ...Object.fromEntries(
          definition.parameters.map((parameter) => [parameter.key, parameter.default]),
        ),
        ...node.parameters,
      },
      status: 'idle',
    },
  }
}

export function templateEdgeToFlow(
  edge: WorkflowTemplateEdge,
  template: WorkflowTemplate,
  registry: Map<string, NodeDefinition>,
): ScientificFlowEdge {
  const sourceNode = template.nodes.find((item) => item.node_id === edge.source_node_id)
  const targetNode = template.nodes.find((item) => item.node_id === edge.target_node_id)
    if (!sourceNode || !targetNode) throw new Error(`Edge ${edge.edge_id} references a missing node`)
  const source = definitionFor(sourceNode, registry).outputs.find(
    (port) => port.port_id === edge.source_port_id,
  )
  const target = definitionFor(targetNode, registry).inputs.find(
    (port) => port.port_id === edge.target_port_id,
  )
    if (!source || !target) throw new Error(`Edge ${edge.edge_id} references a missing port`)
  return {
    id: edge.edge_id,
    source: edge.source_node_id,
    sourceHandle: handleId('out', source.kind, source.port_id),
    target: edge.target_node_id,
    targetHandle: handleId('in', target.kind, target.port_id),
    type: 'smoothstep',
    animated: false,
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6e8f86' },
    style: { stroke: '#5d756f', strokeWidth: 1.6 },
  }
}

export function buildValidationRequest(
  nodes: ScientificFlowNode[],
  edges: ScientificFlowEdge[],
): WorkflowValidationRequest {
  return {
    nodes: nodes.map((node) => ({
      node_id: node.id,
      type_id: node.data.definition.type_id,
      position: node.position,
      parameters: node.data.parameters,
    })),
    edges: edges.map((edge) => {
      const source = parseHandleId(edge.sourceHandle)
      const target = parseHandleId(edge.targetHandle)
      return {
        edge_id: edge.id,
        source_node_id: edge.source,
        source_port_id: source?.portId ?? '',
        target_node_id: edge.target,
        target_port_id: target?.portId ?? '',
      }
    }),
  }
}

export function rehydrateNodes(
  nodes: ScientificFlowNode[],
  registry: Map<string, NodeDefinition>,
): ScientificFlowNode[] {
  return nodes.map((node) => {
    const definition = registry.get(node.data.definition.type_id)
    if (!definition) throw new Error(`Unregistered node type: ${node.data.definition.type_id}`)
    return {
      ...node,
      data: {
        ...node.data,
        definition,
        parameters: {
          ...Object.fromEntries(
            definition.parameters.map((parameter) => [parameter.key, parameter.default]),
          ),
          ...node.data.parameters,
        },
      },
    }
  })
}

export function createFlowNode(
  definition: NodeDefinition,
  position: { x: number; y: number },
  id: string,
): ScientificFlowNode {
  return {
    id,
    type: 'scientific',
    position,
    data: {
      definition,
      parameters: Object.fromEntries(
        definition.parameters.map((parameter) => [parameter.key, parameter.default]),
      ),
      status: 'idle',
    },
  }
}

export interface CompatiblePortPair {
  sourceHandle: string
  targetHandle: string
}

export function firstCompatiblePortPair(
  sourceDefinition: NodeDefinition,
  targetDefinition: NodeDefinition,
): CompatiblePortPair | null {
  for (const source of sourceDefinition.outputs) {
    const target = targetDefinition.inputs.find((candidate) => candidate.kind === source.kind)
    if (target) {
      return {
        sourceHandle: handleId('out', source.kind, source.port_id),
        targetHandle: handleId('in', target.kind, target.port_id),
      }
    }
  }
  return null
}

export function layoutWorkflow(
  nodes: ScientificFlowNode[],
  edges: ScientificFlowEdge[],
): ScientificFlowNode[] {
  if (nodes.length === 0) return []

  const nodeIds = new Set(nodes.map((node) => node.id))
  const incoming = new Map(nodes.map((node) => [node.id, 0]))
  const outgoing = new Map(nodes.map((node) => [node.id, [] as string[]]))

  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1)
    outgoing.get(edge.source)?.push(edge.target)
  }

  const layerById = new Map<string, number>()
  const queue = nodes
    .filter((node) => (incoming.get(node.id) ?? 0) === 0)
    .map((node) => node.id)

  for (const nodeId of queue) layerById.set(nodeId, 0)

  let cursor = 0
  while (cursor < queue.length) {
    const nodeId = queue[cursor]
    cursor += 1
    const nextLayer = (layerById.get(nodeId) ?? 0) + 1
    for (const targetId of outgoing.get(nodeId) ?? []) {
      layerById.set(targetId, Math.max(layerById.get(targetId) ?? 0, nextLayer))
      const remaining = (incoming.get(targetId) ?? 0) - 1
      incoming.set(targetId, remaining)
      if (remaining === 0) queue.push(targetId)
    }
  }

  // Validation rejects cycles, but keeping the layout total makes imported or
  // half-edited drafts recoverable instead of hiding their unplaced nodes.
  let fallbackLayer = Math.max(0, ...layerById.values())
  for (const node of nodes) {
    if (!layerById.has(node.id)) {
      fallbackLayer += 1
      layerById.set(node.id, fallbackLayer)
    }
  }

  const layers = new Map<number, ScientificFlowNode[]>()
  for (const node of nodes) {
    const layer = layerById.get(node.id) ?? 0
    layers.set(layer, [...(layers.get(layer) ?? []), node])
  }

  const horizontalGap = 330
  const verticalGap = 180
  const top = 90
  const left = 90
  const widestLayer = Math.max(...[...layers.values()].map((layer) => layer.length))

  return nodes.map((node) => {
    const layerIndex = layerById.get(node.id) ?? 0
    const layer = layers.get(layerIndex) ?? [node]
    const index = layer.findIndex((candidate) => candidate.id === node.id)
    const layerOffset = ((widestLayer - layer.length) * verticalGap) / 2
    return {
      ...node,
      position: {
        x: left + layerIndex * horizontalGap,
        y: top + layerOffset + index * verticalGap,
      },
    }
  })
}

export function localProjectDirectory(
  persistenceRoot: string | null | undefined,
  projectId: string | null | undefined,
): string {
  if (!persistenceRoot || !projectId) return ''
  const separator = persistenceRoot.includes('\\') ? '\\' : '/'
  const root = persistenceRoot.replace(/[\\/]+$/, '')
  return `${root}${separator}projects${separator}${projectId}`
}
