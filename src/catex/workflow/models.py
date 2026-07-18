"""Versioned records for protocol resolution and generate-only execution plans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from catex.models import ArtifactRecord, Diagnostic, Severity
from catex.vasp.models import PotcarMetadata


class ReviewState(StrEnum):
    """Human scientific-review state; automation cannot approve itself."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class KpointsSpecification:
    """Explicit regular mesh supported by the first protocol registry."""

    generation_mode: str
    subdivisions: tuple[int, int, int]
    shift: tuple[float, float, float] = (0.0, 0.0, 0.0)
    comment: str = "CatEx resolved mesh"

    def to_dict(self) -> dict[str, Any]:
        return {
            "comment": self.comment,
            "generation_mode": self.generation_mode,
            "subdivisions": list(self.subdivisions),
            "shift": list(self.shift),
        }


@dataclass(frozen=True, slots=True)
class ScientificProtocol:
    """User-authored scientific settings, independent of scheduler resources."""

    protocol_id: str
    target_vasp_version: str
    incar: Mapping[str, str]
    kpoints: KpointsSpecification
    schema_version: str = "catex.scientific-protocol.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "incar", MappingProxyType(dict(sorted(self.incar.items()))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "target_vasp_version": self.target_vasp_version,
            "incar": dict(self.incar),
            "kpoints": self.kpoints.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ProtocolReview:
    """Explicit human decision bound to one resolved protocol digest."""

    state: ReviewState
    reviewer: str | None = None
    reviewed_at_utc: str | None = None
    note: str | None = None
    schema_version: str = "catex.protocol-review.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "reviewer": self.reviewer,
            "reviewed_at_utc": self.reviewed_at_utc,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ResolvedProtocol:
    """Canonical, validated VASP inputs with an energy-compatibility identity."""

    protocol_id: str
    target_vasp_version: str
    incar_values: Mapping[str, str]
    incar_text: str
    kpoints: KpointsSpecification
    kpoints_text: str
    potcar_metadata: PotcarMetadata
    energy_family_id: str
    resolved_protocol_sha256: str
    source_artifacts: tuple[ArtifactRecord, ...]
    review: ProtocolReview = field(
        default_factory=lambda: ProtocolReview(state=ReviewState.PENDING)
    )
    schema_version: str = "catex.resolved-protocol.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "incar_values", MappingProxyType(dict(sorted(self.incar_values.items())))
        )

    @property
    def approved(self) -> bool:
        return self.review.state is ReviewState.APPROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "target_vasp_version": self.target_vasp_version,
            "incar_values": dict(self.incar_values),
            "incar_text": self.incar_text,
            "kpoints": self.kpoints.to_dict(),
            "kpoints_text": self.kpoints_text,
            "potcar_metadata": self.potcar_metadata.to_dict(),
            "energy_family_id": self.energy_family_id,
            "resolved_protocol_sha256": self.resolved_protocol_sha256,
            "source_artifacts": [item.to_dict() for item in self.source_artifacts],
            "review": self.review.to_dict(),
            "approved": self.approved,
        }


@dataclass(frozen=True, slots=True)
class ProtocolResolutionReport:
    """Fallible resolution result that never writes calculation inputs."""

    protocol: ScientificProtocol | None
    resolved: ResolvedProtocol | None
    diagnostics: tuple[Diagnostic, ...]
    schema_version: str = "catex.protocol-resolution.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        if self.has_errors:
            return "error"
        if self.resolved is None:
            return "unresolved"
        return "approved" if self.resolved.approved else "review_pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "protocol": self.protocol.to_dict() if self.protocol else None,
            "resolved": self.resolved.to_dict() if self.resolved else None,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class SlurmExecutionProfile:
    """Execution resources excluded from the scientific energy family."""

    profile_id: str
    job_name: str
    partition: str
    nodes: int
    tasks_per_node: int
    cpus_per_task: int
    walltime: str
    module_loads: tuple[str, ...]
    executable: str
    mpi_plugin: str = "pmi2"
    shell_mode: str = "nonlogin"
    schema_version: str = "catex.slurm-execution-profile.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "job_name": self.job_name,
            "partition": self.partition,
            "nodes": self.nodes,
            "tasks_per_node": self.tasks_per_node,
            "cpus_per_task": self.cpus_per_task,
            "walltime": self.walltime,
            "module_loads": list(self.module_loads),
            "executable": self.executable,
            "mpi_plugin": self.mpi_plugin,
            "shell_mode": self.shell_mode,
        }


@dataclass(frozen=True, slots=True)
class SlurmClusterPolicy:
    """Site allowlist and resource ceiling used for static validation."""

    policy_id: str
    allowed_partitions: tuple[str, ...]
    allowed_modules: tuple[str, ...]
    allowed_executables: tuple[str, ...]
    allowed_mpi_plugins: tuple[str, ...]
    max_nodes: int
    max_cores_per_node: int
    max_walltime_minutes: int
    allowed_shell_modes: tuple[str, ...] = ("nonlogin",)
    schema_version: str = "catex.slurm-cluster-policy.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "allowed_partitions": list(self.allowed_partitions),
            "allowed_modules": list(self.allowed_modules),
            "allowed_executables": list(self.allowed_executables),
            "allowed_mpi_plugins": list(self.allowed_mpi_plugins),
            "max_nodes": self.max_nodes,
            "max_cores_per_node": self.max_cores_per_node,
            "max_walltime_minutes": self.max_walltime_minutes,
            "allowed_shell_modes": list(self.allowed_shell_modes),
        }


@dataclass(frozen=True, slots=True)
class SlurmScriptPlan:
    """Rendered but never executed Slurm script and its static findings."""

    profile: SlurmExecutionProfile
    policy_id: str
    script_text: str
    script_sha256: str
    diagnostics: tuple[Diagnostic, ...]
    submitted: bool = False
    schema_version: str = "catex.slurm-script-plan.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "error" if self.has_errors else "validated_not_submitted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "profile": self.profile.to_dict(),
            "policy_id": self.policy_id,
            "script_text": self.script_text,
            "script_sha256": self.script_sha256,
            "submitted": self.submitted,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class CalculationPlan:
    """In-memory plan for a new local job directory."""

    job_name: str
    job_directory: str
    destination_root: str
    poscar_artifact: ArtifactRecord
    resolved_protocol: ResolvedProtocol
    slurm: SlurmScriptPlan
    plan_sha256: str
    diagnostics: tuple[Diagnostic, ...]
    schema_version: str = "catex.calculation-plan.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def ready_for_materialization(self) -> bool:
        return not self.has_errors and self.resolved_protocol.approved and not self.slurm.has_errors

    @property
    def status(self) -> str:
        if self.has_errors:
            return "error"
        return "ready" if self.ready_for_materialization else "review_pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "job_name": self.job_name,
            "job_directory": self.job_directory,
            "destination_root": self.destination_root,
            "poscar_artifact": self.poscar_artifact.to_dict(),
            "resolved_protocol": self.resolved_protocol.to_dict(),
            "slurm": self.slurm.to_dict(),
            "plan_sha256": self.plan_sha256,
            "ready_for_materialization": self.ready_for_materialization,
            "writes_performed": False,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    """Audit result for an explicitly approved local-only write."""

    job_directory: str
    artifacts: tuple[ArtifactRecord, ...]
    diagnostics: tuple[Diagnostic, ...]
    submitted: bool = False
    potcar_materialized: bool = False
    schema_version: str = "catex.materialization.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "error" if self.has_errors else "materialized_not_submitted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "job_directory": self.job_directory,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "submitted": self.submitted,
            "potcar_materialized": self.potcar_materialized,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
