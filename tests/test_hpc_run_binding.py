from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from catex.cli import main
from catex.hpc import (
    RunBindingStatus,
    parse_submission_receipt,
    parse_submission_receipt_path,
    validate_run_binding,
)
from catex.results import (
    ScientificResultDecision,
    record_scientific_result_review,
)

VASP_FIXTURES = Path(__file__).parent / "fixtures" / "synthetic" / "vasp_output"
OBSERVED_AT = "2026-07-15T12:34:56Z"
JOB_ID = "12345"
PLAN_SHA256 = "a" * 64
RAW_SUBMISSION_SHA256 = hashlib.sha256(f"{JOB_ID}\n".encode()).hexdigest()
SUBMISSION_TEMPLATE = (
    "sbatch --chdir=<authorized-job-directory> --parsable <authorized-job-directory>/slurm.sh"
)


def _receipt(
    *,
    directory_name: str = "calc-001",
    job_name: str = "calc-001",
    plan_sha256: str = PLAN_SHA256,
    script_sha256: str,
    scientific_result_eligible: bool = True,
) -> dict[str, object]:
    return {
        "schema_version": "catex.submission-receipt.v1",
        "submitted_at_utc": "2026-07-15T12:30:00Z",
        "job_id": JOB_ID,
        "job_directory_name": directory_name,
        "job_name": job_name,
        "plan_sha256": plan_sha256,
        "slurm_script_sha256": script_sha256,
        "submission_command_template": SUBMISSION_TEMPLATE,
        "raw_submission_output_sha256": RAW_SUBMISSION_SHA256,
        "submission_performed": True,
        "approved_scope": "authorized-test-root-only",
        "scientific_result_eligible": scientific_result_eligible,
        "overwrite_performed": False,
        "deletion_performed": False,
    }


def _bound_run(
    tmp_path: Path,
    *,
    fixture_name: str = "normal",
    scientific_result_eligible: bool = True,
) -> tuple[Path, Path, Path]:
    directory = tmp_path / "calc-001"
    directory.mkdir()
    for source in (VASP_FIXTURES / fixture_name).iterdir():
        (directory / source.name).write_bytes(source.read_bytes())
    script = "#!/bin/bash -l\nsrun --mpi=pmi2 /approved/vasp_std\n"
    script_sha256 = hashlib.sha256(script.encode()).hexdigest()
    (directory / "slurm.sh").write_bytes(script.encode())
    manifest = {
        "schema_version": "catex.materialization-manifest.v1",
        "job_name": "calc-001",
        "plan_sha256": PLAN_SHA256,
        "poscar_sha256": "b" * 64,
        "resolved_protocol_sha256": "c" * 64,
        "energy_family_id": f"sha256:{'d' * 64}",
        "protocol_review": {
            "schema_version": "catex.protocol-review.v1",
            "state": "approved",
            "reviewer": "synthetic-reviewer",
            "reviewed_at_utc": "2026-07-15T12:00:00Z",
            "note": "Synthetic fixture only.",
        },
        "execution_profile_id": "profile-001",
        "cluster_policy_id": "policy-001",
        "slurm_script_sha256": script_sha256,
        "potcar_required_on_hpc": True,
        "potcar_materialized": True,
        "submitted": False,
    }
    (directory / "catex-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    receipt = tmp_path / "submission-receipt.json"
    receipt.write_text(
        json.dumps(
            _receipt(
                script_sha256=script_sha256,
                scientific_result_eligible=scientific_result_eligible,
            )
        ),
        encoding="utf-8",
    )
    snapshot = tmp_path / "sacct.txt"
    snapshot.write_text(f"{JOB_ID}|COMPLETED|0:0|41\n", encoding="utf-8")
    return directory, receipt, snapshot


def _validate(directory: Path, receipt: Path, snapshot: Path, *, source: str = "sacct"):
    return validate_run_binding(
        directory,
        submission_receipt_path=receipt,
        slurm_snapshot_path=snapshot,
        source=source,
        observed_at_utc=OBSERVED_AT,
    )


def test_submission_receipt_is_strict_hashed_and_path_sanitized() -> None:
    payload = _receipt(script_sha256="e" * 64)
    content = json.dumps(payload)

    report = parse_submission_receipt(
        content,
        source_name="/private/cluster/submission-receipt.json",
    )
    serialized = json.dumps(report.to_dict())

    assert report.status == "validated"
    assert report.source_name == "submission-receipt.json"
    assert report.source_sha256 == hashlib.sha256(content.encode()).hexdigest()
    assert report.receipt is not None
    assert report.receipt.submission_performed is True
    assert report.receipt.scientific_result_eligible is True
    assert report.raw_content_included is False
    assert report.raw_submission_output_included is False
    assert report.writes_performed is False
    assert report.commands_executed is False
    assert "/private/cluster" not in serialized
    assert content not in serialized


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ({"unexpected": True}, "SUBMISSION_RECEIPT_SCHEMA_INVALID"),
        ({"plan_sha256": "bad"}, "SUBMISSION_RECEIPT_VALUE_INVALID"),
        ({"submission_command_template": "sbatch slurm.sh"}, "SUBMISSION_RECEIPT_VALUE_INVALID"),
        ({"scientific_result_eligible": 1}, "SUBMISSION_RECEIPT_VALUE_INVALID"),
        ({"overwrite_performed": True}, "SUBMISSION_RECEIPT_VALUE_INVALID"),
        ({"deletion_performed": True}, "SUBMISSION_RECEIPT_VALUE_INVALID"),
        ({"submitted_at_utc": "2026-02-30T00:00:00Z"}, "SUBMISSION_RECEIPT_VALUE_INVALID"),
    ],
)
def test_submission_receipt_fails_closed_on_schema_or_value_changes(
    mutation: dict[str, object], expected_code: str
) -> None:
    payload = _receipt(script_sha256="e" * 64)
    payload.update(mutation)

    report = parse_submission_receipt(json.dumps(payload))

    assert report.has_errors
    assert report.receipt is None
    assert {item.code for item in report.diagnostics} == {expected_code}


def test_submission_receipt_path_read_is_bounded_and_encoding_checked(tmp_path: Path) -> None:
    large = tmp_path / "large.json"
    large.write_bytes(b"x" * (64 * 1024 + 1))
    invalid = parse_submission_receipt(b"\xff")
    missing = parse_submission_receipt_path(tmp_path / "missing.json")
    large_report = parse_submission_receipt_path(large)

    assert {item.code for item in invalid.diagnostics} == {"SUBMISSION_RECEIPT_ENCODING_INVALID"}
    assert {item.code for item in missing.diagnostics} == {"SUBMISSION_RECEIPT_READ_FAILED"}
    assert {item.code for item in large_report.diagnostics} == {"SUBMISSION_RECEIPT_TOO_LARGE"}
    assert large_report.source_sha256 == hashlib.sha256(large.read_bytes()).hexdigest()


def test_completed_bound_run_stops_at_scientific_review_without_mutation(
    tmp_path: Path,
) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    before = {item.name: item.read_bytes() for item in directory.iterdir()}

    report = _validate(directory, receipt, snapshot)
    serialized = json.dumps(report.to_dict())
    after = {item.name: item.read_bytes() for item in directory.iterdir()}

    assert report.status is RunBindingStatus.SCIENTIFIC_REVIEW_REQUIRED
    assert report.binding_valid is True
    assert report.scheduler_success is True
    assert report.ready_for_scientific_review is True
    assert report.scientific_result_accepted is False
    assert report.additional_submission_performed is False
    assert report.writes_performed is False
    assert report.commands_executed is False
    assert report.required_reviews[-1] == "accept_or_reject_scientific_result"
    assert report.protocol_identity is not None
    assert report.protocol_identity.plan_sha256 == PLAN_SHA256
    assert report.protocol_identity.energy_family_id == f"sha256:{'d' * 64}"
    assert str(tmp_path) not in serialized
    assert before == after


def test_tampered_slurm_script_breaks_manifest_and_receipt_binding(tmp_path: Path) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    (directory / "slurm.sh").write_bytes(b"#!/bin/bash\nexit 1\n")

    report = _validate(directory, receipt, snapshot)

    assert report.status is RunBindingStatus.ERROR
    assert report.binding_valid is False
    assert {item.code for item in report.diagnostics} >= {"RUN_BINDING_SCRIPT_ARTIFACT_MISMATCH"}


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("plan_sha256", "f" * 64, "RUN_BINDING_PLAN_HASH_MISMATCH"),
        ("job_directory_name", "another-run", "RUN_BINDING_DIRECTORY_MISMATCH"),
        ("job_name", "another-job", "RUN_BINDING_JOB_NAME_MISMATCH"),
    ],
)
def test_receipt_must_match_manifest_and_directory(
    tmp_path: Path,
    field: str,
    value: str,
    expected_code: str,
) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload[field] = value
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    report = _validate(directory, receipt, snapshot)

    assert report.status is RunBindingStatus.ERROR
    assert expected_code in {item.code for item in report.diagnostics}


def test_scheduler_snapshot_must_contain_the_receipt_job(tmp_path: Path) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    snapshot.write_text("99999|COMPLETED|0:0|41\n", encoding="utf-8")

    report = _validate(directory, receipt, snapshot)

    assert report.status is RunBindingStatus.ERROR
    assert "SLURM_JOB_NOT_FOUND_IN_SNAPSHOT" in {item.code for item in report.diagnostics}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("submitted", True),
        ("energy_family_id", "invalid"),
        ("protocol_review", {"state": "pending"}),
    ],
)
def test_manifest_must_remain_a_valid_approved_pre_submission_record(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    manifest_path = directory / "catex-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = _validate(directory, receipt, snapshot)

    assert report.status is RunBindingStatus.ERROR
    assert "RUN_BINDING_MANIFEST_INVALID" in {item.code for item in report.diagnostics}


def test_active_bound_run_waits_for_same_job_without_submission(tmp_path: Path) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    snapshot.write_text(f"{JOB_ID}|RUNNING|00:10\n", encoding="utf-8")

    report = _validate(directory, receipt, snapshot, source="squeue")

    assert report.status is RunBindingStatus.ACTIVE
    assert report.binding_valid is True
    assert report.scheduler_success is False
    assert report.ready_for_scientific_review is False
    assert report.additional_submission_performed is False


def test_bound_but_unconverged_run_requires_terminal_review(tmp_path: Path) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path, fixture_name="unconverged")

    report = _validate(directory, receipt, snapshot)

    assert report.status is RunBindingStatus.TERMINAL_REVIEW_REQUIRED
    assert report.binding_valid is True
    assert report.scheduler_success is True
    assert report.ready_for_scientific_review is False
    assert report.scientific_result_accepted is False


def test_submission_declared_ineligible_can_never_be_scientifically_accepted(
    tmp_path: Path,
) -> None:
    directory, receipt, snapshot = _bound_run(
        tmp_path,
        scientific_result_eligible=False,
    )

    binding = _validate(directory, receipt, snapshot)

    assert binding.status is RunBindingStatus.TERMINAL_REVIEW_REQUIRED
    assert binding.binding_valid is True
    assert binding.scheduler_success is True
    assert binding.vasp.scientifically_complete is True
    assert binding.ready_for_scientific_review is False
    assert "RUN_DECLARED_SCIENTIFICALLY_INELIGIBLE" in {item.code for item in binding.diagnostics}
    with pytest.raises(ValueError, match="acceptance requires"):
        record_scientific_result_review(
            binding,
            accepted=True,
            reviewer="synthetic-scientist",
            reviewed_at_utc="2026-07-15T13:00:00Z",
            note="A smoke run must remain ineligible.",
        )
    rejected = record_scientific_result_review(
        binding,
        accepted=False,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="Submission receipt excludes scientific use.",
    )
    assert rejected.scientific_result_accepted is False
    assert rejected.submission_scientific_result_eligible is False


def test_validate_run_binding_cli_emits_json_and_text(tmp_path: Path, capsys) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    arguments = [
        "validate-run-binding",
        str(directory),
        "--submission-receipt",
        str(receipt),
        "--slurm-snapshot",
        str(snapshot),
        "--source",
        "sacct",
        "--observed-at-utc",
        OBSERVED_AT,
    ]

    json_exit = main([*arguments, "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    text_exit = main(arguments)
    rendered = capsys.readouterr().out

    assert json_exit == 0
    assert payload["schema_version"] == "catex.run-binding.v1"
    assert payload["status"] == "scientific_review_required"
    assert payload["scientific_result_accepted"] is False
    assert text_exit == 0
    assert "binding_valid: true" in rendered
    assert "scientific_result_accepted: false" in rendered


def test_explicit_review_accepts_only_ready_bound_result_without_mutation(
    tmp_path: Path,
) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    binding = _validate(directory, receipt, snapshot)
    before = {item.name: item.read_bytes() for item in directory.iterdir()}

    review = record_scientific_result_review(
        binding,
        accepted=True,
        reviewer="  synthetic-scientist  ",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="  Energy, forces, magnetization, and protocol reviewed.  ",
    )
    repeated = record_scientific_result_review(
        binding,
        accepted=True,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="Energy, forces, magnetization, and protocol reviewed.",
    )
    serialized = json.dumps(review.to_dict())
    after = {item.name: item.read_bytes() for item in directory.iterdir()}

    assert review.decision is ScientificResultDecision.ACCEPTED
    assert review.scientific_result_accepted is True
    assert review.submission_scientific_result_eligible is True
    assert review.eligible_for_same_energy_family_derivation is True
    assert review.human_review_recorded is True
    assert review.automatic_acceptance_performed is False
    assert review.writes_performed is False
    assert review.commands_executed is False
    assert review.additional_submission_performed is False
    assert review.binding_identity_sha256 == repeated.binding_identity_sha256
    assert review.review_sha256 == repeated.review_sha256
    assert binding.scientific_result_accepted is False
    assert str(tmp_path) not in serialized
    assert before == after


def test_invalid_binding_cannot_receive_even_a_rejection() -> None:
    binding_directory = VASP_FIXTURES / "normal"
    with pytest.raises(ValueError, match="complete, valid run binding"):
        record_scientific_result_review(
            validate_run_binding(
                binding_directory,
                submission_receipt_path=binding_directory / "missing-receipt.json",
                slurm_snapshot_path=binding_directory / "missing-snapshot.txt",
                source="sacct",
                observed_at_utc=OBSERVED_AT,
            ),
            accepted=False,
            reviewer="synthetic-scientist",
            reviewed_at_utc="2026-07-15T13:00:00Z",
            note="Evidence identity is incomplete.",
        )


def test_ready_bound_result_can_be_explicitly_rejected(tmp_path: Path) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    binding = _validate(directory, receipt, snapshot)

    review = record_scientific_result_review(
        binding,
        accepted=False,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="Scientifically complete, but rejected after manual inspection.",
    )

    assert review.decision is ScientificResultDecision.REJECTED
    assert review.scientific_result_accepted is False
    assert review.eligible_for_same_energy_family_derivation is False


def test_unconverged_bound_result_can_only_be_rejected(tmp_path: Path) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path, fixture_name="unconverged")
    binding = _validate(directory, receipt, snapshot)

    with pytest.raises(ValueError, match="acceptance requires"):
        record_scientific_result_review(
            binding,
            accepted=True,
            reviewer="synthetic-scientist",
            reviewed_at_utc="2026-07-15T13:00:00Z",
            note="This must not be accepted.",
        )
    rejected = record_scientific_result_review(
        binding,
        accepted=False,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="Electronic convergence is incomplete.",
    )

    assert rejected.decision is ScientificResultDecision.REJECTED
    assert rejected.scientific_result_accepted is False
    assert rejected.submission_scientific_result_eligible is True
    assert rejected.eligible_for_same_energy_family_derivation is False


def test_active_bound_result_cannot_receive_scientific_review(tmp_path: Path) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    snapshot.write_text(f"{JOB_ID}|RUNNING|00:10\n", encoding="utf-8")
    binding = _validate(directory, receipt, snapshot, source="squeue")

    with pytest.raises(ValueError, match="terminal bound run"):
        record_scientific_result_review(
            binding,
            accepted=False,
            reviewer="synthetic-scientist",
            reviewed_at_utc="2026-07-15T13:00:00Z",
            note="The job is still active.",
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"accepted": 1}, "accepted must be a boolean"),
        ({"reviewer": ""}, "reviewer must be"),
        ({"reviewer": "bad\nreviewer"}, "reviewer must be one line"),
        ({"reviewer": "reviewer\n"}, "reviewer must be one line"),
        ({"reviewer": "x" * 101}, "reviewer must be"),
        ({"note": ""}, "note must be"),
        ({"note": "bad\nnote"}, "note must be one line"),
        ({"note": "x" * 501}, "note must be"),
        ({"reviewed_at_utc": "not-a-time"}, "reviewed_at_utc must use"),
        ({"reviewed_at_utc": "2026-7-15T13:00:00Z"}, "reviewed_at_utc must use"),
        (
            {"reviewed_at_utc": "2026-07-15T12:00:00Z"},
            "cannot precede the scheduler observation",
        ),
    ],
)
def test_scientific_review_metadata_is_strict_and_causal(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    binding = _validate(directory, receipt, snapshot)
    arguments: dict[str, object] = {
        "accepted": True,
        "reviewer": "synthetic-scientist",
        "reviewed_at_utc": "2026-07-15T13:00:00Z",
        "note": "Synthetic review.",
    }
    arguments.update(overrides)

    with pytest.raises(ValueError, match=message):
        record_scientific_result_review(binding, **arguments)  # type: ignore[arg-type]


def test_binding_and_review_hashes_change_when_vasp_artifact_bytes_change(
    tmp_path: Path,
) -> None:
    first_parent = tmp_path / "first"
    second_parent = tmp_path / "second"
    first_parent.mkdir()
    second_parent.mkdir()
    first_directory, first_receipt, first_snapshot = _bound_run(first_parent)
    second_directory, second_receipt, second_snapshot = _bound_run(second_parent)
    with (second_directory / "OSZICAR").open("ab") as stream:
        stream.write(b"\n")
    first_binding = _validate(first_directory, first_receipt, first_snapshot)
    second_binding = _validate(second_directory, second_receipt, second_snapshot)

    first_review = record_scientific_result_review(
        first_binding,
        accepted=True,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="Synthetic review.",
    )
    second_review = record_scientific_result_review(
        second_binding,
        accepted=True,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="Synthetic review.",
    )

    assert first_review.binding_identity_sha256 != second_review.binding_identity_sha256
    assert first_review.review_sha256 != second_review.review_sha256


def test_review_identity_binds_submission_scientific_eligibility(tmp_path: Path) -> None:
    eligible_parent = tmp_path / "eligible"
    ineligible_parent = tmp_path / "ineligible"
    eligible_parent.mkdir()
    ineligible_parent.mkdir()
    eligible_directory, eligible_receipt, eligible_snapshot = _bound_run(eligible_parent)
    ineligible_directory, ineligible_receipt, ineligible_snapshot = _bound_run(
        ineligible_parent,
        scientific_result_eligible=False,
    )
    eligible_binding = _validate(eligible_directory, eligible_receipt, eligible_snapshot)
    ineligible_binding = _validate(
        ineligible_directory,
        ineligible_receipt,
        ineligible_snapshot,
    )

    eligible_review = record_scientific_result_review(
        eligible_binding,
        accepted=False,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="Synthetic rejection.",
    )
    ineligible_review = record_scientific_result_review(
        ineligible_binding,
        accepted=False,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="Synthetic rejection.",
    )

    assert eligible_review.binding_identity_sha256 != ineligible_review.binding_identity_sha256
    assert eligible_review.review_sha256 != ineligible_review.review_sha256
