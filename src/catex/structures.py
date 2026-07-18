"""Read-only periodic structure inspection and equivalence comparison."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.analysis.structure_matcher import SpeciesComparator, StructureMatcher
from pymatgen.core import Structure

from catex.hashing import artifact_record, structure_hash
from catex.models import (
    ArtifactRecord,
    ComparisonReport,
    Diagnostic,
    InspectionMetrics,
    InspectionReport,
    Severity,
    StructureRecord,
)


@dataclass(frozen=True, slots=True)
class InspectionSettings:
    """Thresholds for read-only geometry diagnostics."""

    close_contact_error_angstrom: float = 0.4
    close_contact_warning_angstrom: float = 0.7
    vacuum_candidate_angstrom: float = 8.0

    def __post_init__(self) -> None:
        if not 0 < self.close_contact_error_angstrom <= self.close_contact_warning_angstrom:
            raise ValueError("close-contact thresholds must be positive and ordered")
        if self.vacuum_candidate_angstrom <= 0:
            raise ValueError("vacuum threshold must be positive")


@dataclass(frozen=True, slots=True)
class ComparisonSettings:
    """Explicit tolerances passed to pymatgen's periodic StructureMatcher."""

    length_tolerance: float = 0.2
    site_tolerance: float = 0.3
    angle_tolerance_degrees: float = 5.0
    allow_uniform_scale: bool = False

    def __post_init__(self) -> None:
        if self.length_tolerance <= 0 or self.site_tolerance <= 0:
            raise ValueError("length and site tolerances must be positive")
        if self.angle_tolerance_degrees <= 0:
            raise ValueError("angle tolerance must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "length_tolerance": self.length_tolerance,
            "site_tolerance": self.site_tolerance,
            "angle_tolerance_degrees": self.angle_tolerance_degrees,
            "allow_uniform_scale": self.allow_uniform_scale,
            "primitive_cell": False,
            "attempt_supercell": False,
            "species_comparison": "exact",
        }


def _source_format(path: Path) -> str:
    name = path.name.upper()
    if name in {"POSCAR", "CONTCAR"} or name.startswith(("POSCAR.", "CONTCAR.")):
        return "vasp-poscar"
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "unknown"


def _tuple3(values: Any) -> tuple[float, float, float]:
    return tuple(float(value) for value in values)  # type: ignore[return-value]


def _build_record(
    structure: Structure,
    *,
    source_format: str,
    artifact: ArtifactRecord | None,
) -> StructureRecord:
    matrix = tuple(tuple(float(value) for value in row) for row in structure.lattice.matrix)
    counts = tuple(
        sorted((str(element), float(amount)) for element, amount in structure.composition.items())
    )
    try:
        digest: str | None = structure_hash(structure)
    except ValueError:
        digest = None
    return StructureRecord(
        source_format=source_format,
        formula=structure.composition.formula,
        reduced_formula=structure.composition.reduced_formula,
        num_sites=len(structure),
        species_counts=counts,
        lattice_matrix=matrix,
        lattice_lengths=_tuple3(structure.lattice.abc),
        lattice_angles=_tuple3(structure.lattice.angles),
        volume_angstrom3=float(structure.volume),
        charge=float(structure.charge),
        is_ordered=bool(structure.is_ordered),
        canonical_hash=digest,
        artifact=artifact,
    )


def _minimal_circular_span(values: np.ndarray) -> float:
    wrapped = np.sort(np.mod(np.asarray(values, dtype=float), 1.0))
    if len(wrapped) <= 1:
        return 0.0
    gaps = np.diff(np.concatenate((wrapped, [wrapped[0] + 1.0])))
    return float(max(0.0, 1.0 - float(np.max(gaps))))


def _geometry_metrics(structure: Structure) -> InspectionMetrics:
    num_sites = len(structure)
    minimum_distance: float | None = None
    if num_sites >= 2:
        distances = np.asarray(structure.distance_matrix, dtype=float).copy()
        np.fill_diagonal(distances, np.inf)
        finite = distances[np.isfinite(distances)]
        if finite.size:
            minimum_distance = float(np.min(finite))

    spans: tuple[float, float, float] | None = None
    vacuum: tuple[float, float, float] | None = None
    fractional = np.asarray(structure.frac_coords, dtype=float)
    if num_sites and np.isfinite(fractional).all():
        spans = _tuple3(_minimal_circular_span(fractional[:, axis]) for axis in range(3))
        cell_heights = (
            float(structure.lattice.d_hkl((1, 0, 0))),
            float(structure.lattice.d_hkl((0, 1, 0))),
            float(structure.lattice.d_hkl((0, 0, 1))),
        )
        vacuum = _tuple3((1.0 - spans[axis]) * cell_heights[axis] for axis in range(3))

    return InspectionMetrics(
        minimum_distance_angstrom=minimum_distance,
        volume_per_atom_angstrom3=(float(structure.volume) / num_sites if num_sites else None),
        occupied_span_fractions=spans,
        estimated_vacuum_angstrom=vacuum,
    )


def inspect_structure(
    structure: Structure,
    *,
    source_format: str = "in-memory",
    artifact: ArtifactRecord | None = None,
    settings: InspectionSettings | None = None,
) -> InspectionReport:
    """Inspect a periodic structure without mutating it or writing files."""

    active = settings or InspectionSettings()
    diagnostics: list[Diagnostic] = []
    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    fractional = np.asarray(structure.frac_coords, dtype=float)

    if len(structure) == 0:
        diagnostics.append(
            Diagnostic("STRUCTURE_EMPTY", Severity.ERROR, "The structure contains no sites.")
        )
    if not np.isfinite(lattice).all():
        diagnostics.append(
            Diagnostic(
                "LATTICE_NONFINITE",
                Severity.ERROR,
                "The lattice contains a NaN or infinite value.",
            )
        )
    if not np.isfinite(fractional).all():
        diagnostics.append(
            Diagnostic(
                "COORDINATES_NONFINITE",
                Severity.ERROR,
                "At least one fractional coordinate is NaN or infinite.",
            )
        )
    if not np.isfinite(structure.volume) or structure.volume <= 0:
        diagnostics.append(
            Diagnostic(
                "LATTICE_VOLUME_INVALID",
                Severity.ERROR,
                "The periodic cell volume must be finite and positive.",
                {"volume_angstrom3": float(structure.volume)},
            )
        )
    elif abs(float(np.linalg.det(lattice))) < 1e-8:
        diagnostics.append(
            Diagnostic(
                "LATTICE_NEAR_SINGULAR",
                Severity.ERROR,
                "The lattice matrix is singular or numerically unstable.",
            )
        )
    if not structure.is_ordered:
        diagnostics.append(
            Diagnostic(
                "DISORDERED_SITES_PRESENT",
                Severity.WARNING,
                "Partial occupancies require an explicit ordering decision before VASP use.",
            )
        )

    metrics = _geometry_metrics(structure)
    minimum = metrics.minimum_distance_angstrom
    if minimum is not None and minimum < active.close_contact_error_angstrom:
        diagnostics.append(
            Diagnostic(
                "CLOSE_CONTACT_ERROR",
                Severity.ERROR,
                "The minimum periodic interatomic distance is physically implausible.",
                {"distance_angstrom": minimum},
            )
        )
    elif minimum is not None and minimum < active.close_contact_warning_angstrom:
        diagnostics.append(
            Diagnostic(
                "CLOSE_CONTACT_WARNING",
                Severity.WARNING,
                "The minimum periodic interatomic distance should be reviewed.",
                {"distance_angstrom": minimum},
            )
        )

    if metrics.estimated_vacuum_angstrom is not None:
        for axis, amount in enumerate(metrics.estimated_vacuum_angstrom):
            if amount >= active.vacuum_candidate_angstrom:
                diagnostics.append(
                    Diagnostic(
                        "VACUUM_AXIS_CANDIDATE",
                        Severity.INFO,
                        "A large unoccupied periodic interval was detected along a cell axis.",
                        {"axis": axis, "estimated_vacuum_angstrom": amount},
                    )
                )

    record = _build_record(structure, source_format=source_format, artifact=artifact)
    return InspectionReport(record=record, diagnostics=tuple(diagnostics), metrics=metrics)


def _load_structure_artifact(
    source: Path,
) -> tuple[Structure | None, ArtifactRecord | None, tuple[Diagnostic, ...]]:
    """Load one stable artifact and report I/O or parse failures as diagnostics."""

    if not source.is_file():
        return (
            None,
            None,
            (
                Diagnostic(
                    "STRUCTURE_FILE_NOT_FOUND",
                    Severity.ERROR,
                    "The structure file does not exist or is not a regular file.",
                    {"path": str(source)},
                ),
            ),
        )
    try:
        artifact_before = artifact_record(source)
    except OSError as exc:
        return (
            None,
            None,
            (
                Diagnostic(
                    "STRUCTURE_READ_FAILED",
                    Severity.ERROR,
                    "The structure artifact could not be read.",
                    {"path": str(source), "exception_type": type(exc).__name__},
                ),
            ),
        )
    try:
        structure = Structure.from_file(source)
    except Exception as exc:  # pymatgen parsers expose several exception types
        return (
            None,
            artifact_before,
            (
                Diagnostic(
                    "STRUCTURE_PARSE_FAILED",
                    Severity.ERROR,
                    "pymatgen could not parse the structure artifact.",
                    {
                        "path": str(source),
                        "exception_type": type(exc).__name__,
                        "artifact_sha256": artifact_before.sha256,
                    },
                ),
            ),
        )
    try:
        artifact_after = artifact_record(source)
    except OSError as exc:
        return (
            None,
            artifact_before,
            (
                Diagnostic(
                    "STRUCTURE_READ_FAILED",
                    Severity.ERROR,
                    "The structure artifact became unreadable during parsing.",
                    {"path": str(source), "exception_type": type(exc).__name__},
                ),
            ),
        )
    if artifact_before.sha256 != artifact_after.sha256:
        return (
            None,
            artifact_after,
            (
                Diagnostic(
                    "STRUCTURE_CHANGED_DURING_READ",
                    Severity.ERROR,
                    "The artifact changed while it was being parsed; no record was accepted.",
                    {
                        "path": str(source),
                        "sha256_before": artifact_before.sha256,
                        "sha256_after": artifact_after.sha256,
                    },
                ),
            ),
        )
    return structure, artifact_after, ()


def inspect_path(
    path: str | Path, *, settings: InspectionSettings | None = None
) -> InspectionReport:
    """Read and inspect a supported structure file without modifying it."""

    source = Path(path)
    structure, artifact, diagnostics = _load_structure_artifact(source)
    if structure is None:
        return InspectionReport(record=None, metrics=None, diagnostics=diagnostics)
    return inspect_structure(
        structure,
        source_format=_source_format(source),
        artifact=artifact,
        settings=settings,
    )


def _with_side(diagnostic: Diagnostic, side: str) -> Diagnostic:
    return Diagnostic(
        diagnostic.code,
        diagnostic.severity,
        diagnostic.message,
        {**diagnostic.context, "structure_side": side},
    )


def compare_structures(
    structure_a: Structure,
    structure_b: Structure,
    *,
    artifact_a: ArtifactRecord | None = None,
    artifact_b: ArtifactRecord | None = None,
    source_format_a: str = "in-memory",
    source_format_b: str = "in-memory",
    inspection_settings: InspectionSettings | None = None,
    comparison_settings: ComparisonSettings | None = None,
) -> ComparisonReport:
    """Compare two structures with periodic boundary conditions and explicit tolerances."""

    active = comparison_settings or ComparisonSettings()
    inspected_a = inspect_structure(
        structure_a,
        artifact=artifact_a,
        source_format=source_format_a,
        settings=inspection_settings,
    )
    inspected_b = inspect_structure(
        structure_b,
        artifact=artifact_b,
        source_format=source_format_b,
        settings=inspection_settings,
    )
    diagnostics = [*(_with_side(item, "a") for item in inspected_a.diagnostics)]
    diagnostics.extend(_with_side(item, "b") for item in inspected_b.diagnostics)

    if inspected_a.has_errors or inspected_b.has_errors:
        diagnostics.append(
            Diagnostic(
                "COMPARISON_INPUT_INVALID",
                Severity.ERROR,
                "Periodic matching was skipped because an input structure has an error.",
            )
        )
        return ComparisonReport(
            structure_a=inspected_a.record,
            structure_b=inspected_b.record,
            equivalent=False,
            settings=active.to_dict(),
            diagnostics=tuple(diagnostics),
        )

    if len(structure_a) != len(structure_b):
        diagnostics.append(
            Diagnostic(
                "SITE_COUNT_MISMATCH",
                Severity.WARNING,
                "The structures contain different numbers of sites.",
                {"num_sites_a": len(structure_a), "num_sites_b": len(structure_b)},
            )
        )
    if structure_a.composition != structure_b.composition:
        diagnostics.append(
            Diagnostic(
                "COMPOSITION_MISMATCH",
                Severity.WARNING,
                "The structures have different species or occupancies.",
                {
                    "formula_a": structure_a.composition.formula,
                    "formula_b": structure_b.composition.formula,
                },
            )
        )

    matcher = StructureMatcher(
        ltol=active.length_tolerance,
        stol=active.site_tolerance,
        angle_tol=active.angle_tolerance_degrees,
        primitive_cell=False,
        scale=active.allow_uniform_scale,
        attempt_supercell=False,
        allow_subset=False,
        comparator=SpeciesComparator(),
    )
    try:
        equivalent = bool(
            matcher.fit(
                structure_a,
                structure_b,
                symmetric=True,
                skip_structure_reduction=True,
            )
        )
    except Exception as exc:
        diagnostics.append(
            Diagnostic(
                "PERIODIC_MATCH_FAILED",
                Severity.ERROR,
                "The periodic matcher could not complete the comparison.",
                {"exception_type": type(exc).__name__},
            )
        )
        equivalent = False

    rms: float | None = None
    maximum: float | None = None
    if equivalent:
        try:
            distances = matcher.get_rms_dist(structure_a, structure_b)
            if distances is not None:
                rms, maximum = (float(distances[0]), float(distances[1]))
        except Exception as exc:
            diagnostics.append(
                Diagnostic(
                    "MATCH_DISTANCE_UNAVAILABLE",
                    Severity.WARNING,
                    "Structures match, but normalized displacement metrics were unavailable.",
                    {"exception_type": type(exc).__name__},
                )
            )
        diagnostics.append(
            Diagnostic(
                "STRUCTURES_EQUIVALENT",
                Severity.INFO,
                "The structures are equivalent under the configured periodic matcher.",
            )
        )
    elif not any(item.severity is Severity.ERROR for item in diagnostics):
        diagnostics.append(
            Diagnostic(
                "STRUCTURES_NOT_EQUIVALENT",
                Severity.WARNING,
                "The structures are not equivalent under the configured tolerances.",
            )
        )

    return ComparisonReport(
        structure_a=inspected_a.record,
        structure_b=inspected_b.record,
        equivalent=equivalent,
        settings=active.to_dict(),
        diagnostics=tuple(diagnostics),
        normalized_rms_displacement=rms,
        normalized_max_displacement=maximum,
    )


def compare_paths(
    path_a: str | Path,
    path_b: str | Path,
    *,
    inspection_settings: InspectionSettings | None = None,
    comparison_settings: ComparisonSettings | None = None,
) -> ComparisonReport:
    """Load and compare two structure artifacts, returning diagnostics on read failure."""

    source_a = Path(path_a)
    source_b = Path(path_b)
    loaded: list[Structure | None] = []
    artifacts: list[ArtifactRecord | None] = []
    diagnostics: list[Diagnostic] = []
    for side, source in (("a", source_a), ("b", source_b)):
        structure, artifact, load_diagnostics = _load_structure_artifact(source)
        diagnostics.extend(_with_side(item, side) for item in load_diagnostics)
        loaded.append(structure)
        artifacts.append(artifact)

    if loaded[0] is None or loaded[1] is None:
        records: list[StructureRecord | None] = []
        for index, structure in enumerate(loaded):
            if structure is None:
                records.append(None)
                continue
            inspected = inspect_structure(
                structure,
                artifact=artifacts[index],
                source_format=_source_format((source_a, source_b)[index]),
                settings=inspection_settings,
            )
            records.append(inspected.record)
            diagnostics.extend(
                _with_side(item, ("a", "b")[index]) for item in inspected.diagnostics
            )
        return ComparisonReport(
            structure_a=records[0],
            structure_b=records[1],
            equivalent=False,
            settings=(comparison_settings or ComparisonSettings()).to_dict(),
            diagnostics=tuple(diagnostics),
        )
    return compare_structures(
        loaded[0],
        loaded[1],
        artifact_a=artifacts[0],
        artifact_b=artifacts[1],
        source_format_a=_source_format(source_a),
        source_format_b=_source_format(source_b),
        inspection_settings=inspection_settings,
        comparison_settings=comparison_settings,
    )
