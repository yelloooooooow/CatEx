"""Versioned records for deterministic, review-gated structure transformations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from pymatgen.core import Structure

from catex.models import Diagnostic, Severity


class StructureTransformationOperation(StrEnum):
    """Supported scientific structure operations."""

    DOPING = "doping"
    SET_VACUUM = "set_vacuum"
    SLAB_GENERATION = "slab_generation"
    SUBSTITUTION = "substitution"
    VACANCY = "vacancy"


class AtomMappingKind(StrEnum):
    """Strength of the atom-lineage claim."""

    BULK_EQUIVALENCE = "bulk_equivalence"
    EXACT_INDEX = "exact_index"


class TransformationReviewDecision(StrEnum):
    """Explicit human decision for one transformation product."""

    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ParentAtomLineage:
    """Parent index or bulk-equivalence class linked to child indices."""

    parent_index_0based: int
    child_indices_0based: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "parent_index_0based": self.parent_index_0based,
            "child_indices_0based": list(self.child_indices_0based),
        }


@dataclass(frozen=True, slots=True)
class StructureTransformationRecord:
    """Hash-bound provenance for one in-memory transformed structure."""

    transformation_id: str
    operation: StructureTransformationOperation
    input_canonical_sha256: str
    input_ordered_sha256: str
    output_canonical_sha256: str
    output_ordered_sha256: str
    parameters: Mapping[str, Any]
    mapping_kind: AtomMappingKind
    parent_atom_lineage: tuple[ParentAtomLineage, ...]
    removed_parent_indices_0based: tuple[int, ...]
    created_child_indices_0based: tuple[int, ...]
    exact_atom_mapping_complete: bool
    identity_sha256: str
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.structure-transformation.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(sorted(self.parameters.items()))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transformation_id": self.transformation_id,
            "operation": self.operation.value,
            "input_canonical_sha256": self.input_canonical_sha256,
            "input_ordered_sha256": self.input_ordered_sha256,
            "output_canonical_sha256": self.output_canonical_sha256,
            "output_ordered_sha256": self.output_ordered_sha256,
            "parameters": dict(self.parameters),
            "mapping_kind": self.mapping_kind.value,
            "parent_atom_lineage": [item.to_dict() for item in self.parent_atom_lineage],
            "removed_parent_indices_0based": list(self.removed_parent_indices_0based),
            "created_child_indices_0based": list(self.created_child_indices_0based),
            "exact_atom_mapping_complete": self.exact_atom_mapping_complete,
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class TransformationProduct:
    """Runtime structure paired with serializable transformation provenance."""

    structure: Structure
    record: StructureTransformationRecord
    diagnostics: tuple[Diagnostic, ...] = ()
    schema_version: str = "catex.transformation-product.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "error" if self.has_errors else "review_required"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "record": self.record.to_dict(),
            "live_structure_embedded": False,
            "writes_performed": False,
            "commands_executed": False,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class TransformationReview:
    """Human review bound to an immutable transformation identity."""

    decision: TransformationReviewDecision
    transformation_id: str
    transformation_identity_sha256: str
    reviewer: str
    reviewed_at_utc: str
    note: str
    review_sha256: str
    human_review_recorded: bool = True
    automatic_approval_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.transformation-review.v1"

    @property
    def approved(self) -> bool:
        return self.decision is TransformationReviewDecision.APPROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision": self.decision.value,
            "approved": self.approved,
            "transformation_id": self.transformation_id,
            "transformation_identity_sha256": self.transformation_identity_sha256,
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
class TransformationReadinessReport:
    """Fail-closed gate for using one transformation downstream."""

    transformation_id: str
    transformation_identity_sha256: str
    ready_for_catalyst_registration: bool
    accepted_review_sha256: str | None
    diagnostics: tuple[Diagnostic, ...]
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.transformation-readiness.v1"

    @property
    def status(self) -> str:
        return "ready" if self.ready_for_catalyst_registration else "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "transformation_id": self.transformation_id,
            "transformation_identity_sha256": self.transformation_identity_sha256,
            "ready_for_catalyst_registration": self.ready_for_catalyst_registration,
            "accepted_review_sha256": self.accepted_review_sha256,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
