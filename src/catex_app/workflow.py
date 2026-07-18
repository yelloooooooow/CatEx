"""Versioned, UI-neutral workflow contracts for the CatEx workbench."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from catex.models import Diagnostic, Severity


class PortKind(StrEnum):
    """Scientific data types that may be connected in the authoring graph."""

    STRUCTURE_ARTIFACT = "structure_artifact"
    STRUCTURE_RECORD = "structure_record"
    HPC_READY_CONTEXT = "hpc_ready_context"
    REVIEWED_STRUCTURE = "reviewed_structure"
    VALIDATED_INPUT = "validated_input"
    CALCULATION_PLAN = "calculation_plan"
    RUN_EVIDENCE = "run_evidence"
    PARSED_RESULT = "parsed_result"
    REVIEWED_RESULT = "reviewed_result"
    RESULT_SUMMARY = "result_summary"


class NodeCategory(StrEnum):
    SOURCE = "source"
    STRUCTURE = "structure"
    REVIEW = "review"
    PROTOCOL = "protocol"
    EXECUTION = "execution"
    PARSING = "parsing"


@dataclass(frozen=True, slots=True)
class PortDefinition:
    port_id: str
    label: str
    kind: PortKind
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "port_id": self.port_id,
            "label": self.label,
            "kind": self.kind.value,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    type_id: str
    title: str
    description: str
    category: NodeCategory
    inputs: tuple[PortDefinition, ...] = ()
    outputs: tuple[PortDefinition, ...] = ()
    review_gate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "type_id": self.type_id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "inputs": [item.to_dict() for item in self.inputs],
            "outputs": [item.to_dict() for item in self.outputs],
            "review_gate": self.review_gate,
        }


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    node_id: str
    type_id: str
    position_x: float
    position_y: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "type_id": self.type_id,
            "position": {"x": self.position_x, "y": self.position_y},
        }


@dataclass(frozen=True, slots=True)
class WorkflowEdge:
    edge_id: str
    source_node_id: str
    source_port_id: str
    target_node_id: str
    target_port_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "source_port_id": self.source_port_id,
            "target_node_id": self.target_node_id,
            "target_port_id": self.target_port_id,
        }


@dataclass(frozen=True, slots=True)
class WorkflowTemplate:
    template_id: str
    title: str
    description: str
    nodes: tuple[WorkflowNode, ...]
    edges: tuple[WorkflowEdge, ...]
    schema_version: str = "catex.workflow-template.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "template_id": self.template_id,
            "title": self.title,
            "description": self.description,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
        }


@dataclass(frozen=True, slots=True)
class WorkflowValidationReport:
    diagnostics: tuple[Diagnostic, ...]
    schema_version: str = "catex.workflow-validation.v1"

    @property
    def valid(self) -> bool:
        return not any(item.severity is Severity.ERROR for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": "valid" if self.valid else "error",
            "valid": self.valid,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def _port(port_id: str, label: str, kind: PortKind) -> PortDefinition:
    return PortDefinition(port_id=port_id, label=label, kind=kind)


_NODE_DEFINITIONS = (
    NodeDefinition(
        "structure.upload",
        "上传结构",
        "导入 POSCAR 或 CIF; 源文件保持不可变。",
        NodeCategory.SOURCE,
        outputs=(_port("structure", "结构文件", PortKind.STRUCTURE_ARTIFACT),),
    ),
    NodeDefinition(
        "structure.inspect",
        "结构检查",
        "调用 CatEx 只读检查并生成几何诊断。",
        NodeCategory.STRUCTURE,
        inputs=(_port("structure", "结构文件", PortKind.STRUCTURE_ARTIFACT),),
        outputs=(_port("record", "结构记录", PortKind.STRUCTURE_RECORD),),
    ),
    NodeDefinition(
        "review.structure",
        "结构审核",
        "显式确认结构、位点和 provenance, 不自动批准。",
        NodeCategory.REVIEW,
        inputs=(_port("record", "结构记录", PortKind.STRUCTURE_RECORD),),
        outputs=(_port("approved", "已审核结构", PortKind.REVIEWED_STRUCTURE),),
        review_gate=True,
    ),
    NodeDefinition(
        "hpc.connect",
        "连接运行中心",
        "进入运行中心并只读验证 SSH、远端白名单和 POTCAR 构建器。",
        NodeCategory.EXECUTION,
        inputs=(_port("structure", "结构记录", PortKind.STRUCTURE_RECORD),),
        outputs=(_port("context", "已连接计算上下文", PortKind.HPC_READY_CONTEXT),),
    ),
    NodeDefinition(
        "vasp.validate.auto",
        "VASP 输入诊断",
        "根据结构检查和协议规则自动诊断输入; 错误会阻止计算, 警告会保留显示。",
        NodeCategory.PROTOCOL,
        inputs=(_port("context", "已连接计算上下文", PortKind.HPC_READY_CONTEXT),),
        outputs=(_port("validated", "已验证输入", PortKind.VALIDATED_INPUT),),
    ),
    NodeDefinition(
        "vasp.validate",
        "VASP 输入验证",
        "验证协议和输入兼容性; POC 不生成 POTCAR。",
        NodeCategory.PROTOCOL,
        inputs=(_port("structure", "已审核结构", PortKind.REVIEWED_STRUCTURE),),
        outputs=(_port("validated", "已验证输入", PortKind.VALIDATED_INPUT),),
    ),
    NodeDefinition(
        "slurm.plan",
        "Slurm 计划",
        "生成并检查计划, 但不调用调度器。",
        NodeCategory.EXECUTION,
        inputs=(_port("input", "已验证输入", PortKind.VALIDATED_INPUT),),
        outputs=(_port("plan", "计算计划", PortKind.CALCULATION_PLAN),),
    ),
    NodeDefinition(
        "slurm.submit",
        "上传并提交",
        "在命名的远端项目目录中上传输入、生成 POTCAR, 并在用户确认后提交 Slurm。",
        NodeCategory.EXECUTION,
        inputs=(_port("plan", "计算计划", PortKind.CALCULATION_PLAN),),
        outputs=(_port("evidence", "运行证据", PortKind.RUN_EVIDENCE),),
    ),
    NodeDefinition(
        "execution.mock",
        "合成运行",
        "仅演示状态变化, 不连接 HPC 或执行 VASP。",
        NodeCategory.EXECUTION,
        inputs=(_port("plan", "计算计划", PortKind.CALCULATION_PLAN),),
        outputs=(_port("evidence", "运行证据", PortKind.RUN_EVIDENCE),),
    ),
    NodeDefinition(
        "vasp.parse",
        "结果解析",
        "使用 CatEx 解析合成 OUTCAR/OSZICAR。",
        NodeCategory.PARSING,
        inputs=(_port("evidence", "运行证据", PortKind.RUN_EVIDENCE),),
        outputs=(_port("result", "解析结果", PortKind.PARSED_RESULT),),
    ),
    NodeDefinition(
        "results.summarize",
        "结果汇总",
        "自动汇总能量、收敛结论、最终结构、振动与诊断信息。",
        NodeCategory.PARSING,
        inputs=(_port("result", "解析结果", PortKind.PARSED_RESULT),),
        outputs=(_port("summary", "结果汇总", PortKind.RESULT_SUMMARY),),
    ),
    NodeDefinition(
        "review.result",
        "结果审核",
        "区分运行结束、科学收敛和人工接受。",
        NodeCategory.REVIEW,
        inputs=(_port("result", "解析结果", PortKind.PARSED_RESULT),),
        outputs=(_port("accepted", "已审核结果", PortKind.REVIEWED_RESULT),),
        review_gate=True,
    ),
)

NODE_REGISTRY: Mapping[str, NodeDefinition] = MappingProxyType(
    {item.type_id: item for item in _NODE_DEFINITIONS}
)


def node_registry_payload() -> list[dict[str, Any]]:
    return [item.to_dict() for item in _NODE_DEFINITIONS]


def default_workflow_template() -> WorkflowTemplate:
    """Return the deterministic, read-only POC workflow template."""

    node_types = (
        "structure.upload",
        "structure.inspect",
        "hpc.connect",
        "vasp.validate.auto",
        "slurm.plan",
        "slurm.submit",
        "vasp.parse",
        "results.summarize",
    )
    # A compact snake layout keeps node text legible when the graph is fitted
    # into the central workbench. A single eight-node row forced the browser to
    # zoom out so far that the workflow could be seen but not comfortably read.
    positions = (
        (0.0, 0.0),
        (300.0, 0.0),
        (600.0, 0.0),
        (600.0, 220.0),
        (300.0, 220.0),
        (0.0, 220.0),
        (0.0, 440.0),
        (300.0, 440.0),
    )
    nodes = tuple(
        WorkflowNode(
            node_id=f"node-{index + 1}",
            type_id=type_id,
            position_x=positions[index][0],
            position_y=positions[index][1],
        )
        for index, type_id in enumerate(node_types)
    )
    edges: list[WorkflowEdge] = []
    for index in range(len(nodes) - 1):
        source = NODE_REGISTRY[nodes[index].type_id]
        target = NODE_REGISTRY[nodes[index + 1].type_id]
        edges.append(
            WorkflowEdge(
                edge_id=f"edge-{index + 1}",
                source_node_id=nodes[index].node_id,
                source_port_id=source.outputs[0].port_id,
                target_node_id=nodes[index + 1].node_id,
                target_port_id=target.inputs[0].port_id,
            )
        )
    return WorkflowTemplate(
        template_id="structure-to-results",
        title="结构到计算结果",
        description="结构检查、VASP 输入诊断、运行、结果解析和自动汇总工作流。",
        nodes=nodes,
        edges=tuple(edges),
    )


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_workflow(
    nodes: tuple[WorkflowNode, ...], edges: tuple[WorkflowEdge, ...]
) -> WorkflowValidationReport:
    """Validate graph identity, typed ports, required inputs, and acyclicity."""

    diagnostics: list[Diagnostic] = []
    duplicate_nodes = _duplicates(item.node_id for item in nodes)
    duplicate_edges = _duplicates(item.edge_id for item in edges)
    for node_id in sorted(duplicate_nodes):
        diagnostics.append(
            Diagnostic(
                "WORKFLOW_NODE_ID_DUPLICATE",
                Severity.ERROR,
                "Workflow node IDs must be unique.",
                {"node_id": node_id},
            )
        )
    for edge_id in sorted(duplicate_edges):
        diagnostics.append(
            Diagnostic(
                "WORKFLOW_EDGE_ID_DUPLICATE",
                Severity.ERROR,
                "Workflow edge IDs must be unique.",
                {"edge_id": edge_id},
            )
        )

    node_map = {item.node_id: item for item in nodes}
    for node in nodes:
        if node.type_id not in NODE_REGISTRY:
            diagnostics.append(
                Diagnostic(
                    "WORKFLOW_NODE_TYPE_UNKNOWN",
                    Severity.ERROR,
                    "The workflow contains an unregistered node type.",
                    {"node_id": node.node_id, "type_id": node.type_id},
                )
            )

    connected_inputs: set[tuple[str, str]] = set()
    adjacency: dict[str, set[str]] = {node.node_id: set() for node in nodes}
    for edge in edges:
        source_node = node_map.get(edge.source_node_id)
        target_node = node_map.get(edge.target_node_id)
        if source_node is None or target_node is None:
            diagnostics.append(
                Diagnostic(
                    "WORKFLOW_EDGE_NODE_MISSING",
                    Severity.ERROR,
                    "Every edge endpoint must reference an existing node.",
                    {"edge_id": edge.edge_id},
                )
            )
            continue
        source_definition = NODE_REGISTRY.get(source_node.type_id)
        target_definition = NODE_REGISTRY.get(target_node.type_id)
        if source_definition is None or target_definition is None:
            continue
        source_port = next(
            (item for item in source_definition.outputs if item.port_id == edge.source_port_id),
            None,
        )
        target_port = next(
            (item for item in target_definition.inputs if item.port_id == edge.target_port_id),
            None,
        )
        if source_port is None or target_port is None:
            diagnostics.append(
                Diagnostic(
                    "WORKFLOW_EDGE_PORT_MISSING",
                    Severity.ERROR,
                    "Every edge must reference registered source and target ports.",
                    {"edge_id": edge.edge_id},
                )
            )
            continue
        if source_port.kind is not target_port.kind:
            diagnostics.append(
                Diagnostic(
                    "WORKFLOW_PORT_KIND_MISMATCH",
                    Severity.ERROR,
                    "Connected workflow ports must have the same scientific type.",
                    {
                        "edge_id": edge.edge_id,
                        "source_kind": source_port.kind.value,
                        "target_kind": target_port.kind.value,
                    },
                )
            )
        input_key = (edge.target_node_id, edge.target_port_id)
        if input_key in connected_inputs:
            diagnostics.append(
                Diagnostic(
                    "WORKFLOW_INPUT_CONNECTED_MULTIPLE_TIMES",
                    Severity.ERROR,
                    "A single-value input port can have only one incoming edge.",
                    {"node_id": edge.target_node_id, "port_id": edge.target_port_id},
                )
            )
        connected_inputs.add(input_key)
        adjacency[edge.source_node_id].add(edge.target_node_id)

    for node in nodes:
        definition = NODE_REGISTRY.get(node.type_id)
        if definition is None:
            continue
        for port in definition.inputs:
            if port.required and (node.node_id, port.port_id) not in connected_inputs:
                diagnostics.append(
                    Diagnostic(
                        "WORKFLOW_REQUIRED_INPUT_MISSING",
                        Severity.ERROR,
                        "A required node input is not connected.",
                        {"node_id": node.node_id, "port_id": port.port_id},
                    )
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(child) for child in adjacency.get(node_id, ())):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    if any(visit(node_id) for node_id in adjacency if node_id not in visited):
        diagnostics.append(
            Diagnostic(
                "WORKFLOW_CYCLE_DETECTED",
                Severity.ERROR,
                "The POC workflow graph must be acyclic.",
            )
        )

    if not diagnostics:
        diagnostics.append(
            Diagnostic(
                "WORKFLOW_VALIDATED",
                Severity.INFO,
                "Workflow identities, ports, required inputs, and topology are valid.",
            )
        )
    return WorkflowValidationReport(tuple(diagnostics))
