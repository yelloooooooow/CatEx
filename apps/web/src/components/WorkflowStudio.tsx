import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  reconnectEdge,
  type Connection,
  type Edge,
  type OnEdgesChange,
  type OnNodesChange,
  type ReactFlowInstance,
} from '@xyflow/react'
import {
  AlignHorizontalSpaceAround,
  BookOpen,
  Boxes,
  ChevronDown,
  Copy,
  FileCheck2,
  FolderOpen,
  GitBranch,
  Link2,
  LoaderCircle,
  MoreHorizontal,
  PanelRightOpen,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  ServerOff,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-react'
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type MouseEvent as ReactMouseEvent,
  type SetStateAction,
} from 'react'

import { localizeNodeDefinition, useI18n, type Language } from '../i18n'
import type {
  NodeDefinition,
  WorkflowRevision,
  WorkflowRunGraph,
  WorkflowTemplateCatalogItem,
} from '../types'
import {
  compatibleHandles,
  createFlowNode,
  firstCompatiblePortPair,
  layoutWorkflow,
  wouldCreateWorkflowCycle,
  type ScientificFlowEdge,
  type ScientificFlowNode,
} from '../workflow'
import {
  groupedNodeDefinitions,
  guidanceCopy,
  nodeGuidance,
} from '../workflowGuidance'
import { ScientificNode } from './ScientificNode'

const nodeTypes = { scientific: ScientificNode }

const ENGLISH_TEMPLATE_COPY: Record<string, { title: string; description: string }> = {
  'vasp-relax': {
    title: 'Structure relaxation',
    description: 'Prepare inputs, run a VASP relaxation, and collect the results.',
  },
  'vasp-relax-static': {
    title: 'Relaxation + static',
    description: 'Run a high-accuracy static calculation after structure relaxation.',
  },
  'vasp-relax-frequency': {
    title: 'Relaxation + static + frequency',
    description: 'Build the data chain for adsorption energies and vibrational corrections.',
  },
  'vasp-relax-static-dos': {
    title: 'Relaxation + static + DOS',
    description: 'Branch into a density-of-states calculation after the static stage.',
  },
  'chgnet-vasp-relax-static': {
    title: 'CHGNet pre-relaxation + VASP',
    description: 'Optionally pre-relax with an ML potential before VASP validation.',
  },
  'vasp-md': {
    title: 'Ab initio molecular dynamics',
    description: 'Prepare inputs, run VASP MD, and collect trajectory metadata and results.',
  },
}

export function localizeWorkflowTemplate(
  template: WorkflowTemplateCatalogItem,
  language: Language,
) {
  return language === 'en'
    ? (ENGLISH_TEMPLATE_COPY[template.template_id] ?? {
        title: template.title,
        description: template.description,
      })
    : { title: template.title, description: template.description }
}

interface WorkflowWorkbenchProps {
  connectionState: 'loading' | 'online' | 'offline'
  nodes: ScientificFlowNode[]
  edges: ScientificFlowEdge[]
  registry: Map<string, NodeDefinition>
  templates: WorkflowTemplateCatalogItem[]
  selectedNodeId: string | null
  revisions: WorkflowRevision[]
  runGraphs: WorkflowRunGraph[]
  projectReady: boolean
  projectTitle: string | null
  projectStoragePath: string
  workflowInitialized: boolean
  onNodesChange: OnNodesChange<ScientificFlowNode>
  onEdgesChange: OnEdgesChange<ScientificFlowEdge>
  setNodes: Dispatch<SetStateAction<ScientificFlowNode[]>>
  setEdges: Dispatch<SetStateAction<ScientificFlowEdge[]>>
  onConnect: (connection: Connection) => void
  onSelectNode: (nodeId: string | null) => void
  onOpenNode: (node: ScientificFlowNode) => void
  onApplyTemplate: (template: WorkflowTemplateCatalogItem) => void
  onInitializeBlank: () => void
  onOpenProjects: () => void
  onValidate: () => void
  onSave: () => void
  onPublish: () => void
  onCreateRunGraph: () => void
  onClear: () => void
  onRetry: () => void
}

interface ContextMenuState {
  kind: 'pane' | 'node' | 'edge'
  x: number
  y: number
  flowPosition: { x: number; y: number }
  targetId?: string
}

type InspectorTab = 'guide' | 'parameters' | 'ports'
type StudioView = 'editor' | 'lifecycle'

function parameterValue(
  node: ScientificFlowNode,
  key: string,
  fallback: string | number | boolean,
) {
  return node.data.parameters[key] ?? fallback
}

function workflowEdge(connection: Connection): ScientificFlowEdge {
  return {
    ...connection,
    id: `edge-${crypto.randomUUID()}`,
    type: 'smoothstep',
    animated: false,
    markerEnd: { type: MarkerType.ArrowClosed, color: '#77a99a' },
    style: { stroke: '#64857b', strokeWidth: 1.8 },
  }
}

export function WorkflowWorkbench({
  connectionState,
  nodes,
  edges,
  registry,
  templates,
  selectedNodeId,
  revisions,
  runGraphs,
  projectReady,
  projectTitle,
  projectStoragePath,
  workflowInitialized,
  onNodesChange,
  onEdgesChange,
  setNodes,
  setEdges,
  onConnect,
  onSelectNode,
  onOpenNode,
  onApplyTemplate,
  onInitializeBlank,
  onOpenProjects,
  onValidate,
  onSave,
  onPublish,
  onCreateRunGraph,
  onClear,
  onRetry,
}: WorkflowWorkbenchProps) {
  const { language, tr } = useI18n()
  const [view, setView] = useState<StudioView>('editor')
  const [showTemplates, setShowTemplates] = useState(false)
  const [paletteSearch, setPaletteSearch] = useState('')
  const [contextSearch, setContextSearch] = useState('')
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('guide')
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const [flowInstance, setFlowInstance] =
    useState<ReactFlowInstance<ScientificFlowNode, ScientificFlowEdge> | null>(null)
  const [pathCopied, setPathCopied] = useState(false)
  const canvasRef = useRef<HTMLDivElement>(null)
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null
  const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId) ?? null
  const nodeGroups = useMemo(() => groupedNodeDefinitions(registry), [registry])
  const paletteDefinitions = useMemo(
    () => nodeGroups.flatMap((group) => group.definitions),
    [nodeGroups],
  )
  const normalizedPaletteSearch = paletteSearch.trim().toLowerCase()
  const normalizedContextSearch = contextSearch.trim().toLowerCase()

  const definitionMatches = (definition: NodeDefinition, query: string) => {
    if (!query) return true
    const localized = localizeNodeDefinition(definition, language)
    return [
      definition.type_id,
      localized.title,
      localized.description,
      definition.category,
    ].some((value) => value.toLowerCase().includes(query))
  }

  const closeContextMenu = () => {
    setContextMenu(null)
    setContextSearch('')
  }

  useEffect(() => {
    if (!contextMenu) return
    const close = () => closeContextMenu()
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeContextMenu()
    }
    window.addEventListener('pointerdown', close)
    window.addEventListener('keydown', escape)
    return () => {
      window.removeEventListener('pointerdown', close)
      window.removeEventListener('keydown', escape)
    }
  }, [contextMenu])

  const addNode = (
    definition: NodeDefinition,
    options: {
      position?: { x: number; y: number }
      connectFrom?: ScientificFlowNode | null
      arrange?: boolean
    } = {},
  ) => {
    const id = `${definition.type_id.replaceAll('.', '-')}-${crypto.randomUUID().slice(0, 8)}`
    const anchor = options.connectFrom ?? null
    const position = options.position ?? (
      anchor
        ? { x: anchor.position.x + 330, y: anchor.position.y }
        : { x: 90 + (nodes.length % 3) * 330, y: 90 + Math.floor(nodes.length / 3) * 180 }
    )
    const nextNode = createFlowNode(definition, position, id)
    let nextNodes = [...nodes, nextNode]
    let nextEdges = edges

    if (anchor) {
      const ports = firstCompatiblePortPair(anchor.data.definition, definition)
      if (ports) {
        nextEdges = [
          ...edges,
          workflowEdge({
            source: anchor.id,
            sourceHandle: ports.sourceHandle,
            target: id,
            targetHandle: ports.targetHandle,
          }),
        ]
      }
    }

    if (options.arrange && nextEdges !== edges) {
      nextNodes = layoutWorkflow(nextNodes, nextEdges)
    }
    setNodes(nextNodes)
    setEdges(nextEdges)
    onSelectNode(id)
    setSelectedEdgeId(null)
    setInspectorTab('guide')
    closeContextMenu()
  }

  const deleteNode = (nodeId: string) => {
    setNodes((current) => current.filter((node) => node.id !== nodeId))
    setEdges((current) =>
      current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
    )
    if (selectedNodeId === nodeId) onSelectNode(null)
    closeContextMenu()
  }

  const deleteEdge = (edgeId: string) => {
    setEdges((current) => current.filter((edge) => edge.id !== edgeId))
    if (selectedEdgeId === edgeId) setSelectedEdgeId(null)
    closeContextMenu()
  }

  const duplicateNode = (node: ScientificFlowNode) => {
    const id = `${node.data.definition.type_id.replaceAll('.', '-')}-${crypto.randomUUID().slice(0, 8)}`
    setNodes((current) => [
      ...current,
      {
        ...node,
        id,
        position: { x: node.position.x + 42, y: node.position.y + 42 },
        data: {
          ...node.data,
          parameters: { ...node.data.parameters },
          status: 'idle',
          detail: undefined,
        },
        selected: false,
      },
    ])
    onSelectNode(id)
    closeContextMenu()
  }

  const deleteSelection = () => {
    if (selectedEdge) {
      deleteEdge(selectedEdge.id)
      return
    }
    if (selectedNode) deleteNode(selectedNode.id)
  }

  const updateParameter = (key: string, value: string | number | boolean) => {
    if (!selectedNodeId) return
    setNodes((current) =>
      current.map((node) =>
        node.id === selectedNodeId
          ? {
              ...node,
              data: {
                ...node.data,
                parameters: { ...node.data.parameters, [key]: value },
                status: 'idle',
                detail: undefined,
              },
            }
          : node,
      ),
    )
  }

  const arrangeGraph = () => {
    setNodes((current) => layoutWorkflow(current, edges))
    window.setTimeout(() => {
      void flowInstance?.fitView({ duration: 260, padding: 0.16 })
    }, 0)
  }

  const connectionIsValid = (connection: Connection | Edge) => {
    const ignoredEdgeId = 'id' in connection ? connection.id : undefined
    return (
      compatibleHandles(
        connection.sourceHandle ?? null,
        connection.targetHandle ?? null,
      ) &&
      !wouldCreateWorkflowCycle(
        edges,
        connection.source,
        connection.target,
        ignoredEdgeId,
      )
    )
  }

  const contextPosition = (event: MouseEvent | ReactMouseEvent) => {
    const bounds = canvasRef.current?.getBoundingClientRect()
    const x = Math.min(event.clientX - (bounds?.left ?? 0), Math.max(12, (bounds?.width ?? 400) - 330))
    const y = Math.min(event.clientY - (bounds?.top ?? 0), Math.max(12, (bounds?.height ?? 400) - 430))
    return {
      x: Math.max(12, x),
      y: Math.max(12, y),
      flowPosition: flowInstance?.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      }) ?? { x: 80, y: 80 },
    }
  }

  const openPaneContextMenu = (event: MouseEvent | ReactMouseEvent) => {
    event.preventDefault()
    setSelectedEdgeId(null)
    setContextMenu({ kind: 'pane', ...contextPosition(event) })
  }

  const openNodeContextMenu = (event: MouseEvent | ReactMouseEvent, node: ScientificFlowNode) => {
    event.preventDefault()
    event.stopPropagation()
    onSelectNode(node.id)
    setSelectedEdgeId(null)
    setContextMenu({ kind: 'node', targetId: node.id, ...contextPosition(event) })
  }

  const openEdgeContextMenu = (event: MouseEvent | ReactMouseEvent, edge: ScientificFlowEdge) => {
    event.preventDefault()
    event.stopPropagation()
    onSelectNode(null)
    setSelectedEdgeId(edge.id)
    setContextMenu({ kind: 'edge', targetId: edge.id, ...contextPosition(event) })
  }

  const applyTemplate = (template: WorkflowTemplateCatalogItem) => {
    if (
      nodes.length > 0 &&
      !window.confirm(
        tr(
          '使用模板会替换当前未保存的画布，是否继续？',
          'Using a template replaces the current unsaved canvas. Continue?',
        ),
      )
    ) return
    onApplyTemplate(template)
    setShowTemplates(false)
    setView('editor')
    setSelectedEdgeId(null)
  }

  const copyProjectPath = async () => {
    if (!projectStoragePath) return
    await navigator.clipboard.writeText(projectStoragePath)
    setPathCopied(true)
    window.setTimeout(() => setPathCopied(false), 1800)
  }

  const selectedGuide = selectedNode
    ? guidanceCopy(nodeGuidance(selectedNode.data.definition.type_id), language)
    : null

  const renderNodePicker = (
    search: string,
    handleAdd: (definition: NodeDefinition) => void,
  ) => (
    <div className="workflow-node-groups">
      {nodeGroups.map((group) => {
        const visible = group.definitions.filter((definition) =>
          definitionMatches(definition, search),
        )
        if (visible.length === 0) return null
        return (
          <details key={group.id} open>
            <summary>
              <ChevronDown size={13} />
              <span>{language === 'zh-CN' ? group.labelZh : group.labelEn}</span>
              <small>{visible.length}</small>
            </summary>
            <div>
              {visible.map((definition) => {
                const localized = localizeNodeDefinition(definition, language)
                return (
                  <button
                    key={definition.type_id}
                    onClick={() => handleAdd(definition)}
                    title={localized.description}
                    type="button"
                  >
                    <Plus size={14} />
                    <span>
                      <strong>{localized.title}</strong>
                      <small>{localized.description}</small>
                    </span>
                  </button>
                )
              })}
            </div>
          </details>
        )
      })}
    </div>
  )

  return (
    <section className="workflow-workbench workflow-studio-v2">
      <header className="workflow-workbench-header">
        <div className="workflow-title-copy">
          <span className="eyebrow">CATEX FLOW</span>
          <h2>{projectTitle ?? tr('尚未打开项目', 'No project open')}</h2>
          <p>
            {projectReady
              ? tr(
                  '模板只是起点；画布、节点参数和连线共同构成当前项目的可编辑草稿。',
                  'Templates are only starting points; the canvas, node parameters, and connections form the editable project draft.',
                )
              : tr(
                  '先创建或打开项目，再建立可追踪的计算工作流。',
                  'Create or open a project before building a traceable calculation workflow.',
                )}
          </p>
          {projectStoragePath && (
            <button className="workflow-storage-path" onClick={() => void copyProjectPath()} type="button">
              <FolderOpen size={13} />
              <span>{projectStoragePath}</span>
              <Copy size={12} />
              {pathCopied && <em>{tr('已复制', 'Copied')}</em>}
            </button>
          )}
        </div>
        <div className="workflow-header-actions">
          <div className="workflow-mode-switch" role="tablist">
            <button
              className={view === 'editor' ? 'active' : ''}
              onClick={() => setView('editor')}
              type="button"
            >
              <GitBranch size={15} /> {tr('编辑工作流', 'Edit workflow')}
            </button>
            <button
              className={view === 'lifecycle' ? 'active' : ''}
              onClick={() => setView('lifecycle')}
              type="button"
            >
              <Play size={15} /> {tr('版本与运行', 'Versions & runs')}
            </button>
          </div>
        </div>
      </header>

      {view === 'editor' && !projectReady && (
        <div className="workflow-project-required">
          <FolderOpen size={34} />
          <h3>{tr('工作流属于项目', 'A workflow belongs to a project')}</h3>
          <p>
            {tr(
              '项目会把工作流草稿、输入、计算记录和结果保存在同一个本地目录中。',
              'A project keeps workflow drafts, inputs, calculation records, and results in one local directory.',
            )}
          </p>
          <button className="primary-button" onClick={onOpenProjects} type="button">
            {tr('创建或打开项目', 'Create or open a project')}
          </button>
        </div>
      )}

      {view === 'editor' && projectReady && !workflowInitialized && (
        <div className="workflow-start">
          <div className="workflow-start-copy">
            <span className="eyebrow">START</span>
            <h3>{tr('这个项目还没有工作流', 'This project has no workflow yet')}</h3>
            <p>
              {tr(
                '可以从空白画布右键添加节点，也可以选择一个模板后继续自由修改。',
                'Start from a blank canvas and right-click to add nodes, or choose a template and edit it freely.',
              )}
            </p>
            <button className="primary-button" onClick={onInitializeBlank} type="button">
              <Plus size={16} /> {tr('新建空白工作流', 'New blank workflow')}
            </button>
          </div>
          <div className="workflow-start-templates">
            <div className="panel-title">
              <span>{tr('或者使用模板', 'Or use a template')}</span>
              <small>{templates.length}</small>
            </div>
            <div>
              {templates.map((template) => {
                const copy = localizeWorkflowTemplate(template, language)
                return (
                  <button key={template.template_id} onClick={() => applyTemplate(template)} type="button">
                    <Boxes size={18} />
                    <span>
                      <strong>{copy.title}</strong>
                      <small>{copy.description}</small>
                    </span>
                    <span>{template.nodes.length}</span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {view === 'editor' && projectReady && workflowInitialized && (
        <div className="workflow-editor">
          <aside className="node-palette">
            <div className="panel-title">
              <span>
                {selectedNode
                  ? tr('添加后续节点', 'Add next node')
                  : tr('节点库', 'Node library')}
              </span>
              <small>{paletteDefinitions.length}</small>
            </div>
            <label className="workflow-search">
              <Search size={14} />
              <input
                onChange={(event) => setPaletteSearch(event.target.value)}
                placeholder={tr('搜索节点', 'Search nodes')}
                value={paletteSearch}
              />
              {paletteSearch && (
                <button onClick={() => setPaletteSearch('')} type="button"><X size={12} /></button>
              )}
            </label>
            <p className="palette-hint">
              {selectedNode
                ? tr(
                    '点击节点会把它接到当前选中节点后，并自动整理顺序。',
                    'Clicking a node appends it after the selection and automatically arranges the graph.',
                  )
                : tr(
                    '拖动端口可自由连线；在画布空白处右键可按位置新建。',
                    'Drag ports to connect freely; right-click empty canvas space to add at a position.',
                  )}
            </p>
            <div className="node-palette-list">
              {renderNodePicker(normalizedPaletteSearch, (definition) =>
                addNode(definition, {
                  connectFrom: selectedNode,
                  arrange: Boolean(selectedNode),
                }))}
            </div>
          </aside>

          <div className="workflow-graph-panel">
            <div className="workflow-graph-toolbar">
              <button onClick={() => setShowTemplates(true)} type="button">
                <Boxes size={14} /> {tr('模板', 'Templates')}
              </button>
              <button onClick={arrangeGraph} type="button">
                <AlignHorizontalSpaceAround size={14} /> {tr('自动布局', 'Auto layout')}
              </button>
              <span className="workflow-toolbar-separator" />
              <button onClick={onValidate} type="button">
                <ShieldCheck size={14} /> {tr('校验', 'Validate')}
              </button>
              <button disabled={nodes.length === 0} onClick={onSave} type="button">
                <Save size={14} /> {tr('保存草稿', 'Save draft')}
              </button>
              <button disabled={!selectedNode} onClick={() => selectedNode && duplicateNode(selectedNode)} type="button">
                <Copy size={14} /> {tr('复制', 'Duplicate')}
              </button>
              <button
                className="danger"
                disabled={!selectedNode && !selectedEdge}
                onClick={deleteSelection}
                type="button"
              >
                <Trash2 size={14} />
                {selectedEdge ? tr('删除连线', 'Delete edge') : tr('删除节点', 'Delete node')}
              </button>
              <button className="danger subtle" onClick={onClear} type="button">
                <RefreshCw size={14} /> {tr('清空画布', 'Clear canvas')}
              </button>
              <span className="workflow-toolbar-help">
                <MoreHorizontal size={14} />
                {tr('右键新建 · 拖动连线 · Delete 删除', 'Right-click to add · drag to connect · Delete to remove')}
              </span>
            </div>
            <div className="workflow-canvas" ref={canvasRef}>
              {connectionState !== 'online' ? (
                <div className="connection-empty">
                  {connectionState === 'loading' ? (
                    <LoaderCircle className="spin" size={28} />
                  ) : (
                    <ServerOff size={32} />
                  )}
                  <strong>
                    {connectionState === 'loading'
                      ? tr('正在连接本地 API', 'Connecting to local API')
                      : tr('本地 API 未启动', 'Local API is offline')}
                  </strong>
                  {connectionState === 'offline' && (
                    <button onClick={onRetry} type="button">
                      <RefreshCw size={14} /> {tr('重试', 'Retry')}
                    </button>
                  )}
                </div>
              ) : (
                <>
                  <ReactFlow
                    colorMode="dark"
                    defaultEdgeOptions={{
                      type: 'smoothstep',
                      markerEnd: { type: MarkerType.ArrowClosed, color: '#77a99a' },
                      style: { stroke: '#64857b', strokeWidth: 1.8 },
                    }}
                    deleteKeyCode={['Backspace', 'Delete']}
                    edges={edges}
                    edgesReconnectable
                    fitView
                    fitViewOptions={{ padding: 0.18 }}
                    isValidConnection={connectionIsValid}
                    maxZoom={1.6}
                    minZoom={0.2}
                    nodeTypes={nodeTypes}
                    nodes={nodes}
                    onConnect={onConnect}
                    onEdgeClick={(_, edge) => {
                      onSelectNode(null)
                      setSelectedEdgeId(edge.id)
                      setInspectorTab('ports')
                    }}
                    onEdgeContextMenu={openEdgeContextMenu}
                    onEdgesChange={onEdgesChange}
                    onEdgesDelete={(deleted) => {
                      if (deleted.some((edge) => edge.id === selectedEdgeId)) setSelectedEdgeId(null)
                    }}
                    onInit={setFlowInstance}
                    onNodeClick={(_, node) => {
                      setSelectedEdgeId(null)
                      onSelectNode(node.id)
                    }}
                    onNodeContextMenu={openNodeContextMenu}
                    onNodeDoubleClick={(_, node) => onOpenNode(node)}
                    onNodesChange={onNodesChange}
                    onNodesDelete={(deleted) => {
                      if (deleted.some((node) => node.id === selectedNodeId)) onSelectNode(null)
                    }}
                    onPaneClick={() => {
                      onSelectNode(null)
                      setSelectedEdgeId(null)
                      closeContextMenu()
                    }}
                    onPaneContextMenu={openPaneContextMenu}
                    onReconnect={(oldEdge, connection) => {
                      if (!connectionIsValid({ ...oldEdge, ...connection })) return
                      setEdges((current) => reconnectEdge(oldEdge, connection, current))
                    }}
                    selectionOnDrag
                  >
                    <Background color="#27423a" gap={22} size={1} />
                    <Controls position="bottom-left" showInteractive />
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

                  {nodes.length === 0 && (
                    <div className="empty-workflow-canvas">
                      <GitBranch size={27} />
                      <strong>{tr('空白工作流', 'Blank workflow')}</strong>
                      <span>
                        {tr(
                          '在这里右键添加第一个节点，或从左侧节点库选择。',
                          'Right-click here to add the first node, or choose one from the library.',
                        )}
                      </span>
                    </div>
                  )}

                  {contextMenu && (
                    <div
                      className={`workflow-context-menu kind-${contextMenu.kind}`}
                      onPointerDown={(event) => event.stopPropagation()}
                      style={{ left: contextMenu.x, top: contextMenu.y }}
                    >
                      {contextMenu.kind === 'edge' ? (
                        <>
                          <strong>{tr('连线操作', 'Edge actions')}</strong>
                          <button
                            className="danger"
                            onClick={() => contextMenu.targetId && deleteEdge(contextMenu.targetId)}
                            type="button"
                          >
                            <Trash2 size={14} /> {tr('删除这条连线', 'Delete this edge')}
                          </button>
                          <small>
                            {tr(
                              '也可以选中连线后按 Delete；拖动端点可重新连接。',
                              'You can also select it and press Delete, or drag an endpoint to reconnect.',
                            )}
                          </small>
                        </>
                      ) : (
                        <>
                          {contextMenu.kind === 'node' && (() => {
                            const node = nodes.find((candidate) => candidate.id === contextMenu.targetId)
                            if (!node) return null
                            return (
                              <div className="context-node-actions">
                                <strong>{localizeNodeDefinition(node.data.definition, language).title}</strong>
                                <button onClick={() => onOpenNode(node)} type="button">
                                  <PanelRightOpen size={14} /> {tr('打开对应页面', 'Open workspace')}
                                </button>
                                <button onClick={() => duplicateNode(node)} type="button">
                                  <Copy size={14} /> {tr('复制节点', 'Duplicate node')}
                                </button>
                                <button className="danger" onClick={() => deleteNode(node.id)} type="button">
                                  <Trash2 size={14} /> {tr('删除节点', 'Delete node')}
                                </button>
                              </div>
                            )
                          })()}
                          <div className="context-picker-heading">
                            <span>
                              {contextMenu.kind === 'node'
                                ? tr('插入后续节点', 'Insert next node')
                                : tr('在此处新建节点', 'Add node here')}
                            </span>
                          </div>
                          <label className="workflow-search">
                            <Search size={14} />
                            <input
                              autoFocus
                              onChange={(event) => setContextSearch(event.target.value)}
                              placeholder={tr('搜索节点', 'Search nodes')}
                              value={contextSearch}
                            />
                          </label>
                          <div className="context-node-picker">
                            {renderNodePicker(normalizedContextSearch, (definition) => {
                              const anchor = contextMenu.kind === 'node'
                                ? nodes.find((node) => node.id === contextMenu.targetId) ?? null
                                : null
                              addNode(definition, {
                                position: anchor ? undefined : contextMenu.flowPosition,
                                connectFrom: anchor,
                                arrange: Boolean(anchor),
                              })
                            })}
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          <aside className="node-inspector">
            <div className="panel-title">
              <span>{tr('详情与提示', 'Details & guidance')}</span>
              {selectedNode && <small>{selectedNode.data.definition.category}</small>}
            </div>
            {!selectedNode && !selectedEdge ? (
              <div className="inspector-empty-state">
                <BookOpen size={24} />
                <strong>{tr('选择节点或连线', 'Select a node or edge')}</strong>
                <p>
                  {tr(
                    '节点说明、所需输入、预期输出和可编辑参数会显示在这里。',
                    'Node purpose, required inputs, expected outputs, and editable parameters appear here.',
                  )}
                </p>
              </div>
            ) : selectedEdge ? (
              <div className="edge-inspector">
                <Link2 size={22} />
                <strong>{tr('工作流连线', 'Workflow edge')}</strong>
                <dl>
                  <div><dt>{tr('来源', 'Source')}</dt><dd>{selectedEdge.source}</dd></div>
                  <div><dt>{tr('目标', 'Target')}</dt><dd>{selectedEdge.target}</dd></div>
                  <div><dt>{tr('数据类型', 'Data type')}</dt><dd>{selectedEdge.sourceHandle?.split('::')[1] ?? '—'}</dd></div>
                </dl>
                <p>
                  {tr(
                    '连线表示数据依赖，不是页面跳转顺序。拖动端点可改接，Delete 可删除。',
                    'An edge represents a data dependency, not page navigation. Drag an endpoint to reconnect or press Delete to remove it.',
                  )}
                </p>
                <button className="secondary-button danger" onClick={() => deleteEdge(selectedEdge.id)} type="button">
                  <Trash2 size={14} /> {tr('删除连线', 'Delete edge')}
                </button>
              </div>
            ) : selectedNode && selectedGuide ? (
              <>
                <div className="inspector-node-summary">
                  <strong>{localizeNodeDefinition(selectedNode.data.definition, language).title}</strong>
                  <code>{selectedNode.data.definition.type_id}</code>
                  <p>{localizeNodeDefinition(selectedNode.data.definition, language).description}</p>
                  <button className="secondary-button" onClick={() => onOpenNode(selectedNode)} type="button">
                    <PanelRightOpen size={14} /> {tr('打开对应工作页面', 'Open corresponding workspace')}
                  </button>
                </div>
                <div className="inspector-tabs" role="tablist">
                  <button className={inspectorTab === 'guide' ? 'active' : ''} onClick={() => setInspectorTab('guide')} type="button">
                    <BookOpen size={13} /> {tr('说明', 'Guide')}
                  </button>
                  <button className={inspectorTab === 'parameters' ? 'active' : ''} onClick={() => setInspectorTab('parameters')} type="button">
                    <SlidersHorizontal size={13} /> {tr('参数', 'Parameters')}
                  </button>
                  <button className={inspectorTab === 'ports' ? 'active' : ''} onClick={() => setInspectorTab('ports')} type="button">
                    <Link2 size={13} /> {tr('输入输出', 'I/O')}
                  </button>
                </div>

                {inspectorTab === 'guide' && (
                  <div className="node-guide">
                    <section>
                      <span>{tr('作用', 'Purpose')}</span>
                      <p>{selectedGuide.purpose}</p>
                    </section>
                    <section>
                      <span>{tr('什么时候使用', 'When to use')}</span>
                      <p>{selectedGuide.useWhen}</p>
                    </section>
                    <section>
                      <span>{tr('开始前需要', 'Before it starts')}</span>
                      <ul>{selectedGuide.requirements.map((item) => <li key={item}>{item}</li>)}</ul>
                    </section>
                    <section>
                      <span>{tr('产生的结果', 'Outputs')}</span>
                      <ul>{selectedGuide.outputs.map((item) => <li key={item}>{item}</li>)}</ul>
                    </section>
                    {selectedGuide.caution && (
                      <section className="guide-caution">
                        <span>{tr('科学注意事项', 'Scientific caution')}</span>
                        <p>{selectedGuide.caution}</p>
                      </section>
                    )}
                  </div>
                )}

                {inspectorTab === 'parameters' && (
                  <div className="parameter-list">
                    {localizeNodeDefinition(selectedNode.data.definition, language).parameters.map((parameter) => (
                      <label key={parameter.key}>
                        <span>{parameter.label}</span>
                        {parameter.kind === 'boolean' ? (
                          <input
                            checked={Boolean(parameterValue(selectedNode, parameter.key, parameter.default))}
                            onChange={(event) => updateParameter(parameter.key, event.target.checked)}
                            type="checkbox"
                          />
                        ) : parameter.kind === 'choice' ? (
                          <select
                            onChange={(event) => updateParameter(parameter.key, event.target.value)}
                            value={String(parameterValue(selectedNode, parameter.key, parameter.default))}
                          >
                            {parameter.choices.map((choice) => (
                              <option key={choice} value={choice}>{choice}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            max={parameter.maximum ?? undefined}
                            min={parameter.minimum ?? undefined}
                            onChange={(event) =>
                              updateParameter(
                                parameter.key,
                                parameter.kind === 'string'
                                  ? event.target.value
                                  : Number(event.target.value),
                              )}
                            step={parameter.kind === 'integer' ? 1 : 'any'}
                            type={parameter.kind === 'string' ? 'text' : 'number'}
                            value={String(parameterValue(selectedNode, parameter.key, parameter.default))}
                          />
                        )}
                        {parameter.description && <small>{parameter.description}</small>}
                      </label>
                    ))}
                    {selectedNode.data.definition.parameters.length === 0 && (
                      <p className="panel-empty">
                        {tr(
                          '这个节点没有画布级参数；双击节点进入对应页面配置详细输入。',
                          'This node has no canvas-level parameters; double-click it to configure detailed inputs.',
                        )}
                      </p>
                    )}
                  </div>
                )}

                {inspectorTab === 'ports' && (
                  <div className="inspector-ports">
                    <section>
                      <span>{tr('输入', 'Inputs')}</span>
                      {selectedNode.data.definition.inputs.map((port) => (
                        <div key={port.port_id}>
                          <strong>{port.label}</strong>
                          <code>{port.kind}</code>
                          <small>{port.required ? tr('必需', 'required') : tr('可选', 'optional')}</small>
                        </div>
                      ))}
                      {selectedNode.data.definition.inputs.length === 0 && <p>{tr('无需上游输入', 'No upstream input')}</p>}
                    </section>
                    <section>
                      <span>{tr('输出', 'Outputs')}</span>
                      {selectedNode.data.definition.outputs.map((port) => (
                        <div key={port.port_id}>
                          <strong>{port.label}</strong>
                          <code>{port.kind}</code>
                          <small>{port.multiple ? tr('可多路连接', 'multiple connections') : tr('单路端口', 'single port')}</small>
                        </div>
                      ))}
                    </section>
                  </div>
                )}
              </>
            ) : null}
          </aside>
        </div>
      )}

      {view === 'lifecycle' && (
        <div className="workflow-release-view">
          <article className="release-explainer">
            <FileCheck2 size={24} />
            <div>
              <span className="eyebrow">CONTROLLED LIFECYCLE</span>
              <h3>{tr('草稿 → 发布版本 → 运行快照', 'Draft → revision → run snapshot')}</h3>
              <p>
                {tr(
                  '草稿是当前可编辑工作流；发布版本是不可变的科学记录；运行快照绑定一次具体执行，便于重现和追踪。',
                  'The draft is the editable workflow. A published revision is an immutable scientific record, and a run snapshot binds one concrete execution for reproducibility.',
                )}
              </p>
            </div>
          </article>
          <div className="release-actions">
            <button className="secondary-button" disabled={!projectReady || nodes.length === 0} onClick={onSave} type="button">
              <Save size={16} /> {tr('1. 保存草稿', '1. Save draft')}
            </button>
            <button className="secondary-button accent" disabled={!projectReady || nodes.length === 0} onClick={onPublish} type="button">
              <FileCheck2 size={16} /> {tr('2. 发布版本', '2. Publish revision')}
            </button>
            <button className="primary-button" disabled={!projectReady || revisions.length === 0} onClick={onCreateRunGraph} type="button">
              <Play size={16} /> {tr('3. 创建运行快照', '3. Create run snapshot')}
            </button>
          </div>
          <div className="release-record-grid">
            <section>
              <div className="panel-title">
                <span>{tr('发布版本', 'Published revisions')}</span>
                <small>{revisions.length}</small>
              </div>
              {revisions.map((revision) => (
                <article key={revision.revision_id}>
                  <strong>{revision.title || revision.revision_id}</strong>
                  <code>{revision.revision_id}</code>
                  <span>{revision.published_at_utc}</span>
                </article>
              ))}
              {revisions.length === 0 && <p className="panel-empty">{tr('尚未发布工作流。', 'No workflow revision has been published.')}</p>}
            </section>
            <section>
              <div className="panel-title">
                <span>{tr('运行快照', 'Run snapshots')}</span>
                <small>{runGraphs.length}</small>
              </div>
              {runGraphs.map((runGraph) => (
                <article key={runGraph.run_graph_id}>
                  <strong>{runGraph.label || runGraph.run_graph_id}</strong>
                  <code>{runGraph.run_graph_id}</code>
                  <span>{runGraph.state}</span>
                </article>
              ))}
              {runGraphs.length === 0 && <p className="panel-empty">{tr('尚未创建运行快照。', 'No run snapshot has been created.')}</p>}
            </section>
          </div>
        </div>
      )}

      {showTemplates && (
        <div className="workflow-template-overlay" role="dialog" aria-modal="true">
          <button className="workflow-template-backdrop" onClick={() => setShowTemplates(false)} type="button" />
          <section>
            <header>
              <div>
                <span className="eyebrow">TEMPLATES</span>
                <h3>{tr('选择一个工作流起点', 'Choose a workflow starting point')}</h3>
                <p>{tr('模板载入后仍可删除节点、重新连线或添加分支。', 'After loading, every node and edge remains editable.')}</p>
              </div>
              <button onClick={() => setShowTemplates(false)} type="button"><X size={18} /></button>
            </header>
            <div className="quick-build-grid">
              {templates.map((template) => {
                const copy = localizeWorkflowTemplate(template, language)
                return (
                  <article className="quick-template-card" key={template.template_id}>
                    <div>
                      <span>{template.nodes.length} NODES</span>
                      <strong>{copy.title}</strong>
                      <p>{copy.description}</p>
                    </div>
                    <div className="template-node-strip">
                      {template.nodes.map((node) => (
                        <span key={node.node_id}>
                          {localizeNodeDefinition(
                            registry.get(node.type_id) ?? {
                              type_id: node.type_id,
                              title: node.type_id,
                              description: '',
                              category: 'calculation',
                              inputs: [],
                              outputs: [],
                              parameters: [],
                              review_gate: false,
                            },
                            language,
                          ).title}
                        </span>
                      ))}
                    </div>
                    <button className="secondary-button" onClick={() => applyTemplate(template)} type="button">
                      <Plus size={15} /> {tr('使用此模板', 'Use template')}
                    </button>
                  </article>
                )
              })}
            </div>
          </section>
        </div>
      )}
    </section>
  )
}
