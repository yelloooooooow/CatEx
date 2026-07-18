"""Construction and deterministic assessment of scientific production requirements."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from catex.readiness.models import (
    RequirementCategory,
    RequirementStatus,
    ScientificCaseReadinessReport,
    ScientificCaseRequirement,
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_text_evidence_sha256(text: str) -> str:
    """Hash UTF-8 text after normalizing platform-dependent line endings.

    This is intended for reviewed text evidence stored in Git. Binary artifacts and
    source files whose exact bytes are scientifically significant must continue to use
    an ordinary byte-level SHA256 instead.
    """

    if not isinstance(text, str):
        raise TypeError("text evidence must be a string")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe identifier of at most 100 characters")
    return value


def _one_line(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or any(character in value for character in "\r\n"):
        raise ValueError(f"{field} must be one line")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must be non-empty and at most {maximum} characters")
    return normalized


def _timestamp(value: str) -> None:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError("assessed_at_utc must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, _UTC_FORMAT)
    except ValueError as exc:
        raise ValueError("assessed_at_utc must be a valid UTC timestamp") from exc


def _requirement_payload(requirement: ScientificCaseRequirement) -> dict[str, Any]:
    return {
        "schema": "catex.scientific-case-requirement-content.v1",
        "requirement_id": requirement.requirement_id,
        "category": requirement.category.value,
        "description": requirement.description,
        "required": requirement.required,
        "status": requirement.status.value,
        "evidence_sha256s": list(requirement.evidence_sha256s),
        "note": requirement.note,
        "assessed_by": requirement.assessed_by,
        "assessed_at_utc": requirement.assessed_at_utc,
    }


def create_scientific_case_requirement(
    *,
    requirement_id: str,
    category: RequirementCategory,
    description: str,
    required: bool,
    status: RequirementStatus,
    evidence_sha256s: Sequence[str],
    note: str,
    assessed_by: str,
    assessed_at_utc: str,
) -> ScientificCaseRequirement:
    """Record an explicit human requirement assessment without satisfying it automatically."""

    if not isinstance(category, RequirementCategory) or not isinstance(status, RequirementStatus):
        raise ValueError("category and status must use explicit readiness enums")
    if not isinstance(required, bool):
        raise ValueError("required must be a boolean")
    if required and status is RequirementStatus.NOT_APPLICABLE:
        raise ValueError("a required requirement cannot be not_applicable")
    hashes = tuple(sorted(evidence_sha256s))
    if len(set(hashes)) != len(hashes) or any(_SHA256.fullmatch(item) is None for item in hashes):
        raise ValueError("evidence_sha256s must contain unique lowercase SHA256 values")
    if status is RequirementStatus.SATISFIED and not hashes:
        raise ValueError("satisfied requirements require at least one evidence SHA256")
    _timestamp(assessed_at_utc)
    provisional = ScientificCaseRequirement(
        requirement_id=_identifier(requirement_id, field="requirement_id"),
        category=category,
        description=_one_line(description, field="description", maximum=300),
        required=required,
        status=status,
        evidence_sha256s=hashes,
        note=_one_line(note, field="note", maximum=500),
        assessed_by=_one_line(assessed_by, field="assessed_by", maximum=100),
        assessed_at_utc=assessed_at_utc,
        identity_sha256="0" * 64,
    )
    return replace(
        provisional,
        identity_sha256=_digest(_requirement_payload(provisional)),
    )


def _valid_requirement(requirement: object) -> bool:
    try:
        _timestamp(requirement.assessed_at_utc)
        return (
            isinstance(requirement, ScientificCaseRequirement)
            and requirement.schema_version == "catex.scientific-case-requirement.v1"
            and _IDENTIFIER.fullmatch(requirement.requirement_id) is not None
            and isinstance(requirement.category, RequirementCategory)
            and isinstance(requirement.required, bool)
            and isinstance(requirement.status, RequirementStatus)
            and _one_line(requirement.description, field="description", maximum=300)
            == requirement.description
            and _one_line(requirement.note, field="note", maximum=500) == requirement.note
            and _one_line(requirement.assessed_by, field="assessed_by", maximum=100)
            == requirement.assessed_by
            and not (
                requirement.required and requirement.status is RequirementStatus.NOT_APPLICABLE
            )
            and (
                requirement.status is not RequirementStatus.SATISFIED
                or bool(requirement.evidence_sha256s)
            )
            and len(set(requirement.evidence_sha256s)) == len(requirement.evidence_sha256s)
            and tuple(sorted(requirement.evidence_sha256s)) == requirement.evidence_sha256s
            and all(_SHA256.fullmatch(item) for item in requirement.evidence_sha256s)
            and _SHA256.fullmatch(requirement.identity_sha256) is not None
            and requirement.identity_sha256 == _digest(_requirement_payload(requirement))
            and requirement.manual_assessment_recorded
            and not requirement.automatic_satisfaction_performed
            and not requirement.writes_performed
            and not requirement.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _report_payload(report: ScientificCaseReadinessReport) -> dict[str, Any]:
    return {
        "schema": "catex.scientific-case-readiness-content.v1",
        "case_id": report.case_id,
        "requirement_identity_sha256s": [item.identity_sha256 for item in report.requirements],
        "ready_for_production_planning": report.ready_for_production_planning,
        "blocking_requirement_ids": list(report.blocking_requirement_ids),
        "satisfied_requirement_ids": list(report.satisfied_requirement_ids),
        "execution_authorized": report.execution_authorized,
    }


def assess_scientific_case_readiness(
    case_id: str,
    requirements: Sequence[ScientificCaseRequirement],
) -> ScientificCaseReadinessReport:
    """Assess required evidence while keeping execution authorization permanently separate."""

    case_id_value = _identifier(case_id, field="case_id")
    candidates = tuple(requirements)
    if not candidates or any(not _valid_requirement(item) for item in candidates):
        raise ValueError("requirements must be non-empty intact assessment records")
    items = tuple(sorted(candidates, key=lambda item: item.requirement_id))
    if len({item.requirement_id for item in items}) != len(items):
        raise ValueError("requirement IDs must be unique")
    blocking = tuple(
        item.requirement_id
        for item in items
        if item.required and item.status is not RequirementStatus.SATISFIED
    )
    satisfied = tuple(
        item.requirement_id for item in items if item.status is RequirementStatus.SATISFIED
    )
    provisional = ScientificCaseReadinessReport(
        case_id=case_id_value,
        requirements=items,
        ready_for_production_planning=not blocking,
        blocking_requirement_ids=blocking,
        satisfied_requirement_ids=satisfied,
        report_sha256="0" * 64,
    )
    return replace(
        provisional,
        report_sha256=_digest(_report_payload(provisional)),
    )
