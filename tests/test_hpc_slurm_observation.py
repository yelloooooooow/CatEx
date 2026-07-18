from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from catex.cli import main
from catex.hpc import (
    FailureCategory,
    RestartDecision,
    SlurmJobState,
    assess_restart,
    parse_slurm_snapshot,
    parse_slurm_snapshot_path,
)

VASP_FIXTURES = Path(__file__).parent / "fixtures" / "synthetic" / "vasp_output"
OBSERVED_AT = "2026-07-15T12:34:56Z"


def _sacct(
    state: str,
    *,
    exit_code: str = "0:0",
    elapsed: int = 120,
    job_id: str = "12345",
):
    return parse_slurm_snapshot(
        f"JobIDRaw|State|ExitCode|ElapsedRaw\n{job_id}|{state}|{exit_code}|{elapsed}\n",
        source="sacct",
        job_id=job_id,
        observed_at_utc=OBSERVED_AT,
        source_name="snapshot.txt",
    )


def test_sacct_snapshot_is_exact_hashed_sanitized_and_typed() -> None:
    content = "JobIDRaw|State|ExitCode|ElapsedRaw\n12345|COMPLETED|0:0|120\n"

    report = parse_slurm_snapshot(
        content,
        source="sacct",
        job_id="12345",
        observed_at_utc=OBSERVED_AT,
        source_name="/private/cluster/accounting.txt",
    )
    payload = report.to_dict()

    assert report.status == "observed"
    assert report.source_name == "accounting.txt"
    assert report.source_sha256 == hashlib.sha256(content.encode()).hexdigest()
    assert report.source_size_bytes == len(content.encode())
    assert report.raw_content_included is False
    assert report.commands_executed is False
    assert report.observation is not None
    assert report.observation.state is SlurmJobState.COMPLETED
    assert report.observation.exit_code == 0
    assert report.observation.terminating_signal == 0
    assert report.observation.elapsed_seconds == 120
    assert "/private/cluster" not in json.dumps(payload)
    assert content not in json.dumps(payload)


def test_squeue_active_snapshot_ignores_unrelated_rows_without_retaining_them() -> None:
    content = "JobID|State|TimeUsed\n111|RUNNING|00:09\n222|PENDING|00:00\n"

    report = parse_slurm_snapshot(
        content,
        source="squeue",
        job_id="222",
        observed_at_utc=OBSERVED_AT,
    )

    assert report.status == "observed"
    assert report.observation is not None
    assert report.observation.state is SlurmJobState.PENDING
    assert report.observation.exit_code is None
    finding = next(
        item for item in report.diagnostics if item.code == "SLURM_UNRELATED_ROWS_IGNORED"
    )
    assert finding.context["count"] == 1
    assert "111" not in json.dumps(report.to_dict())


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("", "SLURM_JOB_NOT_FOUND_IN_SNAPSHOT"),
        ("12345|RUNNING\n", "SLURM_SNAPSHOT_COLUMN_COUNT_INVALID"),
        ("12345|RUNNING|x\n", "SLURM_ELAPSED_RAW_INVALID"),
        ("12345|FUTURE_STATE|00:00\n", "SLURM_STATE_NOT_SUPPORTED"),
        ("12345|RUNNING|00:00\n12345|RUNNING|00:01\n", "SLURM_JOB_ROW_AMBIGUOUS"),
    ],
)
def test_malformed_or_ambiguous_snapshots_fail_closed(content: str, code: str) -> None:
    report = parse_slurm_snapshot(
        content,
        source="squeue",
        job_id="12345",
        observed_at_utc=OBSERVED_AT,
    )

    assert report.has_errors
    assert code in {item.code for item in report.diagnostics}


def test_snapshot_size_encoding_identifiers_and_timestamp_are_bounded(tmp_path: Path) -> None:
    large = b"x" * (1024 * 1024 + 1)
    report = parse_slurm_snapshot(
        large,
        source="squeue",
        job_id="12345",
        observed_at_utc=OBSERVED_AT,
    )
    encoded = parse_slurm_snapshot(
        b"\xff",
        source="squeue",
        job_id="12345",
        observed_at_utc=OBSERVED_AT,
    )
    large_path = tmp_path / "large-snapshot.txt"
    large_path.write_bytes(large)
    path_report = parse_slurm_snapshot_path(
        large_path,
        source="squeue",
        job_id="12345",
        observed_at_utc=OBSERVED_AT,
    )

    assert {item.code for item in report.diagnostics} == {"SLURM_SNAPSHOT_TOO_LARGE"}
    assert {item.code for item in encoded.diagnostics} == {"SLURM_SNAPSHOT_ENCODING_INVALID"}
    assert {item.code for item in path_report.diagnostics} == {"SLURM_SNAPSHOT_TOO_LARGE"}
    assert path_report.source_sha256 == hashlib.sha256(large).hexdigest()
    with pytest.raises(ValueError):
        parse_slurm_snapshot("", source="squeue", job_id="123;bad", observed_at_utc=OBSERVED_AT)
    with pytest.raises(ValueError):
        parse_slurm_snapshot(
            "", source="squeue", job_id="123", observed_at_utc="2026-02-30T00:00:00Z"
        )


def test_completed_zero_exit_and_scientific_completion_need_no_restart() -> None:
    assessment = assess_restart(VASP_FIXTURES / "normal", _sacct("COMPLETED"))

    assert assessment.decision is RestartDecision.NO_RESTART
    assert assessment.failure_categories == (FailureCategory.NONE,)
    assert assessment.required_reviews == (
        "verify_scheduler_vasp_run_binding",
        "accept_scientific_result",
    )
    assert "RUN_BINDING_REQUIRES_REVIEW" in {item.code for item in assessment.diagnostics}
    assert assessment.restart_authorized is False
    assert assessment.writes_performed is False
    assert assessment.commands_executed is False
    assert assessment.submitted is False


def test_active_scheduler_state_waits_and_never_authorizes_restart() -> None:
    snapshot = parse_slurm_snapshot(
        "12345|RUNNING|01:00\n",
        source="squeue",
        job_id="12345",
        observed_at_utc=OBSERVED_AT,
    )

    assessment = assess_restart(VASP_FIXTURES / "truncated", snapshot)

    assert assessment.decision is RestartDecision.WAIT
    assert assessment.failure_categories == (FailureCategory.ACTIVE,)
    assert assessment.restart_authorized is False


def test_scheduler_completion_does_not_hide_vasp_nonconvergence() -> None:
    assessment = assess_restart(VASP_FIXTURES / "unconverged", _sacct("COMPLETED"))

    assert assessment.decision is RestartDecision.MANUAL_REVIEW_REQUIRED
    assert FailureCategory.VASP_NOT_CONVERGED in assessment.failure_categories
    assert "SCHEDULER_COMPLETED_BUT_VASP_INCOMPLETE" in {
        item.code for item in assessment.diagnostics
    }
    assert assessment.scientific_parameters_changed is False
    assert "approve_restart_without_silent_protocol_change" in assessment.required_reviews


def test_timeout_and_truncated_artifact_require_manual_review() -> None:
    assessment = assess_restart(
        VASP_FIXTURES / "truncated",
        _sacct("TIMEOUT", exit_code="0:9"),
    )

    assert assessment.decision is RestartDecision.MANUAL_REVIEW_REQUIRED
    assert set(assessment.failure_categories) == {
        FailureCategory.SCHEDULER_TIMEOUT,
        FailureCategory.SCHEDULER_NONZERO_EXIT,
        FailureCategory.ARTIFACT_INCOMPLETE,
    }


def test_failing_scheduler_with_complete_vasp_is_an_evidence_conflict() -> None:
    assessment = assess_restart(
        VASP_FIXTURES / "normal",
        _sacct("FAILED", exit_code="1:0"),
    )

    assert assessment.decision is RestartDecision.MANUAL_REVIEW_REQUIRED
    assert FailureCategory.EVIDENCE_CONFLICT in assessment.failure_categories
    assert "SCHEDULER_VASP_EVIDENCE_CONFLICT" in {item.code for item in assessment.diagnostics}


def test_squeue_completion_is_not_enough_to_close_a_scientific_run() -> None:
    snapshot = parse_slurm_snapshot(
        "12345|COMPLETED|02:00\n",
        source="squeue",
        job_id="12345",
        observed_at_utc=OBSERVED_AT,
    )

    assessment = assess_restart(VASP_FIXTURES / "normal", snapshot)

    assert assessment.decision is RestartDecision.MANUAL_REVIEW_REQUIRED
    assert "RESTART_TERMINAL_ACCOUNTING_REQUIRED" in {item.code for item in assessment.diagnostics}


def test_invalid_scheduler_evidence_blocks_assessment() -> None:
    assessment = assess_restart(VASP_FIXTURES / "normal", _sacct("FUTURE_STATE"))

    assert assessment.decision is RestartDecision.BLOCKED
    assert assessment.has_errors
    assert assessment.restart_authorized is False


def test_cli_parses_and_assesses_without_modifying_inputs(tmp_path: Path, capsys) -> None:
    snapshot = tmp_path / "snapshot.txt"
    snapshot.write_text("12345|COMPLETED|0:0|120\n", encoding="utf-8")
    before = {item.name: item.read_bytes() for item in (VASP_FIXTURES / "normal").iterdir()}

    parse_exit = main(
        [
            "parse-slurm-snapshot",
            str(snapshot),
            "--source",
            "sacct",
            "--job-id",
            "12345",
            "--observed-at-utc",
            OBSERVED_AT,
            "--format",
            "json",
        ]
    )
    parsed = json.loads(capsys.readouterr().out)
    assess_exit = main(
        [
            "assess-restart",
            str(VASP_FIXTURES / "normal"),
            "--slurm-snapshot",
            str(snapshot),
            "--source",
            "sacct",
            "--job-id",
            "12345",
            "--observed-at-utc",
            OBSERVED_AT,
            "--format",
            "json",
        ]
    )
    assessed = json.loads(capsys.readouterr().out)
    after = {item.name: item.read_bytes() for item in (VASP_FIXTURES / "normal").iterdir()}

    assert parse_exit == 0
    assert parsed["status"] == "observed"
    assert assess_exit == 0
    assert assessed["status"] == "no_restart"
    assert assessed["writes_performed"] is False
    assert assessed["commands_executed"] is False
    assert assessed["submitted"] is False
    assert str(VASP_FIXTURES) not in json.dumps(assessed)
    assert before == after
