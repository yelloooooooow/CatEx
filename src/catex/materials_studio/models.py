"""Versioned records for the constrained Materials Studio adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from catex.models import (
    ArtifactRecord,
    ComparisonReport,
    Diagnostic,
    Severity,
    TransformationRecord,
)


class ManualReviewState(StrEnum):
    """Human visual-review decision for a generated structure."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class MaterialsStudioCapabilityReport:
    """Read-only inventory of the configured local runner and fixed template."""

    backend: str
    expected_version: str
    runner_available: bool
    runner_artifact: ArtifactRecord | None
    template_artifact: ArtifactRecord
    license_status: str
    execution_status: str
    supported_operations: tuple[str, ...]
    arbitrary_script_supported: bool
    diagnostics: tuple[Diagnostic, ...]
    schema_version: str = "catex.materials-studio-capability.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        if self.has_errors:
            return "unavailable"
        return "available_unverified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "backend": self.backend,
            "expected_version": self.expected_version,
            "runner_available": self.runner_available,
            "runner_artifact": (self.runner_artifact.to_dict() if self.runner_artifact else None),
            "template_artifact": self.template_artifact.to_dict(),
            "license_status": self.license_status,
            "execution_status": self.execution_status,
            "supported_operations": list(self.supported_operations),
            "arbitrary_script_supported": self.arbitrary_script_supported,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class MaterialsStudioRoundTripPlan:
    """Immutable plan containing only a fixed template and fixed output names."""

    input_artifact: ArtifactRecord
    runner_artifact: ArtifactRecord
    template_artifact: ArtifactRecord
    staging_root: str
    job_directory: str
    intermediate_xsd_path: str
    exported_cif_path: str
    backend: str = "materials_script_perl_2023"
    operation: str = "roundtrip_cif_via_xsd"
    template_id: str = "catex.ms.roundtrip-cif-via-xsd.v1"
    schema_version: str = "catex.materials-studio-roundtrip-plan.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backend": self.backend,
            "operation": self.operation,
            "template_id": self.template_id,
            "input_artifact": self.input_artifact.to_dict(),
            "runner_artifact": self.runner_artifact.to_dict(),
            "template_artifact": self.template_artifact.to_dict(),
            "staging_root": self.staging_root,
            "job_directory": self.job_directory,
            "intermediate_xsd_path": self.intermediate_xsd_path,
            "exported_cif_path": self.exported_cif_path,
            "fixed_output_names": ["roundtrip.xsd", "roundtrip.cif"],
            "arbitrary_script": False,
        }


@dataclass(frozen=True, slots=True)
class MaterialsStudioExecutionReport:
    """Side-effect report for one explicitly approved fixed-template execution."""

    return_code: int | None
    duration_seconds: float
    intermediate_xsd_created: bool
    exported_cif_created: bool
    diagnostics: tuple[Diagnostic, ...]
    schema_version: str = "catex.materials-studio-execution.v1"

    @property
    def succeeded(self) -> bool:
        return (
            self.return_code == 0
            and self.intermediate_xsd_created
            and self.exported_cif_created
            and not any(item.severity is Severity.ERROR for item in self.diagnostics)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "succeeded": self.succeeded,
            "return_code": self.return_code,
            "duration_seconds": self.duration_seconds,
            "intermediate_xsd_created": self.intermediate_xsd_created,
            "exported_cif_created": self.exported_cif_created,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class MaterialsStudioRoundTripReport:
    """Independent structural audit plus mandatory manual-review state."""

    plan: MaterialsStudioRoundTripPlan
    execution: MaterialsStudioExecutionReport | None
    output_artifacts: tuple[ArtifactRecord, ...]
    comparison: ComparisonReport | None
    source_to_exported_site_mapping: tuple[int, ...] | None
    transformation: TransformationRecord | None
    manual_review_state: ManualReviewState
    diagnostics: tuple[Diagnostic, ...]
    schema_version: str = "catex.materials-studio-roundtrip.v1"

    @property
    def has_errors(self) -> bool:
        local_errors = any(item.severity is Severity.ERROR for item in self.diagnostics)
        comparison_errors = self.comparison.has_errors if self.comparison else False
        return local_errors or comparison_errors

    @property
    def ready_for_downstream(self) -> bool:
        return (
            self.execution is not None
            and self.execution.succeeded
            and self.comparison is not None
            and self.comparison.equivalent
            and self.source_to_exported_site_mapping is not None
            and self.manual_review_state is ManualReviewState.APPROVED
            and not self.has_errors
        )

    @property
    def status(self) -> str:
        if self.has_errors:
            return "error"
        if self.ready_for_downstream:
            return "approved"
        return "review_required"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready_for_downstream": self.ready_for_downstream,
            "manual_review_state": self.manual_review_state.value,
            "plan": self.plan.to_dict(),
            "execution": self.execution.to_dict() if self.execution else None,
            "output_artifacts": [item.to_dict() for item in self.output_artifacts],
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "source_to_exported_site_mapping": (
                list(self.source_to_exported_site_mapping)
                if self.source_to_exported_site_mapping is not None
                else None
            ),
            "transformation": self.transformation.to_dict() if self.transformation else None,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
