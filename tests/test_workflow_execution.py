from __future__ import annotations

from catex_app.workflow import workflow_template_catalog
from catex_app.workflow_execution import compile_workflow_execution_plan


def _template(template_id: str) -> dict[str, object]:
    template = next(item for item in workflow_template_catalog() if item.template_id == template_id)
    return {
        "nodes": [item.to_dict() for item in template.nodes],
        "edges": [item.to_dict() for item in template.edges],
    }


def test_compile_relax_frequency_workflow_preserves_stage_dependencies() -> None:
    plan = compile_workflow_execution_plan(_template("vasp-relax-frequency"))

    assert [stage["calculation_type"] for stage in plan["stages"]] == [
        "relax",
        "static",
        "frequency",
    ]
    assert plan["stages"][0]["incar_overrides"]["IBRION"] == 2
    assert plan["stages"][1]["depends_on"] == [plan["stages"][0]["stage_id"]]
    assert plan["stages"][2]["depends_on"] == [plan["stages"][1]["stage_id"]]
    assert "vibrational-modes.json" in plan["stages"][2]["produced_outputs"]
    assert plan["commands_executed"] is False


def test_compile_chgnet_workflow_separates_local_and_hpc_backends() -> None:
    plan = compile_workflow_execution_plan(_template("chgnet-vasp-relax-static"))

    assert plan["stages"][0]["execution_backend"] == "local_chgnet"
    assert plan["stages"][1]["execution_backend"] == "project_hpc_profile"
    assert plan["automatic_scientific_parameter_changes"] is False
