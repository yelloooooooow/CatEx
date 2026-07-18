"""Versioned records for review-gated electronic-energy derivations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from catex.models import Diagnostic, Severity
from catex.vasp.output_models import ParseConfidence


class VaspEnergyKind(StrEnum):
    """Distinct VASP electronic-energy fields that must never be mixed implicitly."""

    FREE_ENERGY_TOTEN = "free_energy_toten"
    ENERGY_WITHOUT_ENTROPY = "energy_without_entropy"
    SIGMA_ZERO = "sigma_zero"


@dataclass(frozen=True, slots=True)
class ReviewedEnergyEvidence:
    """Path-sanitized parser evidence retained with a reviewed energy."""

    artifact_name: str
    line_start: int
    line_end: int
    parser_rule: str
    confidence: ParseConfidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_name": self.artifact_name,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "parser_rule": self.parser_rule,
            "confidence": self.confidence.value,
        }


@dataclass(frozen=True, slots=True)
class ReviewedEnergyRecord:
    """One explicit VASP energy bound to accepted, unchanged run evidence."""

    energy_id: str
    kind: VaspEnergyKind
    value_ev: float
    ionic_step: int | None
    parse_confidence: ParseConfidence
    energy_family_id: str
    review_sha256: str
    binding_identity_sha256: str
    record_sha256: str
    output_directory_name: str
    vasp_artifact_names_and_sha256: tuple[tuple[str, str], ...]
    evidence: tuple[ReviewedEnergyEvidence, ...]
    scientific_result_accepted: bool
    submission_scientific_result_eligible: bool
    eligible_for_same_energy_family_derivation: bool
    human_review_recorded: bool
    automatic_acceptance_performed: bool
    writes_performed: bool = False
    commands_executed: bool = False
    additional_submission_performed: bool = False
    schema_version: str = "catex.reviewed-energy.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "energy_id": self.energy_id,
            "kind": self.kind.value,
            "value_eV": self.value_ev,
            "ionic_step": self.ionic_step,
            "parse_confidence": self.parse_confidence.value,
            "energy_family_id": self.energy_family_id,
            "review_sha256": self.review_sha256,
            "binding_identity_sha256": self.binding_identity_sha256,
            "record_sha256": self.record_sha256,
            "output_directory_name": self.output_directory_name,
            "vasp_artifacts": [
                {"name": name, "sha256": sha256}
                for name, sha256 in self.vasp_artifact_names_and_sha256
            ],
            "evidence": [item.to_dict() for item in self.evidence],
            "scientific_result_accepted": self.scientific_result_accepted,
            "submission_scientific_result_eligible": (self.submission_scientific_result_eligible),
            "eligible_for_same_energy_family_derivation": (
                self.eligible_for_same_energy_family_derivation
            ),
            "human_review_recorded": self.human_review_recorded,
            "automatic_acceptance_performed": self.automatic_acceptance_performed,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "additional_submission_performed": self.additional_submission_performed,
        }


@dataclass(frozen=True, slots=True)
class EnergyCompatibilityReport:
    """Fail-closed assessment for combining reviewed electronic energies."""

    compatible: bool
    energy_ids: tuple[str, ...]
    record_sha256s: tuple[str, ...]
    common_energy_family_id: str | None
    common_kind: VaspEnergyKind | None
    diagnostics: tuple[Diagnostic, ...]
    writes_performed: bool = False
    commands_executed: bool = False
    additional_submission_performed: bool = False
    schema_version: str = "catex.energy-compatibility.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "compatible" if self.compatible and not self.has_errors else "incompatible"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "compatible": self.compatible,
            "energy_ids": list(self.energy_ids),
            "record_sha256s": list(self.record_sha256s),
            "common_energy_family_id": self.common_energy_family_id,
            "common_kind": self.common_kind.value if self.common_kind else None,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "additional_submission_performed": self.additional_submission_performed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class EnergyTerm:
    """One coefficient and one reviewed electronic-energy record."""

    coefficient: float
    energy: ReviewedEnergyRecord


@dataclass(frozen=True, slots=True)
class EnergyTermContribution:
    """Auditable contribution to a generic linear energy combination."""

    energy_id: str
    record_sha256: str
    coefficient: float
    value_ev: float
    contribution_ev: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "energy_id": self.energy_id,
            "record_sha256": self.record_sha256,
            "coefficient": self.coefficient,
            "value_eV": self.value_ev,
            "contribution_eV": self.contribution_ev,
        }


@dataclass(frozen=True, slots=True)
class LinearEnergyDerivationReport:
    """Generic same-family combination, without thermochemical interpretation."""

    derivation_id: str
    terms: tuple[EnergyTermContribution, ...]
    compatibility: EnergyCompatibilityReport
    value_ev: float | None
    energy_family_id: str | None
    kind: VaspEnergyKind | None
    derivation_sha256: str | None
    diagnostics: tuple[Diagnostic, ...]
    scientific_interpretation_approved: bool = False
    reference_state_reviewed: bool = False
    thermochemical_corrections_included: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    additional_submission_performed: bool = False
    schema_version: str = "catex.linear-energy-derivation.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "derived" if self.value_ev is not None and not self.has_errors else "not_derived"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "derivation_id": self.derivation_id,
            "operation": "linear_combination",
            "terms": [item.to_dict() for item in self.terms],
            "compatibility": self.compatibility.to_dict(),
            "value_eV": self.value_ev,
            "energy_family_id": self.energy_family_id,
            "kind": self.kind.value if self.kind else None,
            "derivation_sha256": self.derivation_sha256,
            "scientific_interpretation_approved": self.scientific_interpretation_approved,
            "reference_state_reviewed": self.reference_state_reviewed,
            "thermochemical_corrections_included": (self.thermochemical_corrections_included),
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "additional_submission_performed": self.additional_submission_performed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
