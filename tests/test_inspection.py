from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

from catex.models import Severity
from catex.structures import InspectionSettings, inspect_path, inspect_structure


def _codes(report) -> set[str]:
    return {item.code for item in report.diagnostics}


def test_inspection_summarizes_valid_periodic_structure(nacl_structure) -> None:
    report = inspect_structure(nacl_structure)

    assert report.status == "ok"
    assert report.record is not None
    assert report.record.reduced_formula == "NaCl"
    assert report.record.num_sites == 2
    assert report.record.canonical_hash is not None
    assert report.metrics is not None
    assert report.metrics.minimum_distance_angstrom is not None
    assert not report.has_errors


def test_inspection_reports_physically_implausible_contact() -> None:
    structure = Structure(
        Lattice.cubic(10.0),
        ["H", "H"],
        [[0.0, 0.0, 0.0], [0.02, 0.0, 0.0]],
    )

    report = inspect_structure(structure)

    assert "CLOSE_CONTACT_ERROR" in _codes(report)
    assert report.has_errors


def test_close_contact_thresholds_are_explicit() -> None:
    structure = Structure(
        Lattice.cubic(10.0),
        ["H", "H"],
        [[0.0, 0.0, 0.0], [0.05, 0.0, 0.0]],
    )
    settings = InspectionSettings(
        close_contact_error_angstrom=0.2,
        close_contact_warning_angstrom=0.6,
    )

    report = inspect_structure(structure, settings=settings)

    warning = next(item for item in report.diagnostics if item.code == "CLOSE_CONTACT_WARNING")
    assert warning.severity is Severity.WARNING


def test_slab_like_cell_reports_vacuum_candidate() -> None:
    slab = Structure(
        Lattice.from_parameters(4.0, 4.0, 20.0, 90, 90, 90),
        ["C", "C"],
        [[0.25, 0.25, 0.45], [0.75, 0.75, 0.55]],
    )

    report = inspect_structure(slab)

    findings = [item for item in report.diagnostics if item.code == "VACUUM_AXIS_CANDIDATE"]
    assert any(item.context["axis"] == 2 for item in findings)
    assert report.metrics is not None
    assert report.metrics.estimated_vacuum_angstrom is not None
    assert report.metrics.estimated_vacuum_angstrom[2] == pytest.approx(18.0)


def test_inspect_path_is_read_only(tmp_path, nacl_structure) -> None:
    source = tmp_path / "POSCAR"
    nacl_structure.to(filename=source, fmt="poscar")
    before = source.read_bytes()

    report = inspect_path(source)

    assert report.record is not None
    assert report.record.artifact is not None
    assert report.record.source_format == "vasp-poscar"
    assert source.read_bytes() == before


def test_missing_path_returns_structured_error(tmp_path) -> None:
    report = inspect_path(tmp_path / "missing.cif")

    assert report.status == "error"
    assert report.record is None
    assert _codes(report) == {"STRUCTURE_FILE_NOT_FOUND"}


def test_invalid_structure_file_returns_parse_diagnostic(tmp_path) -> None:
    source = tmp_path / "broken.cif"
    source.write_text("this is not a CIF", encoding="utf-8")

    report = inspect_path(source)

    assert report.status == "error"
    assert report.record is None
    assert _codes(report) == {"STRUCTURE_PARSE_FAILED"}
    assert report.diagnostics[0].context["artifact_sha256"]
