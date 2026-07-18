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
  return {
    id: node.node_id,
    type: 'scientific',
    position: node.position,
    data: {
      definition: definitionFor(node, registry),
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
    return { ...node, data: { ...node.data, definition } }
  })
}
