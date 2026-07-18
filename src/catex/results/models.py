"""Versioned records for explicit scientific acceptance or rejection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ScientificResultDecision(StrEnum):
    """An explicit review outcome, never inferred from scheduler success."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ScientificResultReview:
    """Path-sanitized decision bound to immutable run evidence hashes."""

    decision: ScientificResultDecision
    reviewer: str
    reviewed_at_utc: str
    note: str
    binding_identity_sha256: str
    review_sha256: str
    submission_receipt_sha256: str
    submission_scientific_result_eligible: bool
    job_id: str
    output_directory_name: str
    plan_sha256: str
    manifest_sha256: str
    resolved_protocol_sha256: str
    energy_family_id: str
    slurm_script_sha256: str
    scheduler_source: str
    scheduler_state: str
    scheduler_elapsed_seconds: int
    scheduler_exit_code: int | None
    scheduler_terminating_signal: int | None
    scheduler_observed_at_utc: str
    scheduler_active: bool
    scheduler_terminal: bool
    vasp_outcome: str
    vasp_scientifically_complete: bool
    vasp_electronic_convergence: str
    vasp_ionic_convergence: str
    vasp_fatal_error_codes: tuple[str, ...]
    vasp_artifact_names_and_sha256: tuple[tuple[str, str], ...]
    scientific_result_accepted: bool
    eligible_for_same_energy_family_derivation: bool
    human_review_recorded: bool = True
    automatic_acceptance_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    additional_submission_performed: bool = False
    schema_version: str = "catex.scientific-result-review.v1"

    @property
    def status(self) -> str:
        return self.decision.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "decision": self.decision.value,
            "reviewer": self.reviewer,
            "reviewed_at_utc": self.reviewed_at_utc,
            "note": self.note,
            "binding_identity_sha256": self.binding_identity_sha256,
            "review_sha256": self.review_sha256,
            "submission_receipt_sha256": self.submission_receipt_sha256,
            "submission_scientific_result_eligible": (self.submission_scientific_result_eligible),
            "job_id": self.job_id,
            "output_directory_name": self.output_directory_name,
            "plan_sha256": self.plan_sha256,
            "manifest_sha256": self.manifest_sha256,
            "resolved_protocol_sha256": self.resolved_protocol_sha256,
            "energy_family_id": self.energy_family_id,
            "slurm_script_sha256": self.slurm_script_sha256,
            "scheduler": {
                "source": self.scheduler_source,
                "state": self.scheduler_state,
                "elapsed_seconds": self.scheduler_elapsed_seconds,
                "exit_code": self.scheduler_exit_code,
                "terminating_signal": self.scheduler_terminating_signal,
                "observed_at_utc": self.scheduler_observed_at_utc,
                "active": self.scheduler_active,
                "terminal": self.scheduler_terminal,
            },
            "vasp": {
                "outcome": self.vasp_outcome,
                "scientifically_complete": self.vasp_scientifically_complete,
                "electronic_convergence": self.vasp_electronic_convergence,
                "ionic_convergence": self.vasp_ionic_convergence,
                "fatal_error_codes": list(self.vasp_fatal_error_codes),
                "artifacts": [
                    {"name": name, "sha256": sha256}
                    for name, sha256 in self.vasp_artifact_names_and_sha256
                ],
            },
            "scientific_result_accepted": self.scientific_result_accepted,
            "eligible_for_same_energy_family_derivation": (
                self.eligible_for_same_energy_family_derivation
            ),
            "human_review_recorded": self.human_review_recorded,
            "automatic_acceptance_performed": self.automatic_acceptance_performed,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "additional_submission_performed": self.additional_submission_performed,
        }
