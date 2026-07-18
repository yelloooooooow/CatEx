"""Versioned, path-sanitized records for submission and run binding review."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from catex.hpc.slurm_models import SlurmJobObservation, VaspRestartEvidence
from catex.models import Diagnostic, Severity


class RunBindingStatus(StrEnum):
    """Evidence state; no value accepts a scientific result automatically."""

    ACTIVE = "active"
    ERROR = "error"
    SCIENTIFIC_REVIEW_REQUIRED = "scientific_review_required"
    TERMINAL_REVIEW_REQUIRED = "terminal_review_required"


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    """Sanitized record emitted after one separately authorized submission."""

    job_id: str
    job_directory_name: str
    job_name: str
    plan_sha256: str
    slurm_script_sha256: str
    submitted_at_utc: str
    approved_scope: str
    submission_command_template: str
    raw_submission_output_sha256: str
    submission_performed: bool
    scientific_result_eligible: bool
    overwrite_performed: bool
    deletion_performed: bool
    schema_version: str = "catex.submission-receipt.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "job_directory_name": self.job_directory_name,
            "job_name": self.job_name,
            "plan_sha256": self.plan_sha256,
            "slurm_script_sha256": self.slurm_script_sha256,
            "submitted_at_utc": self.submitted_at_utc,
            "approved_scope": self.approved_scope,
            "submission_command_template": self.submission_command_template,
            "raw_submission_output_sha256": self.raw_submission_output_sha256,
            "submission_performed": self.submission_performed,
            "scientific_result_eligible": self.scientific_result_eligible,
            "overwrite_performed": self.overwrite_performed,
            "deletion_performed": self.deletion_performed,
        }


@dataclass(frozen=True, slots=True)
class SubmissionReceiptParseReport:
    """Bounded receipt parse result that never retains raw JSON or full paths."""

    source_name: str
    source_sha256: str | None
    source_size_bytes: int | None
    receipt: SubmissionReceipt | None
    diagnostics: tuple[Diagnostic, ...]
    raw_content_included: bool = False
    raw_submission_output_included: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.submission-receipt-parse.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "validated" if self.receipt is not None and not self.has_errors else "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "source_name": self.source_name,
            "source_sha256": self.source_sha256,
            "source_size_bytes": self.source_size_bytes,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "raw_content_included": self.raw_content_included,
            "raw_submission_output_included": self.raw_submission_output_included,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class RunProtocolIdentity:
    """Sanitized scientific and execution identity recovered from the manifest."""

    job_name: str
    plan_sha256: str
    poscar_sha256: str
    resolved_protocol_sha256: str
    energy_family_id: str
    execution_profile_id: str
    cluster_policy_id: str
    slurm_script_sha256: str
    potcar_required_on_hpc: bool
    potcar_materialized: bool
    schema_version: str = "catex.run-protocol-identity.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_name": self.job_name,
            "plan_sha256": self.plan_sha256,
            "poscar_sha256": self.poscar_sha256,
            "resolved_protocol_sha256": self.resolved_protocol_sha256,
            "energy_family_id": self.energy_family_id,
            "execution_profile_id": self.execution_profile_id,
            "cluster_policy_id": self.cluster_policy_id,
            "slurm_script_sha256": self.slurm_script_sha256,
            "potcar_required_on_hpc": self.potcar_required_on_hpc,
            "potcar_materialized": self.potcar_materialized,
        }


@dataclass(frozen=True, slots=True)
class RunBindingReport:
    """Cross-check submission, scheduler, manifest, script, and VASP evidence."""

    status: RunBindingStatus
    output_directory_name: str
    manifest_name: str
    manifest_sha256: str | None
    protocol_identity: RunProtocolIdentity | None
    receipt_report: SubmissionReceiptParseReport
    scheduler: SlurmJobObservation | None
    vasp: VaspRestartEvidence
    binding_valid: bool
    scheduler_success: bool
    ready_for_scientific_review: bool
    required_reviews: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    scientific_result_accepted: bool = False
    additional_submission_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.run-binding.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "output_directory_name": self.output_directory_name,
            "manifest_name": self.manifest_name,
            "manifest_sha256": self.manifest_sha256,
            "protocol_identity": (
                self.protocol_identity.to_dict() if self.protocol_identity else None
            ),
            "receipt_report": self.receipt_report.to_dict(),
            "scheduler": self.scheduler.to_dict() if self.scheduler else None,
            "vasp": self.vasp.to_dict(),
            "binding_valid": self.binding_valid,
            "scheduler_success": self.scheduler_success,
            "ready_for_scientific_review": self.ready_for_scientific_review,
            "required_reviews": list(self.required_reviews),
            "scientific_result_accepted": self.scientific_result_accepted,
            "additional_submission_performed": self.additional_submission_performed,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
