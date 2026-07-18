from __future__ import annotations

import numpy as np
from pymatgen.core import Structure

from catex.structures import ComparisonSettings, compare_paths, compare_structures


def _codes(report) -> set[str]:
    return {item.code for item in report.diagnostics}


def test_periodic_match_accepts_site_reordering_and_global_translation(nacl_structure) -> None:
    translated = nacl_structure.copy()
    translated.translate_sites(
        range(len(translated)), [0.117, 0.223, 0.319], frac_coords=True, to_unit_cell=True
    )
    reordered = Structure.from_sites(list(reversed(translated.sites)))
    original_coordinates = np.asarray(nacl_structure.frac_coords).copy()

    report = compare_structures(nacl_structure, reordered)

    assert report.equivalent
    assert report.status == "equivalent"
    assert "STRUCTURES_EQUIVALENT" in _codes(report)
    assert np.array_equal(nacl_structure.frac_coords, original_coordinates)


def test_periodic_match_rejects_composition_change(nacl_structure) -> None:
    changed = nacl_structure.copy()
    changed.replace(0, "K")

    report = compare_structures(nacl_structure, changed)

    assert not report.equivalent
    assert "COMPOSITION_MISMATCH" in _codes(report)
    assert "STRUCTURES_NOT_EQUIVALENT" in _codes(report)


def test_periodic_match_reports_site_count_mismatch(nacl_structure) -> None:
    missing_site = nacl_structure.copy()
    missing_site.remove_sites([1])

    report = compare_structures(nacl_structure, missing_site)

    assert not report.equivalent
    assert "SITE_COUNT_MISMATCH" in _codes(report)


def test_strict_site_tolerance_rejects_large_internal_displacement(nacl_structure) -> None:
    displaced = nacl_structure.copy()
    displaced.translate_sites([1], [0.25, 0.0, 0.0], frac_coords=True, to_unit_cell=True)

    report = compare_structures(
        nacl_structure,
        displaced,
        comparison_settings=ComparisonSettings(site_tolerance=0.05),
    )

    assert not report.equivalent
    assert "STRUCTURES_NOT_EQUIVALENT" in _codes(report)


def test_compare_paths_returns_error_instead_of_raising(tmp_path, nacl_structure) -> None:
    valid = tmp_path / "valid.cif"
    nacl_structure.to(filename=valid, fmt="cif")

    report = compare_paths(valid, tmp_path / "missing.cif")

    assert not report.equivalent
    assert report.has_errors
    assert "STRUCTURE_FILE_NOT_FOUND" in _codes(report)
    assert report.structure_a is not None
