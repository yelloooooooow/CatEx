from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

from catex.models import Severity
from catex.vasp.kpoints import parse_kpoints_text, validate_kpoints
from catex.vasp.models import KpointsSummary, ValidationMode


def _codes(diagnostics) -> set[str]:
    return {item.code for item in diagnostics}


def _slab() -> Structure:
    return Structure(
        Lattice.from_parameters(4, 4, 20, 90, 90, 120),
        ["C", "C"],
        [[0.25, 0.25, 0.45], [0.75, 0.75, 0.55]],
    )


def test_parse_regular_gamma_mesh_with_default_shift() -> None:
    summary, diagnostics = parse_kpoints_text("mesh\n0\nGamma\n3 3 1\n")

    assert diagnostics == ()
    assert summary is not None
    assert summary.generation_mode == "gamma"
    assert summary.subdivisions == (3, 3, 1)
    assert summary.shift == (0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("only\n0\n", "KPOINTS_TOO_SHORT"),
        ("mesh\nnope\nGamma\n3 3 1\n", "KPOINTS_COUNT_INVALID"),
        ("mesh\n0\nGamma\n", "KPOINTS_SUBDIVISIONS_MISSING"),
        ("mesh\n0\nGamma\n3 0 1\n", "KPOINTS_SUBDIVISIONS_INVALID"),
        ("mesh\n0\nGamma\n3 3 1\n0 0\n", "KPOINTS_SHIFT_INVALID"),
        ("mesh\n0\nUnknown\n3 3 1\n", "KPOINTS_MODE_UNSUPPORTED"),
    ],
)
def test_kpoints_parse_failures_are_structured(text, code) -> None:
    _, diagnostics = parse_kpoints_text(text)

    assert code in _codes(diagnostics)


@pytest.mark.parametrize(
    ("text", "mode", "code"),
    [
        (
            "explicit\n2\nReciprocal\n0 0 0 1\n0.5 0 0 1\n",
            "explicit",
            "KPOINTS_EXPLICIT_MODE_LIMITED_CHECK",
        ),
        ("line\n10\nLine-mode\nReciprocal\n", "line-mode", "KPOINTS_EXPLICIT_MODE_LIMITED_CHECK"),
        ("auto\n0\nAutomatic\n20\n", "automatic-length", "KPOINTS_AUTOMATIC_LENGTH_LIMITED_CHECK"),
        (
            "general\n0\nReciprocal\n0.5 0 0\n",
            "generalized-regular",
            "KPOINTS_GENERALIZED_MODE_LIMITED_CHECK",
        ),
    ],
)
def test_non_regular_modes_are_classified(text, mode, code) -> None:
    summary, diagnostics = parse_kpoints_text(text)

    assert summary is not None
    assert summary.generation_mode == mode
    assert code in _codes(diagnostics)


def test_hexagonal_lattice_rejects_monkhorst_in_strict_mode() -> None:
    summary, _ = parse_kpoints_text("mesh\n0\nMonkhorst-Pack\n4 4 1\n")
    assert summary is not None

    diagnostics = validate_kpoints(summary, _slab(), mode=ValidationMode.STRICT)

    finding = next(
        item for item in diagnostics if item.code == "KPOINTS_HEXAGONAL_REQUIRES_GAMMA_CENTERING"
    )
    assert finding.severity is Severity.ERROR


def test_slab_vacuum_axis_requires_one_unshifted_point() -> None:
    summary = KpointsSummary(
        comment="mesh",
        generation_mode="gamma",
        automatic=True,
        subdivisions=(3, 3, 2),
        shift=(0.0, 0.0, 0.5),
        declared_point_count=0,
    )

    diagnostics = validate_kpoints(summary, _slab(), mode=ValidationMode.STRICT)
    codes = _codes(diagnostics)

    assert "KPOINTS_VACUUM_AXIS_MESH_NOT_ONE" in codes
    assert "KPOINTS_VACUUM_AXIS_SHIFT_NONZERO" in codes
    assert "KPOINTS_SHIFTED_GAMMA_MESH" in codes


def test_implicit_mesh_cannot_prove_slab_rule() -> None:
    summary = KpointsSummary(
        comment="auto",
        generation_mode="automatic-length",
        automatic=True,
        subdivisions=None,
        shift=None,
        declared_point_count=0,
    )

    diagnostics = validate_kpoints(summary, _slab(), mode=ValidationMode.EXPLORATION)

    finding = next(item for item in diagnostics if item.code == "KPOINTS_VACUUM_AXIS_NOT_EXPLICIT")
    assert finding.severity is Severity.WARNING
