from __future__ import annotations

from pathlib import Path

import pytest

from catex_app.services import (
    UploadRejected,
    inspect_structure_upload,
    parse_demo_vasp_output,
)
from catex_app.workflow import (
    PortKind,
    WorkflowEdge,
    default_workflow_template,
    validate_workflow,
)

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def test_default_workflow_is_typed_and_valid() -> None:
    template = default_workflow_template()

    report = validate_workflow(template.nodes, template.edges)

    assert report.valid
    assert template.nodes[0].type_id == "structure.upload"
    assert template.nodes[-1].type_id == "results.summarize"
    assert PortKind.STRUCTURE_ARTIFACT.value == "structure_artifact"


def test_workflow_rejects_type_mismatch() -> None:
    template = default_workflow_template()
    invalid = WorkflowEdge(
        edge_id="bad-edge",
        source_node_id="node-1",
        source_port_id="structure",
        target_node_id="node-5",
        target_port_id="input",
    )

    report = validate_workflow(template.nodes, (invalid,))

    assert not report.valid
    assert "WORKFLOW_PORT_KIND_MISMATCH" in {item.code for item in report.diagnostics}


def test_structure_upload_is_ephemeral_and_inspected() -> None:
    content = (FIXTURES / "workflow" / "POSCAR").read_bytes()

    payload = inspect_structure_upload("POSCAR", content)

    assert payload["retained"] is False
    assert payload["inspection"]["status"] == "ok"
    assert payload["inspection"]["record"]["reduced_formula"] == "NaCl"
    assert payload["viewer"]["species"] == ["Na", "Cl"]


@pytest.mark.parametrize("filename", ["../POSCAR", "folder\\POSCAR", "payload.exe"])
def test_structure_upload_rejects_unsafe_or_unsupported_names(filename: str) -> None:
    with pytest.raises(UploadRejected):
        inspect_structure_upload(filename, b"not a structure")


def test_demo_vasp_output_is_never_scientifically_eligible() -> None:
    payload = parse_demo_vasp_output()

    assert payload["status"] == "normal"
    assert payload["scientifically_complete"] is True
    assert payload["demo"] == {
        "synthetic": True,
        "scientific_result_eligible": False,
        "commands_executed": False,
        "hpc_contacted": False,
    }
