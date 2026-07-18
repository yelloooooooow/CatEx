from __future__ import annotations

from pathlib import Path

import pytest

from catex_app.calculations import CalculationServiceError, CalculationWorkspaceService
from catex_app.projects import ProjectStore


def _workspace(tmp_path: Path):
    store = ProjectStore(tmp_path / "data")
    service = CalculationWorkspaceService(store)
    project = store.create_project(title="NaCl calculation", purpose="training")
    poscar = Path(__file__).parent / "fixtures" / "synthetic" / "workflow" / "POSCAR"
    artifact = store.add_structure(project["project_id"], "POSCAR", poscar.read_bytes())
    store.record_structure_review(
        project["project_id"],
        artifact["artifact_id"],
        approved=True,
        reviewer="structure-reviewer",
        note="Synthetic structure approved for workflow testing.",
    )
    return store, service, project, artifact


def test_protocol_plan_review_and_local_materialization(tmp_path: Path) -> None:
    store, service, project, artifact = _workspace(tmp_path)
    saved = service.save_bundle(project["project_id"], service.default_bundle())
    pending = service.plan(project["project_id"], artifact["artifact_id"])

    assert saved["saved"] is True
    assert pending["resolution"]["status"] == "review_pending"
    assert pending["plan"]["ready_for_materialization"] is False
    assert pending["submitted"] is False
    assert pending["plan"]["slurm"]["submitted"] is False

    review = service.approve_protocol(
        project["project_id"],
        artifact["artifact_id"],
        reviewer="local-reviewer",
        note="Synthetic protocol checked",
    )
    approved = service.plan(project["project_id"], artifact["artifact_id"])
    plan_sha256 = approved["plan"]["plan_sha256"]
    materialized = service.materialize(
        project["project_id"],
        artifact["artifact_id"],
        confirm_plan_sha256=plan_sha256,
        approved_write=True,
    )

    run = store.project_directory(project["project_id"]) / "runs" / "nacl-static-001"
    assert review["approved"] is True
    assert approved["plan"]["ready_for_materialization"] is True
    assert materialized["materialization"]["status"] == "materialized_not_submitted"
    assert (run / "POSCAR").is_file()
    assert (run / "INCAR").is_file()
    assert (run / "KPOINTS").is_file()
    assert (run / "slurm.sh").is_file()
    assert not (run / "POTCAR").exists()
    assert store.get_project(project["project_id"])["run_count"] == 1


def test_materialization_requires_current_plan_digest_and_explicit_write(tmp_path: Path) -> None:
    _, service, project, artifact = _workspace(tmp_path)
    service.save_bundle(project["project_id"], service.default_bundle())
    service.approve_protocol(
        project["project_id"],
        artifact["artifact_id"],
        reviewer="reviewer",
        note="approved",
    )

    with pytest.raises(PermissionError, match="approved_write"):
        service.materialize(
            project["project_id"],
            artifact["artifact_id"],
            confirm_plan_sha256="0" * 64,
            approved_write=False,
        )
    with pytest.raises(CalculationServiceError, match="digest"):
        service.materialize(
            project["project_id"],
            artifact["artifact_id"],
            confirm_plan_sha256="0" * 64,
            approved_write=True,
        )


def test_calculation_planning_uses_automatic_structure_diagnostics(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")
    service = CalculationWorkspaceService(store)
    project = store.create_project(title="Review gate", purpose="training")
    poscar = Path(__file__).parent / "fixtures" / "synthetic" / "workflow" / "POSCAR"
    artifact = store.add_structure(project["project_id"], "POSCAR", poscar.read_bytes())
    service.save_bundle(project["project_id"], service.default_bundle())

    plan = service.plan(project["project_id"], artifact["artifact_id"])

    assert plan["resolution"]["resolved"] is not None
    assert plan["plan"] is not None
    assert plan["plan"]["status"] == "review_pending"
