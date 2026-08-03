import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Connection,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react'
import {
  Boxes,
  Copy,
  FileCheck2,
  GitBranch,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  Save,
  ServerOff,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { useMemo, useState, type Dispatch, type SetStateAction } from 'react'

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
  type ScientificFlowEdge,
  type ScientificFlowNode,
} from '../workflow'
import { ScientificNode } from './ScientificNode'

const nodeTypes = { scientific: ScientificNode }

type WorkbenchMode = 'quick' | 'graph' | 'run'

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
  onNodesChange: OnNodesChange<ScientificFlowNode>
  onEdgesChange: OnEdgesChange<ScientificFlowEdge>
  setNodes: Dispatch<SetStateAction<ScientificFlowNode[]>>
  setEdges: Dispatch<SetStateAction<ScientificFlowEdge[]>>
  onConnect: (connection: Connection) => void
  onSelectNode: (nodeId: string | null) => void
  onOpenNode: (node: ScientificFlowNode) => void
  onApplyTemplate: (template: WorkflowTemplateCatalogItem) => void
  onValidate: () => void
  onSave: () => void
  onPublish: () => void
  onCreateRunGraph: () => void
  onReset: () => void
  onRetry: () => void
}

function parameterValue(
  node: ScientificFlowNode,
  key: string,
  fallback: string | number | boolean,
) {
  return node.data.parameters[key] ?? fallback
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
  onNodesChange,
  onEdgesChange,
  setNodes,
  setEdges,
  onConnect,
  onSelectNode,
  onOpenNode,
  onApplyTemplate,
  onValidate,
  onSave,
  onPublish,
  onCreateRunGraph,
  onReset,
  onRetry,
}: WorkflowWorkbenchProps) {
  const { language, tr } = useI18n()
  const [mode, setMode] = useState<WorkbenchMode>('quick')
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null
  const palette = useMemo(
    () =>
      [...registry.values()].filter(
        (definition) => !definition.review_gate && definition.type_id !== 'execution.mock',
      ),
    [registry],
  )

  const addNode = (definition: NodeDefinition) => {
    const id = `${definition.type_id.replaceAll('.', '-')}-${Date.now().toString(36)}`
    const node = createFlowNode(
      definition,
      {
        x: 80 + (nodes.length % 4) * 260,
        y: 80 + Math.floor(nodes.length / 4) * 190,
      },
      id,
    )
    setNodes((current) => [...current, node])
    onSelectNode(id)
  }

  const deleteSelected = () => {
    if (!selectedNodeId) return
    setNodes((current) => current.filter((node) => node.id !== selectedNodeId))
    setEdges((current) =>
      current.filter(
        (edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId,
      ),
    )
    onSelectNode(null)
  }

  const duplicateSelected = () => {
    if (!selectedNode) return
    const id = `${selectedNode.data.definition.type_id.replaceAll('.', '-')}-${Date.now().toString(36)}`
    setNodes((current) => [
      ...current,
      {
        ...selectedNode,
        id,
        position: {
          x: selectedNode.position.x + 44,
          y: selectedNode.position.y + 44,
        },
        data: {
          ...selectedNode.data,
          parameters: { ...selectedNode.data.parameters },
          status: 'idle',
          detail: undefined,
        },
        selected: false,
      },
    ])
    onSelectNode(id)
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

  return (
    <section className="workflow-workbench">
      <header className="workflow-workbench-header">
        <div>
          <span className="eyebrow">WORKFLOW STUDIO</span>
          <h2>{tr('可编辑计算工作流', 'Editable calculation workflows')}</h2>
          <p>
            {tr(
              '快速构建负责常用流程，节点图负责高级编辑，运行视图使用已发布的不可变版本。',
              'Quick Build covers common flows, the graph supports advanced editing, and Run uses immutable published revisions.',
            )}
          </p>
        </div>
        <div className="workflow-mode-switch" role="tablist">
          <button
            className={mode === 'quick' ? 'active' : ''}
            onClick={() => setMode('quick')}
            type="button"
          >
            <Boxes size={15} /> {tr('快速构建', 'Quick Build')}
          </button>
          <button
            className={mode === 'graph' ? 'active' : ''}
            onClick={() => setMode('graph')}
            type="button"
          >
            <GitBranch size={15} /> {tr('节点图', 'Graph')}
          </button>
          <button
            className={mode === 'run' ? 'active' : ''}
            onClick={() => setMode('run')}
            type="button"
          >
            <Play size={15} /> {tr('发布与运行', 'Publish & Run')}
          </button>
        </div>
      </header>

      {mode === 'quick' && (
        <div className="quick-build-grid">
          {templates.map((template) => (
            <article className="quick-template-card" key={template.template_id}>
              <div>
                <span>{template.nodes.length} NODES</span>
                <strong>{localizeWorkflowTemplate(template, language).title}</strong>
                <p>{localizeWorkflowTemplate(template, language).description}</p>
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
              <button
                className="secondary-button"
                onClick={() => {
                  onApplyTemplate(template)
                  setMode('graph')
                }}
                type="button"
              >
                <Plus size={15} /> {tr('使用此模板', 'Use template')}
              </button>
            </article>
          ))}
        </div>
      )}

      {mode === 'graph' && (
        <div className="workflow-editor">
          <aside className="node-palette">
            <div className="panel-title">
              <span>{tr('节点库', 'Node library')}</span>
              <small>{palette.length}</small>
            </div>
            <div className="node-palette-list">
              {palette.map((definition) => {
                const localized = localizeNodeDefinition(definition, language)
                return (
                  <button
                    key={definition.type_id}
                    onClick={() => addNode(definition)}
                    title={localized.description}
                    type="button"
                  >
                    <Plus size={13} />
                    <span>
                      <strong>{localized.title}</strong>
                      <small>{localized.category}</small>
                    </span>
                  </button>
                )
              })}
            </div>
          </aside>

          <div className="workflow-graph-panel">
            <div className="workflow-graph-toolbar">
              <button onClick={onValidate} type="button">
                <ShieldCheck size={14} /> {tr('校验', 'Validate')}
              </button>
              <button onClick={onSave} type="button">
                <Save size={14} /> {tr('保存草稿', 'Save draft')}
              </button>
              <button disabled={!selectedNode} onClick={duplicateSelected} type="button">
                <Copy size={14} /> {tr('复制', 'Duplicate')}
              </button>
              <button
                className="danger"
                disabled={!selectedNode}
                onClick={deleteSelected}
                type="button"
              >
                <Trash2 size={14} /> {tr('删除节点', 'Delete node')}
              </button>
              <button onClick={onReset} type="button">
                <RefreshCw size={14} /> {tr('恢复默认', 'Reset')}
              </button>
            </div>
            <div className="workflow-canvas">
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
                <ReactFlow
                  colorMode="dark"
                  defaultEdgeOptions={{ type: 'smoothstep' }}
                  edges={edges}
                  fitView
                  fitViewOptions={{ padding: 0.18 }}
                  isValidConnection={(connection) =>
                    compatibleHandles(
                      connection.sourceHandle ?? null,
                      connection.targetHandle ?? null,
                    )
                  }
                  maxZoom={1.5}
                  minZoom={0.2}
                  nodeTypes={nodeTypes}
                  nodes={nodes}
                  onConnect={onConnect}
                  onEdgesChange={onEdgesChange}
                  onNodeClick={(_, node) => onSelectNode(node.id)}
                  onNodeDoubleClick={(_, node) => onOpenNode(node)}
                  onNodesChange={onNodesChange}
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
              )}
            </div>
          </div>

          <aside className="node-inspector">
            <div className="panel-title">
              <span>{tr('节点参数', 'Node parameters')}</span>
            </div>
            {!selectedNode ? (
              <p className="panel-empty">
                {tr('选择一个节点查看参数。', 'Select a node to inspect its parameters.')}
              </p>
            ) : (
              <>
                <div className="inspector-node-summary">
                  <strong>
                    {
                      localizeNodeDefinition(
                        selectedNode.data.definition,
                        language,
                      ).title
                    }
                  </strong>
                  <code>{selectedNode.id}</code>
                  <p>
                    {
                      localizeNodeDefinition(
                        selectedNode.data.definition,
                        language,
                      ).description
                    }
                  </p>
                </div>
                <div className="parameter-list">
                  {localizeNodeDefinition(
                    selectedNode.data.definition,
                    language,
                  ).parameters.map((parameter) => (
                    <label key={parameter.key}>
                      <span>{parameter.label}</span>
                      {parameter.kind === 'boolean' ? (
                        <input
                          checked={Boolean(
                            parameterValue(selectedNode, parameter.key, parameter.default),
                          )}
                          onChange={(event) =>
                            updateParameter(parameter.key, event.target.checked)
                          }
                          type="checkbox"
                        />
                      ) : parameter.kind === 'choice' ? (
                        <select
                          onChange={(event) =>
                            updateParameter(parameter.key, event.target.value)
                          }
                          value={String(
                            parameterValue(selectedNode, parameter.key, parameter.default),
                          )}
                        >
                          {parameter.choices.map((choice) => (
                            <option key={choice} value={choice}>
                              {choice}
                            </option>
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
                            )
                          }
                          step={parameter.kind === 'integer' ? 1 : 'any'}
                          type={parameter.kind === 'string' ? 'text' : 'number'}
                          value={String(
                            parameterValue(selectedNode, parameter.key, parameter.default),
                          )}
                        />
                      )}
                      {parameter.description && <small>{parameter.description}</small>}
                    </label>
                  ))}
                  {selectedNode.data.definition.parameters.length === 0 && (
                    <p className="panel-empty">
                      {tr(
                        '这个节点没有独立参数；双击可进入对应工作页面。',
                        'This node has no local parameters; double-click to open its workspace.',
                      )}
                    </p>
                  )}
                </div>
              </>
            )}
          </aside>
        </div>
      )}

      {mode === 'run' && (
        <div className="workflow-release-view">
          <article className="release-explainer">
            <FileCheck2 size={24} />
            <div>
              <span className="eyebrow">CONTROLLED LIFECYCLE</span>
              <h3>{tr('草稿 → 发布版本 → 运行快照', 'Draft → revision → run snapshot')}</h3>
              <p>
                {tr(
                  '草稿可以继续编辑；发布版本内容不可更改；每次运行从发布版本复制一份不可变快照，节点重试只追加尝试记录。',
                  'Drafts remain editable. Published revisions are immutable. Each run copies a revision into an immutable snapshot, while retries append attempt records.',
                )}
              </p>
            </div>
          </article>
          <div className="release-actions">
            <button
              className="secondary-button"
              disabled={!projectReady}
              onClick={onSave}
              type="button"
            >
              <Save size={16} /> {tr('1. 保存草稿', '1. Save draft')}
            </button>
            <button
              className="secondary-button accent"
              disabled={!projectReady}
              onClick={onPublish}
              type="button"
            >
              <FileCheck2 size={16} /> {tr('2. 发布版本', '2. Publish revision')}
            </button>
            <button
              className="primary-button"
              disabled={!projectReady || revisions.length === 0}
              onClick={onCreateRunGraph}
              type="button"
            >
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
              {revisions.length === 0 && (
                <p className="panel-empty">
                  {tr('尚未发布工作流。', 'No workflow revision has been published.')}
                </p>
              )}
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
              {runGraphs.length === 0 && (
                <p className="panel-empty">
                  {tr('尚未创建运行快照。', 'No run snapshot has been created.')}
                </p>
              )}
            </section>
          </div>
        </div>
      )}
    </section>
  )
}
