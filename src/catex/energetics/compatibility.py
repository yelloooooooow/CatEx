"""Pure, fail-closed construction and combination of reviewed VASP energies."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from catex.energetics.models import (
    EnergyCompatibilityReport,
    EnergyTerm,
    EnergyTermContribution,
    LinearEnergyDerivationReport,
    ReviewedEnergyEvidence,
    ReviewedEnergyRecord,
    VaspEnergyKind,
)
from catex.models import Diagnostic, Severity
from catex.results import ScientificResultDecision, ScientificResultReview
from catex.vasp.output_models import ParseConfidence, VaspOutputParseReport

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENERGY_FAMILY = re.compile(r"^sha256:[0-9a-f]{64}$")


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validated_identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe identifier of at most 100 characters")
    return value


def _review_binding_identity(review: ScientificResultReview) -> dict[str, Any]:
    return {
        "schema": "catex.run-review-identity.v1",
        "submission_receipt_sha256": review.submission_receipt_sha256,
        "submission_scientific_result_eligible": (review.submission_scientific_result_eligible),
        "job_id": review.job_id,
        "output_directory_name": review.output_directory_name,
        "plan_sha256": review.plan_sha256,
        "manifest_sha256": review.manifest_sha256,
        "resolved_protocol_sha256": review.resolved_protocol_sha256,
        "energy_family_id": review.energy_family_id,
        "slurm_script_sha256": review.slurm_script_sha256,
        "scheduler": {
            "schema_version": "catex.slurm-job-observation.v1",
            "job_id": review.job_id,
            "source": review.scheduler_source,
            "state": review.scheduler_state,
            "elapsed_seconds": review.scheduler_elapsed_seconds,
            "observed_at_utc": review.scheduler_observed_at_utc,
            "exit_code": review.scheduler_exit_code,
            "terminating_signal": review.scheduler_terminating_signal,
            "active": review.scheduler_active,
            "terminal": review.scheduler_terminal,
        },
        "vasp": {
            "schema_version": "catex.vasp-restart-evidence.v1",
            "output_directory_name": review.output_directory_name,
            "outcome": review.vasp_outcome,
            "scientifically_complete": review.vasp_scientifically_complete,
            "electronic_convergence": review.vasp_electronic_convergence,
            "ionic_convergence": review.vasp_ionic_convergence,
            "fatal_error_codes": list(review.vasp_fatal_error_codes),
            "artifacts": [
                {"name": name, "sha256": sha256}
                for name, sha256 in review.vasp_artifact_names_and_sha256
            ],
        },
    }


def _validated_review(review: ScientificResultReview) -> None:
    if not isinstance(review, ScientificResultReview):
        raise ValueError("review must be a ScientificResultReview")
    if (
        review.decision is not ScientificResultDecision.ACCEPTED
        or not review.scientific_result_accepted
        or not review.submission_scientific_result_eligible
        or not review.eligible_for_same_energy_family_derivation
        or not review.human_review_recorded
        or review.automatic_acceptance_performed
        or review.writes_performed
        or review.commands_executed
        or review.additional_submission_performed
    ):
        raise ValueError("reviewed energy requires an eligible, explicit human acceptance")
    if (
        review.schema_version != "catex.scientific-result-review.v1"
        or review.binding_identity_sha256 != _digest(_review_binding_identity(review))
        or review.review_sha256
        != _digest(
            {
                "schema": "catex.scientific-result-review-content.v1",
                "decision": review.decision.value,
                "reviewer": review.reviewer,
                "reviewed_at_utc": review.reviewed_at_utc,
                "note": review.note,
                "binding_identity_sha256": review.binding_identity_sha256,
            }
        )
        or not _matches(_SHA256, review.submission_receipt_sha256)
        or not _matches(_SHA256, review.review_sha256)
        or not _matches(_SHA256, review.binding_identity_sha256)
        or not _matches(_ENERGY_FAMILY, review.energy_family_id)
    ):
        raise ValueError("review contains an invalid provenance identity")
    _validated_identifier(review.output_directory_name, field="review output_directory_name")


def _energy_value(report: VaspOutputParseReport, kind: VaspEnergyKind) -> float | None:
    energy = report.energy
    if energy is None:
        return None
    if kind is VaspEnergyKind.FREE_ENERGY_TOTEN:
        return energy.free_energy_ev
    if kind is VaspEnergyKind.ENERGY_WITHOUT_ENTROPY:
        return energy.energy_without_entropy_ev
    if kind is VaspEnergyKind.SIGMA_ZERO:
        return energy.sigma_zero_energy_ev
    return None


def _energy_evidence(report: VaspOutputParseReport, kind: VaspEnergyKind):
    if report.energy is None:
        return ()
    if kind is VaspEnergyKind.ENERGY_WITHOUT_ENTROPY:
        return tuple(
            item
            for item in report.energy.evidence
            if item.parser_rule == "outcar.final_free_energy_block"
        )
    return report.energy.evidence


def _record_identity(record: ReviewedEnergyRecord) -> dict[str, Any]:
    return {
        "schema": "catex.reviewed-energy-content.v1",
        "energy_id": record.energy_id,
        "kind": record.kind.value,
        "value_eV": record.value_ev,
        "ionic_step": record.ionic_step,
        "parse_confidence": record.parse_confidence.value,
        "energy_family_id": record.energy_family_id,
        "review_sha256": record.review_sha256,
        "binding_identity_sha256": record.binding_identity_sha256,
        "output_directory_name": record.output_directory_name,
        "vasp_artifacts": [list(item) for item in record.vasp_artifact_names_and_sha256],
        "evidence": [item.to_dict() for item in record.evidence],
        "acceptance": {
            "scientific_result_accepted": record.scientific_result_accepted,
            "submission_scientific_result_eligible": (record.submission_scientific_result_eligible),
            "eligible_for_same_energy_family_derivation": (
                record.eligible_for_same_energy_family_derivation
            ),
            "human_review_recorded": record.human_review_recorded,
            "automatic_acceptance_performed": record.automatic_acceptance_performed,
        },
    }


def bind_reviewed_vasp_energy(
    review: ScientificResultReview,
    report: VaspOutputParseReport,
    *,
    energy_id: str,
    kind: VaspEnergyKind,
) -> ReviewedEnergyRecord:
    """Bind one explicit energy field to an accepted and byte-identical VASP result."""

    _validated_review(review)
    energy_id_value = _validated_identifier(energy_id, field="energy_id")
    if not isinstance(report, VaspOutputParseReport):
        raise ValueError("report must be a VaspOutputParseReport")
    if not isinstance(kind, VaspEnergyKind):
        raise ValueError("kind must be a VaspEnergyKind")
    if not report.scientifically_complete or report.has_errors or report.energy is None:
        raise ValueError("reviewed energy requires a scientifically complete VASP parse report")
    if (
        report.target_vasp_version != "5.4.4"
        or report.detected_vasp_version != report.target_vasp_version
    ):
        raise ValueError("reviewed energy requires the declared VASP 5.4.4 target version")
    if Path(report.directory).name != review.output_directory_name:
        raise ValueError("VASP output directory does not match the accepted review")
    if report.status != review.vasp_outcome:
        raise ValueError("VASP outcome does not match the accepted review")

    artifacts = tuple(sorted((Path(item.path).name, item.sha256) for item in report.artifacts))
    if artifacts != review.vasp_artifact_names_and_sha256:
        raise ValueError("VASP artifact hashes do not match the accepted review")
    if (
        not artifacts
        or len({name for name, _ in artifacts}) != len(artifacts)
        or any(
            not _matches(_IDENTIFIER, name) or not _matches(_SHA256, value)
            for name, value in artifacts
        )
    ):
        raise ValueError("VASP artifact identity is invalid or ambiguous")

    energy = report.energy
    value = _energy_value(report, kind)
    if value is None or not math.isfinite(value):
        raise ValueError(f"selected VASP energy field {kind.value} is unavailable or non-finite")
    if energy.confidence is not ParseConfidence.HIGH:
        raise ValueError("reviewed energy requires high-confidence parser evidence")

    evidence = tuple(
        ReviewedEnergyEvidence(
            artifact_name=Path(item.artifact_path).name,
            line_start=item.line_start,
            line_end=item.line_end,
            parser_rule=item.parser_rule,
            confidence=item.confidence,
        )
        for item in _energy_evidence(report, kind)
    )
    artifact_names = {name for name, _ in artifacts}
    if not evidence or any(
        item.artifact_name not in artifact_names
        or item.line_start < 1
        or item.line_end < item.line_start
        or item.confidence is not ParseConfidence.HIGH
        for item in evidence
    ):
        raise ValueError("selected VASP energy has incomplete or mismatched parser evidence")

    provisional = ReviewedEnergyRecord(
        energy_id=energy_id_value,
        kind=kind,
        value_ev=value,
        ionic_step=energy.ionic_step,
        parse_confidence=energy.confidence,
        energy_family_id=review.energy_family_id,
        review_sha256=review.review_sha256,
        binding_identity_sha256=review.binding_identity_sha256,
        record_sha256="0" * 64,
        output_directory_name=review.output_directory_name,
        vasp_artifact_names_and_sha256=artifacts,
        evidence=evidence,
        scientific_result_accepted=review.scientific_result_accepted,
        submission_scientific_result_eligible=(review.submission_scientific_result_eligible),
        eligible_for_same_energy_family_derivation=(
            review.eligible_for_same_energy_family_derivation
        ),
        human_review_recorded=review.human_review_recorded,
        automatic_acceptance_performed=review.automatic_acceptance_performed,
    )
    return replace(
        provisional,
        record_sha256=_digest(_record_identity(provisional)),
    )


def _accepted_record(record: ReviewedEnergyRecord) -> bool:
    structurally_valid = (
        isinstance(record, ReviewedEnergyRecord)
        and record.schema_version == "catex.reviewed-energy.v1"
        and isinstance(record.kind, VaspEnergyKind)
        and isinstance(record.parse_confidence, ParseConfidence)
        and record.parse_confidence is ParseConfidence.HIGH
        and isinstance(record.value_ev, int | float)
        and not isinstance(record.value_ev, bool)
        and math.isfinite(record.value_ev)
        and _matches(_IDENTIFIER, record.energy_id)
        and _matches(_IDENTIFIER, record.output_directory_name)
        and _matches(_SHA256, record.record_sha256)
        and _matches(_SHA256, record.review_sha256)
        and _matches(_SHA256, record.binding_identity_sha256)
        and _matches(_ENERGY_FAMILY, record.energy_family_id)
        and record.scientific_result_accepted
        and record.submission_scientific_result_eligible
        and record.eligible_for_same_energy_family_derivation
        and record.human_review_recorded
        and not record.automatic_acceptance_performed
        and not record.writes_performed
        and not record.commands_executed
        and not record.additional_submission_performed
    )
    if not structurally_valid:
        return False
    try:
        artifacts_valid = bool(record.vasp_artifact_names_and_sha256) and all(
            _matches(_IDENTIFIER, name) and _matches(_SHA256, sha256)
            for name, sha256 in record.vasp_artifact_names_and_sha256
        )
        artifacts_valid = (
            artifacts_valid
            and len({name for name, _ in record.vasp_artifact_names_and_sha256})
            == len(record.vasp_artifact_names_and_sha256)
            and tuple(sorted(record.vasp_artifact_names_and_sha256))
            == record.vasp_artifact_names_and_sha256
        )
        evidence_valid = bool(record.evidence) and all(
            _matches(_IDENTIFIER, item.artifact_name)
            and item.artifact_name in {name for name, _ in record.vasp_artifact_names_and_sha256}
            and item.line_start >= 1
            and item.line_end >= item.line_start
            and item.confidence is ParseConfidence.HIGH
            for item in record.evidence
        )
        return (
            artifacts_valid
            and evidence_valid
            and record.record_sha256 == _digest(_record_identity(record))
        )
    except (AttributeError, TypeError, ValueError):
        return False


def assess_energy_compatibility(
    records: Sequence[ReviewedEnergyRecord],
) -> EnergyCompatibilityReport:
    """Assess whether reviewed VASP energies may enter one linear combination."""

    diagnostics: list[Diagnostic] = []
    if not records:
        diagnostics.append(
            Diagnostic(
                "ENERGY_INPUTS_EMPTY",
                Severity.ERROR,
                "At least one reviewed energy is required.",
            )
        )

    energy_ids = tuple(item.energy_id for item in records if isinstance(item, ReviewedEnergyRecord))
    record_sha256s = tuple(
        item.record_sha256 for item in records if isinstance(item, ReviewedEnergyRecord)
    )
    invalid_positions = [index for index, item in enumerate(records) if not _accepted_record(item)]
    if invalid_positions:
        diagnostics.append(
            Diagnostic(
                "ENERGY_INPUT_NOT_ACCEPTED",
                Severity.ERROR,
                "Every input must be a high-confidence, human-accepted reviewed energy.",
                {"positions_0based": tuple(invalid_positions)},
            )
        )
    if len(energy_ids) != len(records):
        diagnostics.append(
            Diagnostic(
                "ENERGY_INPUT_TYPE_INVALID",
                Severity.ERROR,
                "Every input must be a ReviewedEnergyRecord.",
            )
        )
    if len(set(energy_ids)) != len(energy_ids):
        diagnostics.append(
            Diagnostic(
                "ENERGY_ID_DUPLICATED",
                Severity.ERROR,
                "Energy identifiers must be unique within one derivation.",
            )
        )

    valid_records = tuple(item for item in records if _accepted_record(item))
    families = {item.energy_family_id for item in valid_records}
    kinds = {item.kind for item in valid_records}
    if len(families) > 1:
        diagnostics.append(
            Diagnostic(
                "ENERGY_FAMILY_MISMATCH",
                Severity.ERROR,
                "Reviewed energies use different scientific protocol compatibility families.",
                {"distinct_family_count": len(families)},
            )
        )
    if len(kinds) > 1:
        diagnostics.append(
            Diagnostic(
                "ENERGY_KIND_MISMATCH",
                Severity.ERROR,
                "TOTEN, energy without entropy, and sigma-zero values cannot be mixed.",
                {"kinds": tuple(sorted(item.value for item in kinds))},
            )
        )

    common_family = next(iter(families)) if len(families) == 1 else None
    common_kind = next(iter(kinds)) if len(kinds) == 1 else None
    compatible = bool(records) and len(valid_records) == len(records) and not diagnostics
    return EnergyCompatibilityReport(
        compatible=compatible,
        energy_ids=energy_ids,
        record_sha256s=record_sha256s,
        common_energy_family_id=common_family if compatible else None,
        common_kind=common_kind if compatible else None,
        diagnostics=tuple(diagnostics),
    )


def derive_linear_energy(
    terms: Sequence[EnergyTerm],
    *,
    derivation_id: str,
) -> LinearEnergyDerivationReport:
    """Compute a generic same-family linear combination without scientific interpretation."""

    derivation_id_value = _validated_identifier(derivation_id, field="derivation_id")
    diagnostics: list[Diagnostic] = []
    records: list[ReviewedEnergyRecord] = []
    coefficients_valid = True
    for index, term in enumerate(terms):
        if not isinstance(term, EnergyTerm):
            coefficients_valid = False
            diagnostics.append(
                Diagnostic(
                    "ENERGY_TERM_INVALID",
                    Severity.ERROR,
                    "Every derivation term must be an EnergyTerm.",
                    {"position_0based": index},
                )
            )
            continue
        records.append(term.energy)
        if (
            not isinstance(term.coefficient, int | float)
            or isinstance(term.coefficient, bool)
            or not math.isfinite(term.coefficient)
            or term.coefficient == 0
        ):
            coefficients_valid = False
            diagnostics.append(
                Diagnostic(
                    "ENERGY_COEFFICIENT_INVALID",
                    Severity.ERROR,
                    "Every coefficient must be finite and non-zero.",
                    {"position_0based": index},
                )
            )

    compatibility = assess_energy_compatibility(records)
    contributions: tuple[EnergyTermContribution, ...] = ()
    value: float | None = None
    derivation_sha256: str | None = None
    if coefficients_valid and compatibility.compatible and len(records) == len(terms):
        candidate_contributions = tuple(
            EnergyTermContribution(
                energy_id=term.energy.energy_id,
                record_sha256=term.energy.record_sha256,
                coefficient=float(term.coefficient),
                value_ev=term.energy.value_ev,
                contribution_ev=float(term.coefficient) * term.energy.value_ev,
            )
            for term in terms
        )
        try:
            candidate_value = math.fsum(item.contribution_ev for item in candidate_contributions)
        except OverflowError:
            candidate_value = math.inf
        if not all(
            math.isfinite(item.contribution_ev) for item in candidate_contributions
        ) or not math.isfinite(candidate_value):
            diagnostics.append(
                Diagnostic(
                    "ENERGY_ARITHMETIC_NONFINITE",
                    Severity.ERROR,
                    "The linear combination overflowed or produced a non-finite value.",
                )
            )
        else:
            contributions = candidate_contributions
            value = candidate_value
            identity = {
                "schema": "catex.linear-energy-derivation-content.v1",
                "derivation_id": derivation_id_value,
                "operation": "linear_combination",
                "terms": [item.to_dict() for item in contributions],
                "energy_family_id": compatibility.common_energy_family_id,
                "kind": compatibility.common_kind.value if compatibility.common_kind else None,
            }
            derivation_sha256 = _digest(identity)

    diagnostics.extend(compatibility.diagnostics)
    return LinearEnergyDerivationReport(
        derivation_id=derivation_id_value,
        terms=contributions,
        compatibility=compatibility,
        value_ev=value,
        energy_family_id=compatibility.common_energy_family_id if value is not None else None,
        kind=compatibility.common_kind if value is not None else None,
        derivation_sha256=derivation_sha256,
        diagnostics=tuple(diagnostics),
    )
