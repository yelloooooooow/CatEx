"""Typed scientific-case requirements and non-authorizing readiness reports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RequirementCategory(StrEnum):
    """Cross-cutting evidence classes for production scientific work."""

    EXECUTION = "execution"
    PROTOCOL = "protocol"
    REACTION_NETWORK = "reaction_network"
    REFERENCE_DATA = "reference_data"
    RESULTS = "results"
    STORAGE = "storage"
    STRUCTURE = "structure"
    THERMOCHEMISTRY = "thermochemistry"


class RequirementStatus(StrEnum):
    """Explicit audit status; blocked is never silently converted to satisfied."""

    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"
    SATISFIED = "satisfied"


@dataclass(frozen=True, slots=True)
class ScientificCaseRequirement:
    """Hash-bound human assessment of one production requirement."""

    requirement_id: str
    category: RequirementCategory
    description: str
    required: bool
    status: RequirementStatus
    evidence_sha256s: tuple[str, ...]
    note: str
    assessed_by: str
    assessed_at_utc: str
    identity_sha256: str
    manual_assessment_recorded: bool = True
    automatic_satisfaction_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.scientific-case-requirement.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "requirement_id": self.requirement_id,
            "category": self.category.value,
            "description": self.description,
            "required": self.required,
            "status": self.status.value,
            "evidence_sha256s": list(self.evidence_sha256s),
            "note": self.note,
            "assessed_by": self.assessed_by,
            "assessed_at_utc": self.assessed_at_utc,
            "identity_sha256": self.identity_sha256,
            "manual_assessment_recorded": self.manual_assessment_recorded,
            "automatic_satisfaction_performed": self.automatic_satisfaction_performed,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ScientificCaseReadinessReport:
    """Deterministic production-readiness gate that never authorizes execution."""

    case_id: str
    requirements: tuple[ScientificCaseRequirement, ...]
    ready_for_production_planning: bool
    blocking_requirement_ids: tuple[str, ...]
    satisfied_requirement_ids: tuple[str, ...]
    report_sha256: str
    execution_authorized: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.scientific-case-readiness.v1"

    @property
    def status(self) -> str:
        return "ready" if self.ready_for_production_planning else "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "case_id": self.case_id,
            "requirements": [item.to_dict() for item in self.requirements],
            "ready_for_production_planning": self.ready_for_production_planning,
            "blocking_requirement_ids": list(self.blocking_requirement_ids),
            "satisfied_requirement_ids": list(self.satisfied_requirement_ids),
            "report_sha256": self.report_sha256,
            "execution_authorized": self.execution_authorized,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }
