"""KPOINTS parsing and dimensionality-aware validation."""

from __future__ import annotations

from pymatgen.core import Structure

from catex.models import Diagnostic, Severity
from catex.structures import inspect_structure
from catex.vasp.models import KpointsSummary, ValidationMode


def _policy(mode: ValidationMode) -> Severity:
    return Severity.ERROR if mode is ValidationMode.STRICT else Severity.WARNING


def _without_comment(line: str) -> str:
    end = len(line)
    for marker in ("!", "#"):
        position = line.find(marker)
        if position >= 0:
            end = min(end, position)
    return line[:end].strip()


def _three_ints(line: str) -> tuple[int, int, int]:
    tokens = _without_comment(line).split()
    if len(tokens) != 3:
        raise ValueError("expected exactly three integer subdivisions")
    values = tuple(int(token) for token in tokens)
    if any(value <= 0 for value in values):
        raise ValueError("subdivisions must be positive")
    return values  # type: ignore[return-value]


def _three_floats(line: str) -> tuple[float, float, float]:
    tokens = _without_comment(line).split()
    if len(tokens) != 3:
        raise ValueError("expected exactly three shift values")
    return tuple(float(token.replace("D", "E").replace("d", "e")) for token in tokens)  # type: ignore[return-value]


def parse_kpoints_text(text: str) -> tuple[KpointsSummary | None, tuple[Diagnostic, ...]]:
    """Parse the regular-mesh subset and classify other valid KPOINTS modes."""

    diagnostics: list[Diagnostic] = []
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return None, (
            Diagnostic(
                "KPOINTS_TOO_SHORT",
                Severity.ERROR,
                "KPOINTS must contain at least a comment, count, and mode line.",
            ),
        )
    comment = lines[0].strip()
    try:
        declared_count = int(_without_comment(lines[1]).split()[0])
    except (ValueError, IndexError):
        return None, (
            Diagnostic(
                "KPOINTS_COUNT_INVALID",
                Severity.ERROR,
                "The second KPOINTS line must start with an integer.",
                {"line": 2},
            ),
        )
    if declared_count < 0:
        diagnostics.append(
            Diagnostic(
                "KPOINTS_COUNT_NEGATIVE",
                Severity.ERROR,
                "The declared k-point count cannot be negative.",
            )
        )

    mode_line = _without_comment(lines[2])
    mode_initial = mode_line[:1].upper()
    if declared_count != 0:
        generation_mode = "line-mode" if mode_initial == "L" else "explicit"
        summary = KpointsSummary(
            comment=comment,
            generation_mode=generation_mode,
            automatic=False,
            subdivisions=None,
            shift=None,
            declared_point_count=declared_count,
        )
        diagnostics.append(
            Diagnostic(
                "KPOINTS_EXPLICIT_MODE_LIMITED_CHECK",
                Severity.INFO,
                "Explicit and line-mode coordinates are preserved, but PR-002 does not "
                "validate their density.",
            )
        )
        return summary, tuple(diagnostics)

    if mode_initial in {"G", "M"}:
        generation_mode = "gamma" if mode_initial == "G" else "monkhorst-pack"
        if len(lines) < 4:
            return None, (
                Diagnostic(
                    "KPOINTS_SUBDIVISIONS_MISSING",
                    Severity.ERROR,
                    "A regular automatic mesh requires three subdivisions on line four.",
                ),
            )
        try:
            subdivisions = _three_ints(lines[3])
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(
                    "KPOINTS_SUBDIVISIONS_INVALID",
                    Severity.ERROR,
                    str(exc),
                    {"line": 4},
                )
            )
            subdivisions = None
        shift = (0.0, 0.0, 0.0)
        if len(lines) >= 5:
            try:
                shift = _three_floats(lines[4])
            except ValueError as exc:
                diagnostics.append(
                    Diagnostic(
                        "KPOINTS_SHIFT_INVALID",
                        Severity.ERROR,
                        str(exc),
                        {"line": 5},
                    )
                )
                shift = None
        return (
            KpointsSummary(
                comment=comment,
                generation_mode=generation_mode,
                automatic=True,
                subdivisions=subdivisions,
                shift=shift,
                declared_point_count=declared_count,
            ),
            tuple(diagnostics),
        )

    if mode_initial == "A":
        return (
            KpointsSummary(
                comment=comment,
                generation_mode="automatic-length",
                automatic=True,
                subdivisions=None,
                shift=None,
                declared_point_count=declared_count,
            ),
            (
                Diagnostic(
                    "KPOINTS_AUTOMATIC_LENGTH_LIMITED_CHECK",
                    Severity.WARNING,
                    "Automatic-length mode cannot enforce an explicit 2D 1-point vacuum-axis mesh.",
                ),
            ),
        )

    if mode_initial in {"C", "K", "R"}:
        return (
            KpointsSummary(
                comment=comment,
                generation_mode="generalized-regular",
                automatic=True,
                subdivisions=None,
                shift=None,
                declared_point_count=declared_count,
            ),
            (
                Diagnostic(
                    "KPOINTS_GENERALIZED_MODE_LIMITED_CHECK",
                    Severity.INFO,
                    "Generalized regular meshes are not reduced to three subdivisions in PR-002.",
                ),
            ),
        )

    return None, (
        Diagnostic(
            "KPOINTS_MODE_UNSUPPORTED",
            Severity.ERROR,
            "The automatic mesh mode is not recognized.",
            {"mode_line": mode_line},
        ),
    )


def validate_kpoints(
    summary: KpointsSummary,
    structure: Structure,
    *,
    mode: ValidationMode,
    vacuum_threshold_angstrom: float = 8.0,
) -> tuple[Diagnostic, ...]:
    """Apply symmetry and slab-dimensionality rules to a parsed mesh."""

    diagnostics: list[Diagnostic] = []
    if summary.generation_mode == "monkhorst-pack" and structure.lattice.is_hexagonal():
        diagnostics.append(
            Diagnostic(
                "KPOINTS_HEXAGONAL_REQUIRES_GAMMA_CENTERING",
                _policy(mode),
                "Use a Gamma-centered mesh for a hexagonal lattice to preserve symmetry.",
            )
        )
    if (
        summary.generation_mode == "gamma"
        and summary.shift is not None
        and any(abs(value) > 1e-12 for value in summary.shift)
    ):
        diagnostics.append(
            Diagnostic(
                "KPOINTS_SHIFTED_GAMMA_MESH",
                Severity.WARNING,
                "A nonzero user shift means the stated Gamma mesh is not centered at Gamma.",
                {"shift": list(summary.shift)},
            )
        )

    inspection = inspect_structure(structure)
    estimated = (
        inspection.metrics.estimated_vacuum_angstrom if inspection.metrics is not None else None
    )
    vacuum_axes = (
        tuple(index for index, value in enumerate(estimated) if value >= vacuum_threshold_angstrom)
        if estimated is not None
        else ()
    )
    if vacuum_axes and summary.subdivisions is None:
        diagnostics.append(
            Diagnostic(
                "KPOINTS_VACUUM_AXIS_NOT_EXPLICIT",
                _policy(mode),
                "Vacuum was detected, but this KPOINTS mode has no explicit three-axis mesh.",
                {"vacuum_axes": list(vacuum_axes)},
            )
        )
    if summary.subdivisions is not None:
        for axis in vacuum_axes:
            if summary.subdivisions[axis] != 1:
                diagnostics.append(
                    Diagnostic(
                        "KPOINTS_VACUUM_AXIS_MESH_NOT_ONE",
                        _policy(mode),
                        "A slab/isolated vacuum axis should use one k-point.",
                        {
                            "axis": axis,
                            "subdivision": summary.subdivisions[axis],
                            "estimated_vacuum_angstrom": estimated[axis],
                        },
                    )
                )
            if summary.shift is not None and abs(summary.shift[axis]) > 1e-12:
                diagnostics.append(
                    Diagnostic(
                        "KPOINTS_VACUUM_AXIS_SHIFT_NONZERO",
                        _policy(mode),
                        "The vacuum-axis k-point should not have a user shift.",
                        {"axis": axis, "shift": summary.shift[axis]},
                    )
                )
    return tuple(diagnostics)
