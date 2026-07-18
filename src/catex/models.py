"""Versioned, serialization-friendly domain records for the read-only core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class Severity(StrEnum):
    """Diagnostic severity independent of log levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A stable machine-readable finding with optional structured evidence."""

    code: str
    severity: Severity
    message: str
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(sorted(self.context.items()))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "context": dict(self.context),
        }


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Content-addressed record of one source artifact."""

    path: str
    sha256: str
    size_bytes: int
    schema_version: str = "catex.artifact.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class StructureRecord:
    """Deterministic summary of a parsed periodic structure."""

    source_format: str
    formula: str
    reduced_formula: str
    num_sites: int
    species_counts: tuple[tuple[str, float], ...]
    lattice_matrix: tuple[tuple[float, float, float], ...]
    lattice_lengths: tuple[float, float, float]
    lattice_angles: tuple[float, float, float]
    volume_angstrom3: float
    charge: float
    is_ordered: bool
    canonical_hash: str | None
    artifact: ArtifactRecord | None = None
    schema_version: str = "catex.structure.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_format": self.source_format,
            "formula": self.formula,
            "reduced_formula": self.reduced_formula,
            "num_sites": self.num_sites,
            "species_counts": {key: value for key, value in self.species_counts},
            "lattice": {
                "matrix_angstrom": [list(row) for row in self.lattice_matrix],
                "lengths_angstrom": list(self.lattice_lengths),
                "angles_degrees": list(self.lattice_angles),
                "volume_angstrom3": self.volume_angstrom3,
            },
            "periodic_boundary_conditions": [True, True, True],
            "charge": self.charge,
            "is_ordered": self.is_ordered,
            "canonical_hash": self.canonical_hash,
            "artifact": self.artifact.to_dict() if self.artifact else None,
        }


@dataclass(frozen=True, slots=True)
class TransformationRecord:
    """Provenance edge for a deterministic transformation.

    PR-001 defines this contract but performs no structure mutation.
    """

    operation: str
    input_hashes: tuple[str, ...]
    output_hashes: tuple[str, ...]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    implementation: str = "catex"
    schema_version: str = "catex.transformation.v1"

    def __post_init__(self) -> None:
        parameters = MappingProxyType(dict(sorted(self.parameters.items())))
        object.__setattr__(self, "parameters", parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation": self.operation,
            "input_hashes": list(self.input_hashes),
            "output_hashes": list(self.output_hashes),
            "parameters": dict(self.parameters),
            "implementation": self.implementation,
        }


@dataclass(frozen=True, slots=True)
class InspectionMetrics:
    """Numerical evidence produced by structure inspection."""

    minimum_distance_angstrom: float | None
    volume_per_atom_angstrom3: float | None
    occupied_span_fractions: tuple[float, float, float] | None
    estimated_vacuum_angstrom: tuple[float, float, float] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum_distance_angstrom": self.minimum_distance_angstrom,
            "volume_per_atom_angstrom3": self.volume_per_atom_angstrom3,
            "occupied_span_fractions": (
                list(self.occupied_span_fractions)
                if self.occupied_span_fractions is not None
                else None
            ),
            "estimated_vacuum_angstrom": (
                list(self.estimated_vacuum_angstrom)
                if self.estimated_vacuum_angstrom is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class InspectionReport:
    """Complete result of a read-only structure inspection."""

    record: StructureRecord | None
    diagnostics: tuple[Diagnostic, ...]
    metrics: InspectionMetrics | None
    schema_version: str = "catex.inspection.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        if self.has_errors:
            return "error"
        if any(item.severity is Severity.WARNING for item in self.diagnostics):
            return "warning"
        return "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "record": self.record.to_dict() if self.record else None,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    """Periodic-equivalence result and its numerical evidence."""

    structure_a: StructureRecord | None
    structure_b: StructureRecord | None
    equivalent: bool
    settings: Mapping[str, Any]
    diagnostics: tuple[Diagnostic, ...]
    normalized_rms_displacement: float | None = None
    normalized_max_displacement: float | None = None
    schema_version: str = "catex.comparison.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", MappingProxyType(dict(sorted(self.settings.items()))))

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        if self.has_errors:
            return "error"
        return "equivalent" if self.equivalent else "not_equivalent"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "equivalent": self.equivalent,
            "settings": dict(self.settings),
            "metrics": {
                "normalized_rms_displacement": self.normalized_rms_displacement,
                "normalized_max_displacement": self.normalized_max_displacement,
            },
            "structure_a": self.structure_a.to_dict() if self.structure_a else None,
            "structure_b": self.structure_b.to_dict() if self.structure_b else None,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
