"""Pure construction of evidence-bound scientific result review records."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from catex.hpc.run_binding_models import RunBindingReport, RunBindingStatus
from catex.results.models import ScientificResultDecision, ScientificResultReview

_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _timestamp(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError(f"{field} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, _UTC_FORMAT)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid YYYY-MM-DDTHH:MM:SSZ timestamp") from exc
    return parsed


def _one_line(value: str, *, field: str, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if any(character in value for character in "\r\n"):
        raise ValueError(f"{field} must be one line")
    normalized = value.strip()
    if (not normalized and not allow_empty) or len(normalized) > maximum:
        qualifier = "possibly empty " if allow_empty else "non-empty "
        raise ValueError(f"{field} must be one {qualifier}line of at most {maximum} characters")
    return normalized


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bound_identity(binding: RunBindingReport) -> dict[str, Any]:
    receipt = binding.receipt_report.receipt
    protocol = binding.protocol_identity
    scheduler = binding.scheduler
    if (
        not binding.binding_valid
        or binding.has_errors
        or receipt is None
        or protocol is None
        or scheduler is None
        or binding.manifest_sha256 is None
        or binding.receipt_report.source_sha256 is None
    ):
        raise ValueError("scientific review requires a complete, valid run binding")
    if (
        binding.status
        not in {
            RunBindingStatus.SCIENTIFIC_REVIEW_REQUIRED,
            RunBindingStatus.TERMINAL_REVIEW_REQUIRED,
        }
        or not scheduler.terminal
    ):
        raise ValueError("scientific review requires a terminal bound run")
    return {
        "schema": "catex.run-review-identity.v1",
        "submission_receipt_sha256": binding.receipt_report.source_sha256,
        "submission_scientific_result_eligible": receipt.scientific_result_eligible,
        "job_id": receipt.job_id,
        "output_directory_name": binding.output_directory_name,
        "plan_sha256": protocol.plan_sha256,
        "manifest_sha256": binding.manifest_sha256,
        "resolved_protocol_sha256": protocol.resolved_protocol_sha256,
        "energy_family_id": protocol.energy_family_id,
        "slurm_script_sha256": protocol.slurm_script_sha256,
        "scheduler": scheduler.to_dict(),
        "vasp": binding.vasp.to_dict(),
    }


def record_scientific_result_review(
    binding: RunBindingReport,
    *,
    accepted: bool,
    reviewer: str,
    reviewed_at_utc: str,
    note: str,
) -> ScientificResultReview:
    """Record one explicit decision without writing, executing, or submitting anything."""

    if not isinstance(accepted, bool):
        raise ValueError("accepted must be a boolean")
    reviewer_value = _one_line(reviewer, field="reviewer", maximum=100)
    note_value = _one_line(note, field="note", maximum=500)
    reviewed_at = _timestamp(reviewed_at_utc, field="reviewed_at_utc")
    identity = _bound_identity(binding)
    receipt = binding.receipt_report.receipt
    protocol = binding.protocol_identity
    scheduler = binding.scheduler
    if (
        receipt is None
        or protocol is None
        or scheduler is None
        or binding.manifest_sha256 is None
        or binding.receipt_report.source_sha256 is None
    ):
        raise ValueError("scientific review requires complete typed binding evidence")
    observed_at = _timestamp(scheduler.observed_at_utc, field="scheduler observed_at_utc")
    if reviewed_at < observed_at:
        raise ValueError("reviewed_at_utc cannot precede the scheduler observation")
    if accepted and (
        binding.status is not RunBindingStatus.SCIENTIFIC_REVIEW_REQUIRED
        or not binding.ready_for_scientific_review
        or not binding.scheduler_success
        or not binding.vasp.scientifically_complete
    ):
        raise ValueError("acceptance requires a bound, scheduler-successful, complete VASP run")

    decision = ScientificResultDecision.ACCEPTED if accepted else ScientificResultDecision.REJECTED
    binding_identity_sha256 = _digest(identity)
    review_payload = {
        "schema": "catex.scientific-result-review-content.v1",
        "decision": decision.value,
        "reviewer": reviewer_value,
        "reviewed_at_utc": reviewed_at_utc,
        "note": note_value,
        "binding_identity_sha256": binding_identity_sha256,
    }
    return ScientificResultReview(
        decision=decision,
        reviewer=reviewer_value,
        reviewed_at_utc=reviewed_at_utc,
        note=note_value,
        binding_identity_sha256=binding_identity_sha256,
        review_sha256=_digest(review_payload),
        submission_receipt_sha256=binding.receipt_report.source_sha256,
        submission_scientific_result_eligible=receipt.scientific_result_eligible,
        job_id=receipt.job_id,
        output_directory_name=binding.output_directory_name,
        plan_sha256=protocol.plan_sha256,
        manifest_sha256=binding.manifest_sha256,
        resolved_protocol_sha256=protocol.resolved_protocol_sha256,
        energy_family_id=protocol.energy_family_id,
        slurm_script_sha256=protocol.slurm_script_sha256,
        scheduler_source=scheduler.source.value,
        scheduler_state=scheduler.state.value,
        scheduler_elapsed_seconds=scheduler.elapsed_seconds,
        scheduler_exit_code=scheduler.exit_code,
        scheduler_terminating_signal=scheduler.terminating_signal,
        scheduler_observed_at_utc=scheduler.observed_at_utc,
        scheduler_active=scheduler.active,
        scheduler_terminal=scheduler.terminal,
        vasp_outcome=binding.vasp.outcome,
        vasp_scientifically_complete=binding.vasp.scientifically_complete,
        vasp_electronic_convergence=binding.vasp.electronic_convergence,
        vasp_ionic_convergence=binding.vasp.ionic_convergence,
        vasp_fatal_error_codes=binding.vasp.fatal_error_codes,
        vasp_artifact_names_and_sha256=binding.vasp.artifact_names_and_sha256,
        scientific_result_accepted=accepted,
        eligible_for_same_energy_family_derivation=accepted,
    )
