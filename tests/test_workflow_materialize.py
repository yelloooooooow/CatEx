from __future__ import annotations

import json
from pathlib import Path

import pytest

from catex.workflow.materialize import materialize_calculation, plan_calculation
from catex.workflow.protocol import record_protocol_review, resolve_protocol
from catex.workflow.slurm import parse_cluster_policy, parse_execution_profile

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic" / "workflow"


def _resolved(*, approved: bool):
    resolution = resolve_protocol(
        FIXTURE / "protocol.json",
        poscar_path=FIXTURE / "POSCAR",
        potcar_metadata_path=FIXTURE / "potcar-metadata.json",
    )
    assert resolution.resolved is not None
    if not approved:
        return resolution.resolved
    return record_protocol_review(
        resolution.resolved,
        approved=True,
        reviewer="test-reviewer",
        reviewed_at_utc="2026-07-15T12:00:00Z",
        note="Synthetic fixture reviewed.",
    )


def _profile():
    return parse_execution_profile((FIXTURE / "execution-profile.json").read_text())


def _policy():
    return parse_cluster_policy((FIXTURE / "cluster-policy.json").read_text())


def _plan(destination_root: Path, *, approved: bool):
    return plan_calculation(
        poscar_path=FIXTURE / "POSCAR",
        destination_root=destination_root,
        resolved_protocol=_resolved(approved=approved),
        execution_profile=_profile(),
        cluster_policy=_policy(),
    )


def test_planning_performs_no_write_and_pending_review_blocks_materialization(tmp_path) -> None:
    plan = _plan(tmp_path, approved=False)
    destination = Path(plan.job_directory)

    assert plan.status == "review_pending"
    assert not plan.ready_for_materialization
    assert not destination.exists()
    with pytest.raises(PermissionError):
        materialize_calculation(plan)
    blocked = materialize_calculation(plan, approved_write=True)
    assert blocked.has_errors
    assert not destination.exists()


def test_approved_materialization_writes_fixed_inputs_without_potcar_or_submit(tmp_path) -> None:
    plan = _plan(tmp_path, approved=True)

    result = materialize_calculation(plan, approved_write=True)
    destination = Path(result.job_directory)

    assert result.status == "materialized_not_submitted"
    assert result.submitted is False
    assert result.potcar_materialized is False
    assert {item.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for item in result.artifacts} == {
        "POSCAR",
        "INCAR",
        "KPOINTS",
        "catex-potcar-metadata.json",
        "slurm.sh",
        "catex-manifest.json",
    }
    assert not (destination / "POTCAR").exists()
    assert "sbatch" not in (destination / "slurm.sh").read_text()
    manifest = json.loads((destination / "catex-manifest.json").read_text())
    assert manifest["potcar_required_on_hpc"] is True
    assert manifest["potcar_materialized"] is False
    assert manifest["submitted"] is False
    assert manifest["energy_family_id"] == plan.resolved_protocol.energy_family_id

    second = materialize_calculation(plan, approved_write=True)
    assert second.has_errors
    assert "MATERIALIZATION_DESTINATION_EXISTS" in {item.code for item in second.diagnostics}


def test_source_change_after_plan_is_detected_before_directory_creation(tmp_path) -> None:
    source = tmp_path / "POSCAR"
    source.write_bytes((FIXTURE / "POSCAR").read_bytes())
    resolution = resolve_protocol(
        FIXTURE / "protocol.json",
        poscar_path=source,
        potcar_metadata_path=FIXTURE / "potcar-metadata.json",
    )
    assert resolution.resolved is not None
    approved = record_protocol_review(
        resolution.resolved,
        approved=True,
        reviewer="test-reviewer",
        reviewed_at_utc="2026-07-15T12:00:00Z",
        note="Synthetic fixture reviewed.",
    )
    plan = plan_calculation(
        poscar_path=source,
        destination_root=tmp_path,
        resolved_protocol=approved,
        execution_profile=_profile(),
        cluster_policy=_policy(),
    )
    source.write_text(source.read_text() + "\n", encoding="utf-8")

    result = materialize_calculation(plan, approved_write=True)

    assert result.has_errors
    assert "MATERIALIZATION_POSCAR_CHANGED" in {item.code for item in result.diagnostics}
    assert not Path(plan.job_directory).exists()
