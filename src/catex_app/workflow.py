"""Versioned, UI-neutral workflow contracts for the CatEx workbench."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
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
    CALCULATION_STATE = "calculation_state"
    EXPERIMENT_EVIDENCE_SET = "experiment_evidence_set"
    STRUCTURE_CATALOG = "structure_catalog"
    CANDIDATE_MODEL_SET = "candidate_model_set"
    REVIEWED_MODEL_SET = "reviewed_model_set"


class NodeCategory(StrEnum):
    EXPERIMENT = "experiment"
    SOURCE = "source"
    STRUCTURE = "structure"
    REVIEW = "review"
    PROTOCOL = "protocol"
    EXECUTION = "execution"
    PARSING = "parsing"
    CALCULATION = "calculation"


class ParameterKind(StrEnum):
    """Editor control and validation type for a workflow node parameter."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    CHOICE = "choice"


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    key: str
    label: str
    kind: ParameterKind
    default: Any
    description: str = ""
    required: bool = True
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind.value,
            "default": self.default,
            "description": self.description,
            "required": self.required,
            "choices": list(self.choices),
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True, slots=True)
class PortDefinition:
    port_id: str
    label: str
    kind: PortKind
    required: bool = True
    multiple: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "port_id": self.port_id,
            "label": self.label,
            "kind": self.kind.value,
            "required": self.required,
            "multiple": self.multiple,
        }


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    type_id: str
    title: str
    description: str
    category: NodeCategory
    inputs: tuple[PortDefinition, ...] = ()
    outputs: tuple[PortDefinition, ...] = ()
    parameters: tuple[ParameterDefinition, ...] = ()
    review_gate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "type_id": self.type_id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "inputs": [item.to_dict() for item in self.inputs],
            "outputs": [item.to_dict() for item in self.outputs],
            "parameters": [item.to_dict() for item in self.parameters],
            "review_gate": self.review_gate,
        }


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    node_id: str
    type_id: str
    position_x: float
    position_y: float
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "type_id": self.type_id,
            "position": {"x": self.position_x, "y": self.position_y},
            "parameters": dict(self.parameters),
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


def _port(
    port_id: str,
    label: str,
    kind: PortKind,
    *,
    required: bool = True,
    multiple: bool = False,
) -> PortDefinition:
    return PortDefinition(
        port_id=port_id,
        label=label,
        kind=kind,
        required=required,
        multiple=multiple,
    )


def _parameter(
    key: str,
    label: str,
    kind: ParameterKind,
    default: Any,
    *,
    description: str = "",
    choices: tuple[str, ...] = (),
    minimum: float | None = None,
    maximum: float | None = None,
) -> ParameterDefinition:
    return ParameterDefinition(
        key=key,
        label=label,
        kind=kind,
        default=default,
        description=description,
        choices=choices,
        minimum=minimum,
        maximum=maximum,
    )


_NODE_DEFINITIONS = (
    NodeDefinition(
        "experiment.evidence.prepare",
        "准备实验约束",
        "在项目实验建模工作区整理表征证据、测试条件和成分区间。",
        NodeCategory.EXPERIMENT,
        outputs=(_port("evidence", "实验约束集", PortKind.EXPERIMENT_EVIDENCE_SET),),
    ),
    NodeDefinition(
        "structure.catalog.prepare",
        "准备母体结构库",
        "组合项目结构、论文结构和显式获取的数据库快照。",
        NodeCategory.EXPERIMENT,
        outputs=(_port("catalog", "结构目录", PortKind.STRUCTURE_CATALOG),),
    ),
    NodeDefinition(
        "experiment.model.infer",
        "推断候选模型",
        "以规则规划器为默认, 将实验约束和母体结构转成有限候选集合。",
        NodeCategory.EXPERIMENT,
        inputs=(
            _port("evidence", "实验约束集", PortKind.EXPERIMENT_EVIDENCE_SET),
            _port("catalog", "结构目录", PortKind.STRUCTURE_CATALOG),
        ),
        outputs=(_port("candidates", "候选模型集", PortKind.CANDIDATE_MODEL_SET),),
        parameters=(
            _parameter(
                "planner",
                "规划器",
                ParameterKind.CHOICE,
                "rule",
                choices=("rule", "gpt"),
            ),
            _parameter(
                "maximum_representatives",
                "代表性模型上限",
                ParameterKind.INTEGER,
                10,
                minimum=1,
                maximum=50,
            ),
        ),
    ),
    NodeDefinition(
        "review.candidate_models",
        "审核候选模型",
        "显式选择可进入项目结构库的代表性模型, 不声明唯一真实结构。",
        NodeCategory.REVIEW,
        inputs=(_port("candidates", "候选模型集", PortKind.CANDIDATE_MODEL_SET),),
        outputs=(_port("approved", "已审核模型集", PortKind.REVIEWED_MODEL_SET),),
        review_gate=True,
    ),
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
        outputs=(_port("context", "已连接计算上下文", PortKind.HPC_READY_CONTEXT),),
    ),
    NodeDefinition(
        "vasp.validate.auto",
        "VASP 输入诊断",
        "根据已导入的 VASP 输入和协议规则自动诊断; 错误会阻止计算, 警告会保留显示。",
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
    NodeDefinition(
        "vasp.input.prepare",
        "准备 VASP 输入",
        "读取或生成 POSCAR、INCAR、KPOINTS 和 POTCAR 元数据, 并执行运行前诊断。",
        NodeCategory.PROTOCOL,
        outputs=(_port("state", "计算状态", PortKind.CALCULATION_STATE),),
        inputs=(
            _port(
                "models",
                "已审核模型集",
                PortKind.REVIEWED_MODEL_SET,
                required=False,
            ),
        ),
        parameters=(
            _parameter(
                "input_mode",
                "输入方式",
                ParameterKind.CHOICE,
                "project",
                choices=("project", "generated"),
            ),
            _parameter(
                "potcar_family",
                "POTCAR 数据集",
                ParameterKind.STRING,
                "PAW_PBE_54",
            ),
        ),
    ),
    NodeDefinition(
        "mlip.chgnet.relax",
        "CHGNet 预弛豫",
        "在本机使用机器学习势预弛豫; 结果必须经过确认后才进入 VASP。",
        NodeCategory.CALCULATION,
        inputs=(_port("input", "上游状态", PortKind.CALCULATION_STATE),),
        outputs=(_port("state", "预弛豫状态", PortKind.CALCULATION_STATE),),
        parameters=(
            _parameter(
                "enabled",
                "启用",
                ParameterKind.BOOLEAN,
                True,
            ),
            _parameter(
                "fmax_eV_per_angstrom",
                "最大残余力",
                ParameterKind.NUMBER,
                0.05,
                minimum=0.005,
                maximum=1.0,
            ),
            _parameter(
                "max_steps",
                "最大步数",
                ParameterKind.INTEGER,
                500,
                minimum=1,
                maximum=5000,
            ),
            _parameter(
                "relax_cell",
                "弛豫晶胞",
                ParameterKind.BOOLEAN,
                False,
            ),
        ),
    ),
    NodeDefinition(
        "vasp.relax",
        "VASP 结构优化",
        "执行离子弛豫, 并保留 CONTCAR、OUTCAR、OSZICAR 与重启文件。",
        NodeCategory.CALCULATION,
        inputs=(_port("input", "上游状态", PortKind.CALCULATION_STATE),),
        outputs=(_port("state", "优化后状态", PortKind.CALCULATION_STATE),),
        parameters=(
            _parameter(
                "ediff",
                "电子收敛阈值",
                ParameterKind.NUMBER,
                1e-5,
                minimum=1e-9,
                maximum=1e-2,
            ),
            _parameter(
                "ediffg",
                "离子收敛阈值",
                ParameterKind.NUMBER,
                -0.02,
                minimum=-1.0,
                maximum=0.0,
            ),
            _parameter(
                "nsw",
                "最大离子步",
                ParameterKind.INTEGER,
                200,
                minimum=1,
                maximum=2000,
            ),
        ),
    ),
    NodeDefinition(
        "vasp.static",
        "VASP 静态计算",
        "基于上游最终结构执行高精度单点能计算。",
        NodeCategory.CALCULATION,
        inputs=(_port("input", "上游状态", PortKind.CALCULATION_STATE),),
        outputs=(_port("state", "静态结果", PortKind.CALCULATION_STATE),),
        parameters=(
            _parameter(
                "write_charge",
                "输出 CHGCAR",
                ParameterKind.BOOLEAN,
                True,
            ),
            _parameter(
                "write_wave",
                "输出 WAVECAR",
                ParameterKind.BOOLEAN,
                False,
            ),
        ),
    ),
    NodeDefinition(
        "vasp.frequency",
        "VASP 振动频率",
        "对选定原子执行有限差分频率计算, 用于热力学校正。",
        NodeCategory.CALCULATION,
        inputs=(_port("input", "上游状态", PortKind.CALCULATION_STATE),),
        outputs=(_port("state", "振动结果", PortKind.CALCULATION_STATE),),
        parameters=(
            _parameter(
                "displacement",
                "位移步长",
                ParameterKind.NUMBER,
                0.015,
                minimum=0.001,
                maximum=0.1,
            ),
            _parameter(
                "mobile_selection",
                "活动原子",
                ParameterKind.STRING,
                "adsorbate",
            ),
        ),
    ),
    NodeDefinition(
        "vasp.dos",
        "VASP DOS",
        "从静态计算结果生成总态密度和投影态密度所需输入与结果。",
        NodeCategory.CALCULATION,
        inputs=(_port("input", "上游状态", PortKind.CALCULATION_STATE),),
        outputs=(_port("state", "DOS 结果", PortKind.CALCULATION_STATE),),
        parameters=(
            _parameter(
                "nedos",
                "能量网格点",
                ParameterKind.INTEGER,
                2000,
                minimum=100,
                maximum=20000,
            ),
            _parameter(
                "lorbit",
                "投影模式",
                ParameterKind.CHOICE,
                "11",
                choices=("10", "11", "12"),
            ),
        ),
    ),
    NodeDefinition(
        "vasp.md",
        "VASP 分子动力学",
        "执行显式配置的从头算分子动力学任务。",
        NodeCategory.CALCULATION,
        inputs=(_port("input", "上游状态", PortKind.CALCULATION_STATE),),
        outputs=(_port("state", "MD 结果", PortKind.CALCULATION_STATE),),
        parameters=(
            _parameter(
                "temperature_kelvin",
                "温度",
                ParameterKind.NUMBER,
                300.0,
                minimum=1.0,
                maximum=5000.0,
            ),
            _parameter(
                "steps",
                "步数",
                ParameterKind.INTEGER,
                1000,
                minimum=1,
                maximum=1000000,
            ),
        ),
    ),
    NodeDefinition(
        "results.collect",
        "汇集科学结果",
        "统一收集各计算阶段的结构、能量、振动、DOS 与 provenance。",
        NodeCategory.PARSING,
        inputs=(
            _port(
                "results",
                "计算结果",
                PortKind.CALCULATION_STATE,
                multiple=True,
            ),
        ),
        outputs=(_port("summary", "结果汇总", PortKind.RESULT_SUMMARY),),
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
        title="VASP 计算到结果",
        description="运行中心连接、VASP 输入诊断、Slurm 运行、结果解析和自动汇总工作流。",
        nodes=nodes,
        edges=tuple(edges),
    )


def _calculation_template(
    *,
    template_id: str,
    title: str,
    description: str,
    node_types: tuple[str, ...],
    connections: tuple[tuple[int, int], ...] | None = None,
) -> WorkflowTemplate:
    """Build a deterministic editable calculation template."""

    positions = (
        (0.0, 120.0),
        (300.0, 120.0),
        (600.0, 120.0),
        (900.0, 0.0),
        (900.0, 240.0),
        (1200.0, 120.0),
    )
    nodes = tuple(
        WorkflowNode(
            node_id=f"{template_id}-node-{index + 1}",
            type_id=type_id,
            position_x=positions[index][0],
            position_y=positions[index][1],
            parameters={
                parameter.key: parameter.default for parameter in NODE_REGISTRY[type_id].parameters
            },
        )
        for index, type_id in enumerate(node_types)
    )
    if connections is None:
        connections = tuple((index, index + 1) for index in range(len(nodes) - 1))
    edges = tuple(
        WorkflowEdge(
            edge_id=f"{template_id}-edge-{index + 1}",
            source_node_id=nodes[source_index].node_id,
            source_port_id=NODE_REGISTRY[nodes[source_index].type_id].outputs[0].port_id,
            target_node_id=nodes[target_index].node_id,
            target_port_id=NODE_REGISTRY[nodes[target_index].type_id].inputs[0].port_id,
        )
        for index, (source_index, target_index) in enumerate(connections)
    )
    return WorkflowTemplate(
        template_id=template_id,
        title=title,
        description=description,
        nodes=nodes,
        edges=edges,
    )


def _experiment_to_dft_template() -> WorkflowTemplate:
    """Connect experimental hypotheses to the existing reviewed DFT path."""

    node_types = (
        "experiment.evidence.prepare",
        "structure.catalog.prepare",
        "experiment.model.infer",
        "review.candidate_models",
        "vasp.input.prepare",
        "vasp.relax",
        "vasp.static",
        "results.collect",
    )
    positions = (
        (0.0, 0.0),
        (0.0, 220.0),
        (320.0, 110.0),
        (640.0, 110.0),
        (960.0, 110.0),
        (1260.0, 110.0),
        (1560.0, 110.0),
        (1860.0, 110.0),
    )
    nodes = tuple(
        WorkflowNode(
            node_id=f"experiment-to-dft-node-{index + 1}",
            type_id=type_id,
            position_x=positions[index][0],
            position_y=positions[index][1],
            parameters={
                parameter.key: parameter.default for parameter in NODE_REGISTRY[type_id].parameters
            },
        )
        for index, type_id in enumerate(node_types)
    )
    connection_ports = (
        (0, "evidence", 2, "evidence"),
        (1, "catalog", 2, "catalog"),
        (2, "candidates", 3, "candidates"),
        (3, "approved", 4, "models"),
        (4, "state", 5, "input"),
        (5, "state", 6, "input"),
        (6, "state", 7, "results"),
    )
    edges = tuple(
        WorkflowEdge(
            edge_id=f"experiment-to-dft-edge-{index + 1}",
            source_node_id=nodes[source_index].node_id,
            source_port_id=source_port,
            target_node_id=nodes[target_index].node_id,
            target_port_id=target_port,
        )
        for index, (
            source_index,
            source_port,
            target_index,
            target_port,
        ) in enumerate(connection_ports)
    )
    return WorkflowTemplate(
        template_id="experiment-to-dft",
        title="实验约束建模到 DFT",
        description=(
            "整理实验约束和母体结构, 推断并审核代表性模型, 再进入现有 VASP 优化和静态计算流程。"
        ),
        nodes=nodes,
        edges=edges,
    )


def workflow_template_catalog() -> tuple[WorkflowTemplate, ...]:
    """Return quick-build templates without coupling them to a research purpose."""

    return (
        _experiment_to_dft_template(),
        _calculation_template(
            template_id="vasp-relax",
            title="结构优化",
            description="准备输入、VASP 结构优化并汇集结果。",
            node_types=("vasp.input.prepare", "vasp.relax", "results.collect"),
        ),
        _calculation_template(
            template_id="vasp-relax-static",
            title="结构优化 + 静态计算",
            description="优化结构后执行高精度静态计算。",
            node_types=(
                "vasp.input.prepare",
                "vasp.relax",
                "vasp.static",
                "results.collect",
            ),
        ),
        _calculation_template(
            template_id="vasp-relax-frequency",
            title="结构优化 + 静态 + 振动频率",
            description="用于吸附能与振动热力学校正的数据链。",
            node_types=(
                "vasp.input.prepare",
                "vasp.relax",
                "vasp.static",
                "vasp.frequency",
                "results.collect",
            ),
            connections=((0, 1), (1, 2), (2, 3), (2, 4), (3, 4)),
        ),
        _calculation_template(
            template_id="vasp-relax-static-dos",
            title="结构优化 + 静态 + DOS",
            description="在静态计算基础上分支执行态密度计算。",
            node_types=(
                "vasp.input.prepare",
                "vasp.relax",
                "vasp.static",
                "vasp.dos",
                "results.collect",
            ),
            connections=((0, 1), (1, 2), (2, 3), (2, 4), (3, 4)),
        ),
        _calculation_template(
            template_id="chgnet-vasp-relax-static",
            title="CHGNet 预弛豫 + VASP 优化 + 静态",
            description="可选机器学习势预弛豫后进入 VASP 验证计算。",
            node_types=(
                "vasp.input.prepare",
                "mlip.chgnet.relax",
                "vasp.relax",
                "vasp.static",
                "results.collect",
            ),
        ),
        _calculation_template(
            template_id="vasp-md",
            title="从头算分子动力学",
            description="准备输入、执行 VASP MD 并汇集轨迹和运行结果。",
            node_types=("vasp.input.prepare", "vasp.md", "results.collect"),
        ),
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
        definition = NODE_REGISTRY.get(node.type_id)
        if definition is None:
            diagnostics.append(
                Diagnostic(
                    "WORKFLOW_NODE_TYPE_UNKNOWN",
                    Severity.ERROR,
                    "The workflow contains an unregistered node type.",
                    {"node_id": node.node_id, "type_id": node.type_id},
                )
            )
            continue
        parameter_map = {item.key: item for item in definition.parameters}
        for key in sorted(set(node.parameters) - set(parameter_map)):
            diagnostics.append(
                Diagnostic(
                    "WORKFLOW_PARAMETER_UNKNOWN",
                    Severity.ERROR,
                    "The workflow node contains an unregistered parameter.",
                    {"node_id": node.node_id, "parameter": key},
                )
            )
        for key, value in node.parameters.items():
            parameter = parameter_map.get(key)
            if parameter is None:
                continue
            valid_type = {
                ParameterKind.STRING: isinstance(value, str),
                ParameterKind.INTEGER: isinstance(value, int) and not isinstance(value, bool),
                ParameterKind.NUMBER: isinstance(value, (int, float))
                and not isinstance(value, bool),
                ParameterKind.BOOLEAN: isinstance(value, bool),
                ParameterKind.CHOICE: isinstance(value, str),
            }[parameter.kind]
            if not valid_type:
                diagnostics.append(
                    Diagnostic(
                        "WORKFLOW_PARAMETER_TYPE_INVALID",
                        Severity.ERROR,
                        "A workflow parameter has an invalid value type.",
                        {
                            "node_id": node.node_id,
                            "parameter": key,
                            "expected": parameter.kind.value,
                        },
                    )
                )
                continue
            if parameter.choices and value not in parameter.choices:
                diagnostics.append(
                    Diagnostic(
                        "WORKFLOW_PARAMETER_CHOICE_INVALID",
                        Severity.ERROR,
                        "A workflow choice parameter is outside the registered choices.",
                        {"node_id": node.node_id, "parameter": key, "value": value},
                    )
                )
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and parameter.minimum is not None
                and value < parameter.minimum
            ):
                diagnostics.append(
                    Diagnostic(
                        "WORKFLOW_PARAMETER_BELOW_MINIMUM",
                        Severity.ERROR,
                        "A workflow numeric parameter is below its minimum.",
                        {"node_id": node.node_id, "parameter": key, "value": value},
                    )
                )
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and parameter.maximum is not None
                and value > parameter.maximum
            ):
                diagnostics.append(
                    Diagnostic(
                        "WORKFLOW_PARAMETER_ABOVE_MAXIMUM",
                        Severity.ERROR,
                        "A workflow numeric parameter is above its maximum.",
                        {"node_id": node.node_id, "parameter": key, "value": value},
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
        if input_key in connected_inputs and not target_port.multiple:
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
