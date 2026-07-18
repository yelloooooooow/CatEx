"""Models for deterministic adsorption placement, deduplication, and spin planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pymatgen.core import Structure

from catex.catalysis.models import AdsorptionConfiguration
from catex.models import Diagnostic, Severity
from catex.workflow import ScientificProtocol


class BindingAlignmentMode(StrEnum):
    """Rigid-body algorithm used to align molecular binding atoms."""

    KABSCH = "kabsch"
    TRANSLATION_ONLY = "translation_only"
    TWO_POINT_RIGID = "two_point_rigid"


@dataclass(frozen=True, slots=True)
class BindingAnchorPair:
    """One adsorbate binding atom linked to one site-anchor position."""

    binding_atom_index_0based: int
    site_anchor_position_0based: int

    def to_dict(self) -> dict[str, int]:
        return {
            "binding_atom_index_0based": self.binding_atom_index_0based,
            "site_anchor_position_0based": self.site_anchor_position_0based,
        }


@dataclass(frozen=True, slots=True)
class AdsorptionGenerationRecord:
    """Deterministic rigid placement provenance for one configuration candidate."""

    generation_id: str
    configuration_id: str
    configuration_identity_sha256: str
    binding_anchor_pairs: tuple[BindingAnchorPair, ...]
    height_angstrom: float
    alignment_mode: BindingAlignmentMode
    binding_alignment_rmsd_angstrom: float
    minimum_substrate_distance_angstrom: float
    alignment_tolerance_angstrom: float
    minimum_allowed_distance_angstrom: float
    identity_sha256: str
    manual_configuration_review_required: bool = True
    molecule_distorted: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.adsorption-generation.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generation_id": self.generation_id,
            "configuration_id": self.configuration_id,
            "configuration_identity_sha256": self.configuration_identity_sha256,
            "binding_anchor_pairs": [item.to_dict() for item in self.binding_anchor_pairs],
            "height_angstrom": self.height_angstrom,
            "alignment_mode": self.alignment_mode.value,
            "binding_alignment_rmsd_angstrom": self.binding_alignment_rmsd_angstrom,
            "minimum_substrate_distance_angstrom": (self.minimum_substrate_distance_angstrom),
            "alignment_tolerance_angstrom": self.alignment_tolerance_angstrom,
            "minimum_allowed_distance_angstrom": self.minimum_allowed_distance_angstrom,
            "identity_sha256": self.identity_sha256,
            "manual_configuration_review_required": (self.manual_configuration_review_required),
            "molecule_distorted": self.molecule_distorted,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class GeneratedAdsorptionConfiguration:
    """Runtime combined structure paired with configuration and generation provenance."""

    structure: Structure
    configuration: AdsorptionConfiguration
    generation: AdsorptionGenerationRecord
    schema_version: str = "catex.generated-adsorption-configuration.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "configuration": self.configuration.to_dict(),
            "generation": self.generation.to_dict(),
            "live_structure_embedded": False,
            "writes_performed": False,
            "commands_executed": False,
        }


@dataclass(frozen=True, slots=True)
class ConfigurationDeduplicationGroup:
    """One deterministic representative and its geometrically duplicate members."""

    representative_configuration_id: str
    representative_configuration_identity_sha256: str
    member_configuration_ids: tuple[str, ...]
    member_configuration_identity_sha256s: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "representative_configuration_id": self.representative_configuration_id,
            "representative_configuration_identity_sha256": (
                self.representative_configuration_identity_sha256
            ),
            "member_configuration_ids": list(self.member_configuration_ids),
            "member_configuration_identity_sha256s": list(
                self.member_configuration_identity_sha256s
            ),
        }


@dataclass(frozen=True, slots=True)
class ConfigurationDeduplicationReport:
    """Order-independent same-identity geometric deduplication result."""

    tolerance_angstrom: float
    groups: tuple[ConfigurationDeduplicationGroup, ...]
    deduplication_sha256: str
    diagnostics: tuple[Diagnostic, ...] = ()
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.configuration-deduplication.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "error" if self.has_errors else "deduplicated"

    @property
    def representative_configuration_ids(self) -> tuple[str, ...]:
        return tuple(item.representative_configuration_id for item in self.groups)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "tolerance_angstrom": self.tolerance_angstrom,
            "groups": [item.to_dict() for item in self.groups],
            "representative_configuration_ids": list(self.representative_configuration_ids),
            "deduplication_sha256": self.deduplication_sha256,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class SpinInitialization:
    """One explicit collinear VASP initial magnetic state."""

    label: str
    magnetic_moments_mu_b: tuple[float, ...]
    nupdown: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "magnetic_moments_mu_B": list(self.magnetic_moments_mu_b),
            "nupdown": self.nupdown,
        }


@dataclass(frozen=True, slots=True)
class SpinProtocolVariant:
    """Generated scientific protocol for one initial collinear spin state."""

    spin_initialization: SpinInitialization
    protocol: ScientificProtocol
    protocol_variant_sha256: str
    manual_protocol_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.spin-protocol-variant.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "spin_initialization": self.spin_initialization.to_dict(),
            "protocol": self.protocol.to_dict(),
            "protocol_variant_sha256": self.protocol_variant_sha256,
            "manual_protocol_review_required": self.manual_protocol_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class MultiSpinCalculationPlan:
    """Review-gated protocol variants for one accepted adsorption configuration."""

    configuration_id: str
    configuration_identity_sha256: str
    configuration_review_sha256s: tuple[str, ...]
    base_protocol_id: str
    variants: tuple[SpinProtocolVariant, ...]
    plan_sha256: str
    diagnostics: tuple[Diagnostic, ...] = ()
    writes_performed: bool = False
    commands_executed: bool = False
    submitted: bool = False
    schema_version: str = "catex.multi-spin-calculation-plan.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "error" if self.has_errors else "protocol_review_required"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "configuration_id": self.configuration_id,
            "configuration_identity_sha256": self.configuration_identity_sha256,
            "configuration_review_sha256s": list(self.configuration_review_sha256s),
            "base_protocol_id": self.base_protocol_id,
            "variants": [item.to_dict() for item in self.variants],
            "plan_sha256": self.plan_sha256,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "submitted": self.submitted,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
