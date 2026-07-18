from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from pymatgen.core import Structure

from catex.hashing import artifact_record
from catex.materials_studio import (
    ManualReviewState,
    MaterialsStudioPathPolicy,
    audit_materials_studio_roundtrip,
    detect_materials_studio_capability,
    execute_materials_studio_roundtrip,
    plan_materials_studio_roundtrip,
)

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic" / "materials_studio" / "nacl_input.cif"


def _configured(tmp_path: Path):
    input_root = tmp_path / "inputs"
    staging_root = tmp_path / "staging"
    input_root.mkdir()
    staging_root.mkdir()
    source = input_root / "source.cif"
    shutil.copyfile(FIXTURE, source)
    runner = tmp_path / "RunMatScript.bat"
    runner.write_text("@echo off\n", encoding="utf-8")
    policy = MaterialsStudioPathPolicy((input_root,), staging_root)
    return source, staging_root, runner, policy


def test_capability_is_read_only_and_never_offers_arbitrary_script(tmp_path: Path) -> None:
    runner = tmp_path / "RunMatScript.bat"
    runner.write_text("@echo off\n", encoding="utf-8")

    report = detect_materials_studio_capability(runner)
    payload = report.to_dict()

    assert report.status == "available_unverified"
    assert report.runner_available is True
    assert report.license_status == "unknown"
    assert report.execution_status == "not_tested"
    assert report.arbitrary_script_supported is False
    assert payload["supported_operations"] == ["roundtrip_cif_via_xsd"]
    assert payload["template_artifact"]["sha256"]
    assert "MS_LICENSE_UNVERIFIED" in {item.code for item in report.diagnostics}


@pytest.mark.parametrize("name", ["missing.bat", "runner.exe"])
def test_capability_rejects_missing_or_wrong_runner(tmp_path: Path, name: str) -> None:
    runner = tmp_path / name
    if name.endswith(".exe"):
        runner.write_bytes(b"not an executable")

    report = detect_materials_studio_capability(runner)

    assert report.status == "unavailable"
    assert report.has_errors is True
    assert report.runner_artifact is None


def test_path_policy_and_plan_fix_all_outputs(tmp_path: Path) -> None:
    source, staging, runner, policy = _configured(tmp_path)

    plan = plan_materials_studio_roundtrip(
        source,
        policy=policy,
        runner_path=runner,
        job_name="roundtrip-001",
    )
    payload = plan.to_dict()

    assert Path(plan.job_directory).parent == staging.resolve()
    assert Path(plan.intermediate_xsd_path).name == "roundtrip.xsd"
    assert Path(plan.exported_cif_path).name == "roundtrip.cif"
    assert payload["arbitrary_script"] is False
    assert payload["fixed_output_names"] == ["roundtrip.xsd", "roundtrip.cif"]
    assert len(plan.input_artifact.sha256) == 64


def test_path_policy_rejects_escape_extension_metacharacter_and_existing_job(
    tmp_path: Path,
) -> None:
    source, staging, runner, policy = _configured(tmp_path)
    outside = tmp_path / "outside.cif"
    shutil.copyfile(source, outside)
    wrong_extension = source.with_suffix(".xsd")
    shutil.copyfile(source, wrong_extension)
    unsafe = source.parent / "unsafe%name.cif"
    shutil.copyfile(source, unsafe)

    with pytest.raises(ValueError, match="outside"):
        policy.resolve_input(outside)
    with pytest.raises(ValueError, match="CIF"):
        policy.resolve_input(wrong_extension)
    with pytest.raises(ValueError, match="metacharacter"):
        policy.resolve_input(unsafe)
    with pytest.raises(ValueError, match="job name"):
        policy.resolve_job_directory("../escape")

    (staging / "already-there").mkdir()
    with pytest.raises(ValueError, match="already exists"):
        plan_materials_studio_roundtrip(
            source,
            policy=policy,
            runner_path=runner,
            job_name="already-there",
        )


def test_execution_requires_explicit_approval(tmp_path: Path) -> None:
    source, _, runner, policy = _configured(tmp_path)
    plan = plan_materials_studio_roundtrip(
        source, policy=policy, runner_path=runner, job_name="approval"
    )

    with pytest.raises(PermissionError, match="explicit"):
        execute_materials_studio_roundtrip(plan, approved=False)
    with pytest.raises(ValueError, match="positive"):
        execute_materials_studio_roundtrip(plan, approved=True, timeout_seconds=0)
    assert not Path(plan.job_directory).exists()


def test_fixed_execution_and_audit_require_human_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _, runner, policy = _configured(tmp_path)
    plan = plan_materials_studio_roundtrip(
        source, policy=policy, runner_path=runner, job_name="success"
    )

    def fake_run(command, **kwargs):
        assert command[0]
        assert kwargs["cwd"] == Path(plan.job_directory)
        assert command[1] == "catex_ms_roundtrip"
        assert (Path(plan.job_directory) / "catex_ms_roundtrip.pl").is_file()
        Path(plan.intermediate_xsd_path).write_text("synthetic xsd", encoding="utf-8")
        structure = Structure.from_file(source)
        reordered = Structure.from_sites(list(reversed(structure.sites)))
        reordered.to(filename=plan.exported_cif_path, fmt="cif")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    execution = execute_materials_studio_roundtrip(plan, approved=True)
    pending = audit_materials_studio_roundtrip(plan, execution)
    approved = audit_materials_studio_roundtrip(
        plan,
        execution,
        manual_review_state=ManualReviewState.APPROVED,
    )

    assert execution.succeeded is True
    assert pending.status == "review_required"
    assert pending.ready_for_downstream is False
    assert "MS_MANUAL_REVIEW_REQUIRED" in {item.code for item in pending.diagnostics}
    assert approved.status == "approved"
    assert approved.ready_for_downstream is True
    assert approved.comparison is not None and approved.comparison.equivalent
    assert approved.source_to_exported_site_mapping is not None
    assert sorted(approved.source_to_exported_site_mapping) == [0, 1]
    assert approved.transformation is not None
    assert approved.transformation.input_hashes == (plan.input_artifact.sha256,)
    assert len(approved.output_artifacts) == 2
    assert approved.to_dict()["ready_for_downstream"] is True


def test_changed_input_blocks_execution_before_writing(tmp_path: Path) -> None:
    source, _, runner, policy = _configured(tmp_path)
    plan = plan_materials_studio_roundtrip(
        source, policy=policy, runner_path=runner, job_name="changed"
    )
    source.write_text(source.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")

    execution = execute_materials_studio_roundtrip(plan, approved=True)

    assert execution.succeeded is False
    assert execution.return_code is None
    assert not Path(plan.job_directory).exists()
    assert "MS_ARTIFACT_CHANGED" in {item.code for item in execution.diagnostics}


def test_forged_template_plan_cannot_create_arbitrary_script_interface(tmp_path: Path) -> None:
    source, _, runner, policy = _configured(tmp_path)
    plan = plan_materials_studio_roundtrip(
        source, policy=policy, runner_path=runner, job_name="forged"
    )
    unregistered = tmp_path / "arbitrary.pl"
    unregistered.write_text("die 'arbitrary';\n", encoding="utf-8")
    forged = replace(plan, template_artifact=artifact_record(unregistered))

    execution = execute_materials_studio_roundtrip(forged, approved=True)

    assert execution.succeeded is False
    assert not Path(plan.job_directory).exists()
    assert "MS_TEMPLATE_NOT_REGISTERED" in {item.code for item in execution.diagnostics}


@pytest.mark.parametrize("mode", ["nonzero", "missing", "timeout", "oserror"])
def test_execution_failures_are_structured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    source, _, runner, policy = _configured(tmp_path)
    plan = plan_materials_studio_roundtrip(
        source, policy=policy, runner_path=runner, job_name=f"failure-{mode}"
    )

    def fake_run(command, **kwargs):
        if mode == "nonzero":
            return subprocess.CompletedProcess(command, 7)
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if mode == "oserror":
            raise OSError("cannot start")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    execution = execute_materials_studio_roundtrip(plan, approved=True)

    assert execution.succeeded is False
    assert execution.to_dict()["succeeded"] is False
    assert any(item.severity.value == "error" for item in execution.diagnostics)


def test_non_equivalent_and_rejected_output_cannot_pass_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _, runner, policy = _configured(tmp_path)
    plan = plan_materials_studio_roundtrip(
        source, policy=policy, runner_path=runner, job_name="rejected"
    )

    def fake_run(command, **kwargs):
        Path(plan.intermediate_xsd_path).write_text("synthetic xsd", encoding="utf-8")
        changed = Structure.from_file(source)
        changed.replace(0, "K")
        changed.to(filename=plan.exported_cif_path, fmt="cif")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    execution = execute_materials_studio_roundtrip(plan, approved=True)
    report = audit_materials_studio_roundtrip(
        plan,
        execution,
        manual_review_state="rejected",
    )

    assert report.status == "error"
    assert report.ready_for_downstream is False
    assert report.source_to_exported_site_mapping is None
    assert report.transformation is None
    codes = {item.code for item in report.diagnostics}
    assert "MS_ROUNDTRIP_NOT_EQUIVALENT" in codes
    assert "MS_MANUAL_REVIEW_REJECTED" in codes


def test_audit_without_successful_execution_is_error(tmp_path: Path) -> None:
    source, _, runner, policy = _configured(tmp_path)
    plan = plan_materials_studio_roundtrip(
        source, policy=policy, runner_path=runner, job_name="not-run"
    )

    report = audit_materials_studio_roundtrip(plan, None)

    assert report.status == "error"
    assert report.execution is None
    assert report.comparison is None
    assert "MS_EXECUTION_NOT_SUCCEEDED" in {item.code for item in report.diagnostics}
