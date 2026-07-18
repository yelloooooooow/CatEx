"""Versioned records emitted by VASP input validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from catex.models import ArtifactRecord, Diagnostic, Severity, StructureRecord


class ValidationMode(StrEnum):
    """Policy severity without changing parser truth."""

    STRICT = "strict"
    EXPLORATION = "exploration"


@dataclass(frozen=True, slots=True)
class IncarAssignment:
    tag: str
    raw_value: str
    line_start: int
    line_end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "raw_value": self.raw_value,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }


@dataclass(frozen=True, slots=True)
class IncarSummary:
    assignments: tuple[IncarAssignment, ...]
    schema_version: str = "catex.incar.v1"

    def values(self, tag: str) -> tuple[str, ...]:
        normalized = tag.upper()
        return tuple(item.raw_value for item in self.assignments if item.tag == normalized)

    def value(self, tag: str) -> str | None:
        values = self.values(tag)
        return values[-1] if values else None

    @property
    def duplicate_tags(self) -> tuple[str, ...]:
        counts: dict[str, int] = {}
        for item in self.assignments:
            counts[item.tag] = counts.get(item.tag, 0) + 1
        return tuple(sorted(tag for tag, count in counts.items() if count > 1))

    def to_dict(self) -> dict[str, Any]:
        effective = {item.tag: item.raw_value for item in self.assignments}
        return {
            "schema_version": self.schema_version,
            "effective_raw_values": dict(sorted(effective.items())),
            "duplicate_tags": list(self.duplicate_tags),
            "assignments": [item.to_dict() for item in self.assignments],
        }


@dataclass(frozen=True, slots=True)
class KpointsSummary:
    comment: str
    generation_mode: str
    automatic: bool
    subdivisions: tuple[int, int, int] | None
    shift: tuple[float, float, float] | None
    declared_point_count: int
    schema_version: str = "catex.kpoints.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "comment": self.comment,
            "generation_mode": self.generation_mode,
            "automatic": self.automatic,
            "subdivisions": list(self.subdivisions) if self.subdivisions else None,
            "shift": list(self.shift) if self.shift else None,
            "declared_point_count": self.declared_point_count,
        }


@dataclass(frozen=True, slots=True)
class PotcarDatasetMetadata:
    element: str
    potential_label: str
    titel: str
    lexch: str
    zval: float
    enmax_ev: float
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "potential_label": self.potential_label,
            "titel": self.titel,
            "lexch": self.lexch,
            "zval": self.zval,
            "enmax_eV": self.enmax_ev,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class PotcarMetadata:
    potential_family: str
    datasets: tuple[PotcarDatasetMetadata, ...]
    artifact: ArtifactRecord
    schema_version: str = "catex.potcar-metadata.v1"

    @property
    def maximum_enmax_ev(self) -> float | None:
        return max((item.enmax_ev for item in self.datasets), default=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "potential_family": self.potential_family,
            "maximum_enmax_eV": self.maximum_enmax_ev,
            "datasets": [item.to_dict() for item in self.datasets],
            "artifact": self.artifact.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class VaspInputValidationReport:
    directory: str
    mode: ValidationMode
    artifacts: tuple[ArtifactRecord, ...]
    structure: StructureRecord | None
    poscar_species_order: tuple[str, ...]
    incar: IncarSummary | None
    kpoints: KpointsSummary | None
    potcar_metadata: PotcarMetadata | None
    diagnostics: tuple[Diagnostic, ...]
    target_vasp_version: str = "5.4.4"
    schema_version: str = "catex.vasp-input-validation.v1"

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
            "mode": self.mode.value,
            "target_vasp_version": self.target_vasp_version,
            "directory": self.directory,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "structure": self.structure.to_dict() if self.structure else None,
            "poscar_species_order": list(self.poscar_species_order),
            "incar": self.incar.to_dict() if self.incar else None,
            "kpoints": self.kpoints.to_dict() if self.kpoints else None,
            "potcar_metadata": (self.potcar_metadata.to_dict() if self.potcar_metadata else None),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
