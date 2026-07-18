"""Versioned scientific identities for generic periodic catalysis models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from catex.models import Diagnostic, Severity


class CatalystModelKind(StrEnum):
    """Broad periodic model classes without chemistry-specific hard-coding."""

    BULK = "bulk"
    INTERFACE = "interface"
    OTHER_PERIODIC = "other_periodic"
    SLAB = "slab"


class StructureOrigin(StrEnum):
    """How a catalyst structure entered the platform."""

    EXTERNAL_IMPORT = "external_import"
    GENERATED = "generated"
    TRANSFORMED = "transformed"


class SiteKind(StrEnum):
    """Topology label that does not prescribe a particular catalyst family."""

    ATOP = "atop"
    BRIDGE = "bridge"
    CUSTOM = "custom"
    DEFECT = "defect"
    HOLLOW = "hollow"
    MULTI_CENTER = "multi_center"


class AdsorptionPlacementKind(StrEnum):
    """Provenance of a supplied initial adsorption geometry."""

    EXTERNAL_IMPORT = "external_import"
    MANUAL = "manual"
    RULE_BASED = "rule_based"


class IdentitySubjectKind(StrEnum):
    """Scientific identity classes that can receive explicit review."""

    ADSORBATE = "adsorbate"
    ADSORPTION_CONFIGURATION = "adsorption_configuration"
    CATALYST = "catalyst"
    SITE = "site"


class IdentityReviewDecision(StrEnum):
    """Explicit human decision for one immutable scientific identity."""

    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CatalystSystem:
    """Periodic catalyst identity bound to both canonical and ordered structure hashes."""

    catalyst_id: str
    model_kind: CatalystModelKind
    structure_origin: StructureOrigin
    formula: str
    num_sites: int
    charge_e: float
    canonical_structure_sha256: str
    ordered_structure_sha256: str
    source_artifact_sha256: str | None
    transformation_sha256s: tuple[str, ...]
    identity_sha256: str
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.catalyst-system.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "catalyst_id": self.catalyst_id,
            "model_kind": self.model_kind.value,
            "structure_origin": self.structure_origin.value,
            "formula": self.formula,
            "num_sites": self.num_sites,
            "charge_e": self.charge_e,
            "canonical_structure_sha256": self.canonical_structure_sha256,
            "ordered_structure_sha256": self.ordered_structure_sha256,
            "source_artifact_sha256": self.source_artifact_sha256,
            "transformation_sha256s": list(self.transformation_sha256s),
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class SiteDefinition:
    """Active-site identity whose atom indices are bound to an ordered structure."""

    site_id: str
    catalyst_id: str
    catalyst_identity_sha256: str
    ordered_structure_sha256: str
    kind: SiteKind
    anchor_indices_0based: tuple[int, ...]
    anchor_species: tuple[str, ...]
    anchor_fractional_coordinates_wrapped: tuple[tuple[float, float, float], ...]
    fractional_centroid_wrapped: tuple[float, float, float]
    identity_sha256: str
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.site-definition.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "site_id": self.site_id,
            "catalyst_id": self.catalyst_id,
            "catalyst_identity_sha256": self.catalyst_identity_sha256,
            "ordered_structure_sha256": self.ordered_structure_sha256,
            "kind": self.kind.value,
            "anchor_indices_0based": list(self.anchor_indices_0based),
            "anchor_species": list(self.anchor_species),
            "anchor_fractional_coordinates_wrapped": [
                list(item) for item in self.anchor_fractional_coordinates_wrapped
            ],
            "fractional_centroid_wrapped": list(self.fractional_centroid_wrapped),
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class Adsorbate:
    """Ordered molecular adsorbate identity with explicit charge, spin, and binding atoms."""

    adsorbate_id: str
    formula: str
    species_in_order: tuple[str, ...]
    charge_e: int
    spin_multiplicity: int
    binding_atom_indices_0based: tuple[int, ...]
    stereochemistry_label: str
    geometry_sha256: str
    identity_sha256: str
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.adsorbate.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "adsorbate_id": self.adsorbate_id,
            "formula": self.formula,
            "species_in_order": list(self.species_in_order),
            "charge_e": self.charge_e,
            "spin_multiplicity": self.spin_multiplicity,
            "binding_atom_indices_0based": list(self.binding_atom_indices_0based),
            "stereochemistry_label": self.stereochemistry_label,
            "geometry_sha256": self.geometry_sha256,
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class AdsorptionConfiguration:
    """One supplied single-adsorbate periodic geometry with explicit atom mappings."""

    configuration_id: str
    catalyst_id: str
    catalyst_identity_sha256: str
    site_id: str
    site_identity_sha256: str
    adsorbate_id: str
    adsorbate_identity_sha256: str
    placement_kind: AdsorptionPlacementKind
    combined_structure_canonical_sha256: str
    combined_structure_ordered_sha256: str
    substrate_indices_0based: tuple[int, ...]
    adsorbate_indices_0based: tuple[int, ...]
    binding_distances_angstrom: tuple[tuple[float, ...], ...]
    minimum_binding_distance_angstrom: float
    maximum_binding_distance_angstrom: float
    identity_sha256: str
    single_adsorbate_only: bool = True
    manual_review_required: bool = True
    scientific_identity_approved: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.adsorption-configuration.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "configuration_id": self.configuration_id,
            "catalyst_id": self.catalyst_id,
            "catalyst_identity_sha256": self.catalyst_identity_sha256,
            "site_id": self.site_id,
            "site_identity_sha256": self.site_identity_sha256,
            "adsorbate_id": self.adsorbate_id,
            "adsorbate_identity_sha256": self.adsorbate_identity_sha256,
            "placement_kind": self.placement_kind.value,
            "combined_structure_canonical_sha256": (self.combined_structure_canonical_sha256),
            "combined_structure_ordered_sha256": self.combined_structure_ordered_sha256,
            "substrate_indices_0based": list(self.substrate_indices_0based),
            "adsorbate_indices_0based": list(self.adsorbate_indices_0based),
            "binding_distances_angstrom": [list(item) for item in self.binding_distances_angstrom],
            "minimum_binding_distance_angstrom": self.minimum_binding_distance_angstrom,
            "maximum_binding_distance_angstrom": self.maximum_binding_distance_angstrom,
            "identity_sha256": self.identity_sha256,
            "single_adsorbate_only": self.single_adsorbate_only,
            "manual_review_required": self.manual_review_required,
            "scientific_identity_approved": self.scientific_identity_approved,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ScientificIdentityReview:
    """Explicit review bound to one immutable catalysis-domain identity."""

    decision: IdentityReviewDecision
    subject_kind: IdentitySubjectKind
    subject_id: str
    subject_identity_sha256: str
    reviewer: str
    reviewed_at_utc: str
    note: str
    review_sha256: str
    human_review_recorded: bool = True
    automatic_approval_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.scientific-identity-review.v1"

    @property
    def approved(self) -> bool:
        return self.decision is IdentityReviewDecision.APPROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision": self.decision.value,
            "approved": self.approved,
            "subject_kind": self.subject_kind.value,
            "subject_id": self.subject_id,
            "subject_identity_sha256": self.subject_identity_sha256,
            "reviewer": self.reviewer,
            "reviewed_at_utc": self.reviewed_at_utc,
            "note": self.note,
            "review_sha256": self.review_sha256,
            "human_review_recorded": self.human_review_recorded,
            "automatic_approval_performed": self.automatic_approval_performed,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ConfigurationReadinessReport:
    """Fail-closed review gate before an adsorption configuration enters planning."""

    configuration_id: str
    configuration_identity_sha256: str
    ready_for_calculation_planning: bool
    required_subject_kinds: tuple[IdentitySubjectKind, ...]
    accepted_review_sha256s: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.configuration-readiness.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "ready" if self.ready_for_calculation_planning else "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "configuration_id": self.configuration_id,
            "configuration_identity_sha256": self.configuration_identity_sha256,
            "ready_for_calculation_planning": self.ready_for_calculation_planning,
            "required_subject_kinds": [item.value for item in self.required_subject_kinds],
            "accepted_review_sha256s": list(self.accepted_review_sha256s),
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
