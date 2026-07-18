"""Pure parsing and planning for caller-provided Slurm and VASP evidence."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from catex.hpc.slurm_models import (
    FailureCategory,
    RestartAssessment,
    RestartDecision,
    SlurmJobObservation,
    SlurmJobState,
    SlurmSnapshotReport,
    SlurmSnapshotSource,
    VaspRestartEvidence,
)
from catex.models import Diagnostic, Severity
from catex.vasp.output import parse_vasp_output
from catex.vasp.output_models import VaspOutputParseReport, VaspRunOutcome

_JOB_ID = re.compile(r"^[0-9]+(?:[_+][0-9]+)?$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_EXIT_CODE = re.compile(r"^(\d+):(\d+)$")
_SLURM_DURATION = re.compile(
    r"^(?:(?P<days>\d+)-)?(?:(?P<hours>\d+):)?(?P<minutes>\d{1,2}):(?P<seconds>\d{2})$"
)
_MAX_SNAPSHOT_BYTES = 1024 * 1024
_HEADERS = {
    SlurmSnapshotSource.SQUEUE: (("JOBID", "STATE", "TIMEUSED"),),
    SlurmSnapshotSource.SACCT: (("JOBIDRAW", "STATE", "EXITCODE", "ELAPSEDRAW"),),
}


def _timestamp(value: str) -> str:
    if _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError("observed_at_utc must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("observed_at_utc is not a valid UTC timestamp") from exc
    return value


def _source(value: SlurmSnapshotSource | str) -> SlurmSnapshotSource:
    try:
        return SlurmSnapshotSource(value)
    except ValueError as exc:
        raise ValueError("source must be squeue or sacct") from exc


def _state(value: str) -> SlurmJobState:
    normalized = value.strip().upper().split(maxsplit=1)[0].rstrip("+")
    try:
        return SlurmJobState(normalized)
    except ValueError:
        return SlurmJobState.UNKNOWN


def _elapsed_seconds(value: str, source: SlurmSnapshotSource) -> int:
    if source is SlurmSnapshotSource.SACCT:
        parsed = int(value)
        if parsed < 0:
            raise ValueError
        return parsed
    match = _SLURM_DURATION.fullmatch(value)
    if match is None:
        raise ValueError
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    if minutes >= 60 or seconds >= 60:
        raise ValueError
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _error_report(
    *,
    source_name: str,
    digest: str,
    size: int,
    requested_job_id: str,
    source: SlurmSnapshotSource,
    code: str,
    message: str,
    context: dict[str, object] | None = None,
) -> SlurmSnapshotReport:
    return SlurmSnapshotReport(
        source_name=source_name,
        source_sha256=digest,
        source_size_bytes=size,
        requested_job_id=requested_job_id,
        source=source,
        observation=None,
        diagnostics=(Diagnostic(code, Severity.ERROR, message, context or {}),),
    )


def parse_slurm_snapshot(
    content: str | bytes,
    *,
    source: SlurmSnapshotSource | str,
    job_id: str,
    observed_at_utc: str,
    source_name: str = "slurm-snapshot.txt",
) -> SlurmSnapshotReport:
    """Parse fixed pipe-delimited output without running a scheduler command."""

    parsed_source = _source(source)
    if _JOB_ID.fullmatch(job_id) is None:
        raise ValueError("job_id must be a numeric Slurm allocation, array, or heterogeneous ID")
    observed_at = _timestamp(observed_at_utc)
    raw = content.encode("utf-8") if isinstance(content, str) else content
    name = Path(source_name).name or "slurm-snapshot.txt"
    digest = hashlib.sha256(raw).hexdigest()
    size = len(raw)
    if size > _MAX_SNAPSHOT_BYTES:
        return _error_report(
            source_name=name,
            digest=digest,
            size=size,
            requested_job_id=job_id,
            source=parsed_source,
            code="SLURM_SNAPSHOT_TOO_LARGE",
            message="The scheduler snapshot exceeds the 1 MiB read-only parser limit.",
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _error_report(
            source_name=name,
            digest=digest,
            size=size,
            requested_job_id=job_id,
            source=parsed_source,
            code="SLURM_SNAPSHOT_ENCODING_INVALID",
            message="The scheduler snapshot must be UTF-8 text.",
        )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    headers = _HEADERS[parsed_source]
    expected = headers[0]
    if lines and tuple(item.strip().upper() for item in lines[0].split("|")) in headers:
        lines = lines[1:]

    matching: list[list[str]] = []
    unrelated = 0
    for line in lines:
        fields = [item.strip() for item in line.split("|")]
        if len(fields) != len(expected):
            return _error_report(
                source_name=name,
                digest=digest,
                size=size,
                requested_job_id=job_id,
                source=parsed_source,
                code="SLURM_SNAPSHOT_COLUMN_COUNT_INVALID",
                message="A snapshot row does not match the documented fixed-column grammar.",
                context={"expected_columns": len(expected)},
            )
        if fields[0] == job_id:
            matching.append(fields)
        else:
            unrelated += 1
    if not matching:
        return _error_report(
            source_name=name,
            digest=digest,
            size=size,
            requested_job_id=job_id,
            source=parsed_source,
            code="SLURM_JOB_NOT_FOUND_IN_SNAPSHOT",
            message="The requested allocation row is absent from the provided snapshot.",
        )
    if len(matching) != 1:
        return _error_report(
            source_name=name,
            digest=digest,
            size=size,
            requested_job_id=job_id,
            source=parsed_source,
            code="SLURM_JOB_ROW_AMBIGUOUS",
            message="The provided snapshot contains duplicate rows for the requested allocation.",
            context={"matching_rows": len(matching)},
        )

    fields = matching[0]
    state = _state(fields[1])
    try:
        elapsed_seconds = _elapsed_seconds(fields[-1], parsed_source)
    except ValueError:
        elapsed_seconds = -1
    diagnostics: list[Diagnostic] = []
    if elapsed_seconds < 0:
        diagnostics.append(
            Diagnostic(
                "SLURM_ELAPSED_RAW_INVALID",
                Severity.ERROR,
                "Elapsed time does not match the fixed squeue TimeUsed or sacct "
                "ElapsedRaw grammar.",
            )
        )
    if state is SlurmJobState.UNKNOWN:
        diagnostics.append(
            Diagnostic(
                "SLURM_STATE_NOT_SUPPORTED",
                Severity.ERROR,
                "The job state is outside the conservative CatEx observation registry.",
            )
        )
    exit_code: int | None = None
    signal: int | None = None
    if parsed_source is SlurmSnapshotSource.SACCT:
        match = _EXIT_CODE.fullmatch(fields[2])
        if match is None:
            diagnostics.append(
                Diagnostic(
                    "SLURM_EXIT_CODE_INVALID",
                    Severity.ERROR,
                    "sacct ExitCode must use unsigned status:signal notation.",
                )
            )
        else:
            exit_code = int(match.group(1))
            signal = int(match.group(2))
    if unrelated:
        diagnostics.append(
            Diagnostic(
                "SLURM_UNRELATED_ROWS_IGNORED",
                Severity.INFO,
                "Rows for other allocations were ignored and are not retained.",
                {"count": unrelated},
            )
        )
    observation = SlurmJobObservation(
        job_id=job_id,
        source=parsed_source,
        state=state,
        elapsed_seconds=max(0, elapsed_seconds),
        observed_at_utc=observed_at,
        exit_code=exit_code,
        terminating_signal=signal,
    )
    return SlurmSnapshotReport(
        source_name=name,
        source_sha256=digest,
        source_size_bytes=size,
        requested_job_id=job_id,
        source=parsed_source,
        observation=observation,
        diagnostics=tuple(diagnostics),
    )


def parse_slurm_snapshot_path(
    path: str | Path,
    *,
    source: SlurmSnapshotSource | str,
    job_id: str,
    observed_at_utc: str,
) -> SlurmSnapshotReport:
    """Read one caller-provided local snapshot and retain no raw content."""

    parsed_source = _source(source)
    if _JOB_ID.fullmatch(job_id) is None:
        raise ValueError("job_id must be a numeric Slurm allocation, array, or heterogeneous ID")
    _timestamp(observed_at_utc)
    snapshot = Path(path)
    hasher = hashlib.sha256()
    buffer = bytearray()
    size = 0
    with snapshot.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            hasher.update(chunk)
            size += len(chunk)
            if size <= _MAX_SNAPSHOT_BYTES:
                buffer.extend(chunk)
            else:
                buffer.clear()
    if size > _MAX_SNAPSHOT_BYTES:
        return _error_report(
            source_name=snapshot.name,
            digest=hasher.hexdigest(),
            size=size,
            requested_job_id=job_id,
            source=parsed_source,
            code="SLURM_SNAPSHOT_TOO_LARGE",
            message="The scheduler snapshot exceeds the 1 MiB read-only parser limit.",
        )
    return parse_slurm_snapshot(
        bytes(buffer),
        source=parsed_source,
        job_id=job_id,
        observed_at_utc=observed_at_utc,
        source_name=snapshot.name,
    )


def _vasp_evidence(directory: str | Path, report: VaspOutputParseReport) -> VaspRestartEvidence:
    return VaspRestartEvidence(
        output_directory_name=Path(directory).name or "vasp-output",
        outcome=report.termination.outcome.value,
        scientifically_complete=report.scientifically_complete,
        electronic_convergence=report.convergence.electronic.value,
        ionic_convergence=report.convergence.ionic.value,
        fatal_error_codes=report.termination.fatal_error_codes,
        artifact_names_and_sha256=tuple(
            sorted((Path(item.path).name, item.sha256) for item in report.artifacts)
        ),
    )


def _vasp_categories(report: VaspOutputParseReport) -> list[FailureCategory]:
    if report.scientifically_complete:
        return []
    if report.termination.outcome is VaspRunOutcome.FAILED:
        return [FailureCategory.VASP_FATAL]
    if report.termination.outcome is VaspRunOutcome.UNCONVERGED:
        return [FailureCategory.VASP_NOT_CONVERGED]
    if report.termination.outcome is VaspRunOutcome.TRUNCATED:
        return [FailureCategory.ARTIFACT_INCOMPLETE]
    return [FailureCategory.UNKNOWN]


def assess_restart(
    output_directory: str | Path,
    scheduler_report: SlurmSnapshotReport,
) -> RestartAssessment:
    """Cross-check evidence and stop at a non-executable human-review decision."""

    vasp_report = parse_vasp_output(output_directory)
    vasp = _vasp_evidence(output_directory, vasp_report)
    observation = scheduler_report.observation
    diagnostics: list[Diagnostic] = []
    categories: list[FailureCategory] = []
    if scheduler_report.has_errors or observation is None:
        diagnostics.append(
            Diagnostic(
                "RESTART_SCHEDULER_EVIDENCE_INVALID",
                Severity.ERROR,
                "A unique, supported scheduler observation is required before restart review.",
            )
        )
        return RestartAssessment(
            scheduler=observation,
            vasp=vasp,
            decision=RestartDecision.BLOCKED,
            failure_categories=(FailureCategory.UNKNOWN,),
            required_reviews=("obtain_complete_scheduler_snapshot", "inspect_vasp_outputs"),
            diagnostics=tuple(diagnostics),
        )

    if observation.active:
        return RestartAssessment(
            scheduler=observation,
            vasp=vasp,
            decision=RestartDecision.WAIT,
            failure_categories=(FailureCategory.ACTIVE,),
            required_reviews=("observe_again_after_state_change",),
            diagnostics=(),
        )

    if not observation.terminal:
        diagnostics.append(
            Diagnostic(
                "RESTART_SCHEDULER_STATE_INDETERMINATE",
                Severity.ERROR,
                "The scheduler state is neither active nor a supported terminal state.",
            )
        )
        return RestartAssessment(
            scheduler=observation,
            vasp=vasp,
            decision=RestartDecision.BLOCKED,
            failure_categories=(FailureCategory.UNKNOWN,),
            required_reviews=("obtain_complete_scheduler_snapshot",),
            diagnostics=tuple(diagnostics),
        )

    if observation.state is SlurmJobState.COMPLETED and vasp_report.scientifically_complete:
        if (
            observation.source is SlurmSnapshotSource.SACCT
            and observation.exit_code == 0
            and observation.terminating_signal == 0
        ):
            return RestartAssessment(
                scheduler=observation,
                vasp=vasp,
                decision=RestartDecision.NO_RESTART,
                failure_categories=(FailureCategory.NONE,),
                required_reviews=(
                    "verify_scheduler_vasp_run_binding",
                    "accept_scientific_result",
                ),
                diagnostics=(
                    Diagnostic(
                        "RUN_BINDING_REQUIRES_REVIEW",
                        Severity.WARNING,
                        "This assessment does not include an independent submission receipt; "
                        "use run-binding validation before scientific acceptance.",
                    ),
                ),
            )
        diagnostics.append(
            Diagnostic(
                "RESTART_TERMINAL_ACCOUNTING_REQUIRED",
                Severity.WARNING,
                "A sacct allocation record with ExitCode 0:0 is required to close the run.",
            )
        )

    scheduler_category = {
        SlurmJobState.CANCELLED: FailureCategory.SCHEDULER_CANCELLED,
        SlurmJobState.NODE_FAIL: FailureCategory.SCHEDULER_NODE_FAILURE,
        SlurmJobState.OUT_OF_MEMORY: FailureCategory.SCHEDULER_OUT_OF_MEMORY,
        SlurmJobState.PREEMPTED: FailureCategory.SCHEDULER_PREEMPTED,
        SlurmJobState.TIMEOUT: FailureCategory.SCHEDULER_TIMEOUT,
    }.get(observation.state)
    if scheduler_category is not None:
        categories.append(scheduler_category)
    if observation.state is SlurmJobState.FAILED or (observation.exit_code or 0) != 0:
        categories.append(FailureCategory.SCHEDULER_NONZERO_EXIT)
    if (observation.terminating_signal or 0) != 0:
        categories.append(FailureCategory.SCHEDULER_NONZERO_EXIT)
    categories.extend(_vasp_categories(vasp_report))
    if observation.state is SlurmJobState.COMPLETED and not vasp_report.scientifically_complete:
        diagnostics.append(
            Diagnostic(
                "SCHEDULER_COMPLETED_BUT_VASP_INCOMPLETE",
                Severity.WARNING,
                "Scheduler completion does not establish scientific convergence.",
            )
        )
    if observation.state is not SlurmJobState.COMPLETED and vasp_report.scientifically_complete:
        categories.append(FailureCategory.EVIDENCE_CONFLICT)
        diagnostics.append(
            Diagnostic(
                "SCHEDULER_VASP_EVIDENCE_CONFLICT",
                Severity.WARNING,
                "VASP appears scientifically complete while Slurm reports a failing "
                "terminal state.",
            )
        )
    unique_categories = tuple(dict.fromkeys(categories)) or (FailureCategory.UNKNOWN,)
    return RestartAssessment(
        scheduler=observation,
        vasp=vasp,
        decision=RestartDecision.MANUAL_REVIEW_REQUIRED,
        failure_categories=unique_categories,
        required_reviews=(
            "confirm_scheduler_and_vasp_evidence",
            "verify_restart_artifact_integrity",
            "decide_checkpoint_reuse",
            "approve_restart_without_silent_protocol_change",
        ),
        diagnostics=tuple(diagnostics),
    )
