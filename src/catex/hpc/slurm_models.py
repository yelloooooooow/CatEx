"""Versioned, sanitized records for read-only Slurm observation and restart review."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from catex.models import Diagnostic, Severity


class SlurmSnapshotSource(StrEnum):
    """Supported fixed-column snapshot sources."""

    SQUEUE = "squeue"
    SACCT = "sacct"


class SlurmJobState(StrEnum):
    """Conservative subset of user-facing Slurm states used by CatEx."""

    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    COMPLETING = "COMPLETING"
    CONFIGURING = "CONFIGURING"
    FAILED = "FAILED"
    NODE_FAIL = "NODE_FAIL"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    PENDING = "PENDING"
    PREEMPTED = "PREEMPTED"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class RestartDecision(StrEnum):
    """Review disposition; no value authorizes a restart operation."""

    BLOCKED = "blocked"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    NO_RESTART = "no_restart"
    WAIT = "wait"


class FailureCategory(StrEnum):
    """Evidence-level categories, not automatic scientific remedies."""

    ACTIVE = "active"
    ARTIFACT_INCOMPLETE = "artifact_incomplete"
    EVIDENCE_CONFLICT = "evidence_conflict"
    NONE = "none"
    SCHEDULER_CANCELLED = "scheduler_cancelled"
    SCHEDULER_NODE_FAILURE = "scheduler_node_failure"
    SCHEDULER_NONZERO_EXIT = "scheduler_nonzero_exit"
    SCHEDULER_OUT_OF_MEMORY = "scheduler_out_of_memory"
    SCHEDULER_PREEMPTED = "scheduler_preempted"
    SCHEDULER_TIMEOUT = "scheduler_timeout"
    UNKNOWN = "unknown"
    VASP_FATAL = "vasp_fatal"
    VASP_NOT_CONVERGED = "vasp_not_converged"


@dataclass(frozen=True, slots=True)
class SlurmJobObservation:
    """One sanitized job-level observation from a caller-provided snapshot."""

    job_id: str
    source: SlurmSnapshotSource
    state: SlurmJobState
    elapsed_seconds: int
    observed_at_utc: str
    exit_code: int | None = None
    terminating_signal: int | None = None
    schema_version: str = "catex.slurm-job-observation.v1"

    @property
    def active(self) -> bool:
        return self.state in {
            SlurmJobState.COMPLETING,
            SlurmJobState.CONFIGURING,
            SlurmJobState.PENDING,
            SlurmJobState.RUNNING,
            SlurmJobState.SUSPENDED,
        }

    @property
    def terminal(self) -> bool:
        return self.state in {
            SlurmJobState.CANCELLED,
            SlurmJobState.COMPLETED,
            SlurmJobState.FAILED,
            SlurmJobState.NODE_FAIL,
            SlurmJobState.OUT_OF_MEMORY,
            SlurmJobState.PREEMPTED,
            SlurmJobState.TIMEOUT,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "source": self.source.value,
            "state": self.state.value,
            "elapsed_seconds": self.elapsed_seconds,
            "observed_at_utc": self.observed_at_utc,
            "exit_code": self.exit_code,
            "terminating_signal": self.terminating_signal,
            "active": self.active,
            "terminal": self.terminal,
        }


@dataclass(frozen=True, slots=True)
class SlurmSnapshotReport:
    """Parse result that retains no raw scheduler output or unrelated job rows."""

    source_name: str
    source_sha256: str
    source_size_bytes: int
    requested_job_id: str
    source: SlurmSnapshotSource
    observation: SlurmJobObservation | None
    diagnostics: tuple[Diagnostic, ...]
    raw_content_included: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.slurm-snapshot-parse.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "error" if self.has_errors or self.observation is None else "observed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "source_name": self.source_name,
            "source_sha256": self.source_sha256,
            "source_size_bytes": self.source_size_bytes,
            "requested_job_id": self.requested_job_id,
            "source": self.source.value,
            "observation": self.observation.to_dict() if self.observation else None,
            "raw_content_included": self.raw_content_included,
            "commands_executed": self.commands_executed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class VaspRestartEvidence:
    """Path-sanitized VASP evidence used for a restart review."""

    output_directory_name: str
    outcome: str
    scientifically_complete: bool
    electronic_convergence: str
    ionic_convergence: str
    fatal_error_codes: tuple[str, ...]
    artifact_names_and_sha256: tuple[tuple[str, str], ...]
    schema_version: str = "catex.vasp-restart-evidence.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "output_directory_name": self.output_directory_name,
            "outcome": self.outcome,
            "scientifically_complete": self.scientifically_complete,
            "electronic_convergence": self.electronic_convergence,
            "ionic_convergence": self.ionic_convergence,
            "fatal_error_codes": list(self.fatal_error_codes),
            "artifacts": [
                {"name": name, "sha256": sha256} for name, sha256 in self.artifact_names_and_sha256
            ],
        }


@dataclass(frozen=True, slots=True)
class RestartAssessment:
    """Non-executable restart assessment requiring a separate human action."""

    scheduler: SlurmJobObservation | None
    vasp: VaspRestartEvidence
    decision: RestartDecision
    failure_categories: tuple[FailureCategory, ...]
    required_reviews: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    restart_authorized: bool = False
    restart_inputs_materialized: bool = False
    scientific_parameters_changed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    submitted: bool = False
    schema_version: str = "catex.restart-assessment.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return self.decision.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "scheduler": self.scheduler.to_dict() if self.scheduler else None,
            "vasp": self.vasp.to_dict(),
            "failure_categories": [item.value for item in self.failure_categories],
            "required_reviews": list(self.required_reviews),
            "restart_authorized": self.restart_authorized,
            "restart_inputs_materialized": self.restart_inputs_materialized,
            "scientific_parameters_changed": self.scientific_parameters_changed,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "submitted": self.submitted,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
