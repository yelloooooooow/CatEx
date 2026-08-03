"""Compile an authored workflow into an explicit, non-executing stage plan."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

_STAGE_TYPES = {
    "mlip.chgnet.relax",
    "vasp.relax",
    "vasp.static",
    "vasp.frequency",
    "vasp.dos",
    "vasp.md",
    "slurm.submit",
}


class WorkflowExecutionPlanError(ValueError):
    """Raised when an immutable workflow cannot be compiled into stages."""


def _incar_overrides(type_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    if type_id == "vasp.relax":
        return {
            "IBRION": 2,
            "NSW": parameters.get("nsw", 200),
            "EDIFF": parameters.get("ediff", 1e-5),
            "EDIFFG": parameters.get("ediffg", -0.02),
        }
    if type_id == "vasp.static":
        return {
            "IBRION": -1,
            "NSW": 0,
            "LCHARG": parameters.get("write_charge", True),
            "LWAVE": parameters.get("write_wave", False),
        }
    if type_id == "vasp.frequency":
        return {
            "IBRION": 5,
            "NSW": 1,
            "POTIM": parameters.get("displacement", 0.015),
        }
    if type_id == "vasp.dos":
        return {
            "IBRION": -1,
            "NSW": 0,
            "LORBIT": int(parameters.get("lorbit", "11")),
            "NEDOS": parameters.get("nedos", 2000),
        }
    if type_id == "vasp.md":
        return {
            "IBRION": 0,
            "NSW": parameters.get("steps", 1000),
            "TEBEG": parameters.get("temperature_kelvin", 300.0),
            "TEEND": parameters.get("temperature_kelvin", 300.0),
        }
    return {}


def _outputs(type_id: str) -> list[str]:
    common = ["OUTCAR", "OSZICAR", "CONTCAR", "vasprun.xml"]
    if type_id == "mlip.chgnet.relax":
        return ["CONTCAR", "chgnet-result.json"]
    if type_id == "vasp.static":
        return [*common, "CHGCAR", "WAVECAR"]
    if type_id == "vasp.frequency":
        return [*common, "vibrational-modes.json"]
    if type_id == "vasp.dos":
        return [*common, "DOSCAR", "CHGCAR"]
    if type_id == "vasp.md":
        return [*common, "XDATCAR"]
    if type_id == "slurm.submit":
        return common
    return common


def compile_workflow_execution_plan(workflow: dict[str, Any]) -> dict[str, Any]:
    """Topologically compile scientific stages without writing files or running commands."""

    nodes = workflow.get("nodes")
    edges = workflow.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise WorkflowExecutionPlanError("workflow nodes and edges must be arrays")
    node_map = {str(node.get("node_id")): node for node in nodes if isinstance(node, dict)}
    if len(node_map) != len(nodes):
        raise WorkflowExecutionPlanError("workflow node identities are invalid or duplicated")
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    indegree = {node_id: 0 for node_id in node_map}
    for edge in edges:
        if not isinstance(edge, dict):
            raise WorkflowExecutionPlanError("workflow edge must be an object")
        source = str(edge.get("source_node_id"))
        target = str(edge.get("target_node_id"))
        if source not in node_map or target not in node_map:
            raise WorkflowExecutionPlanError("workflow edge references a missing node")
        if target not in outgoing[source]:
            outgoing[source].add(target)
            incoming[target].add(source)
            indegree[target] += 1
    queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    ordered: list[str] = []
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for target in sorted(outgoing[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(ordered) != len(node_map):
        raise WorkflowExecutionPlanError("workflow must be acyclic")

    stage_ids: dict[str, str] = {}
    stages: list[dict[str, Any]] = []

    def upstream_stages(node_id: str, visited: set[str] | None = None) -> set[str]:
        seen = set() if visited is None else visited
        if node_id in seen:
            return set()
        seen.add(node_id)
        found: set[str] = set()
        for source in incoming[node_id]:
            if source in stage_ids:
                found.add(stage_ids[source])
            else:
                found.update(upstream_stages(source, seen))
        return found

    for node_id in ordered:
        node = node_map[node_id]
        type_id = str(node.get("type_id"))
        if type_id not in _STAGE_TYPES:
            continue
        stage_id = f"stage-{len(stages) + 1:02d}-{type_id.replace('.', '-')}"
        stage_ids[node_id] = stage_id
        parameters = node.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}
        is_local = type_id == "mlip.chgnet.relax"
        dependencies = sorted(upstream_stages(node_id))
        stages.append(
            {
                "stage_id": stage_id,
                "node_id": node_id,
                "node_type": type_id,
                "depends_on": dependencies,
                "execution_backend": "local_chgnet" if is_local else "project_hpc_profile",
                "calculation_type": (
                    "vasp" if type_id == "slurm.submit" else type_id.rsplit(".", 1)[-1]
                ),
                "directory_name": f"{len(stages) + 1:02d}-{type_id.replace('.', '-')}",
                "structure_source": (
                    "project_structure" if not dependencies else "upstream_CONTCAR"
                ),
                "incar_overrides": _incar_overrides(type_id, parameters),
                "parameters": parameters,
                "required_inputs": (
                    ["POSCAR"] if is_local else ["POSCAR", "INCAR", "KPOINTS", "POTCAR"]
                ),
                "produced_outputs": _outputs(type_id),
            }
        )
    if not stages:
        raise WorkflowExecutionPlanError(
            "workflow contains no supported CHGNet or VASP calculation stage"
        )
    return {
        "schema_version": "catex.workflow-execution-plan.v1",
        "stage_count": len(stages),
        "stages": stages,
        "commands_executed": False,
        "files_written": False,
        "submitted": False,
        "automatic_scientific_parameter_changes": False,
    }
