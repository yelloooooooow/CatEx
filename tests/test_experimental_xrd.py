from __future__ import annotations

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from catex.experimental import (
    InMemoryStructureProvider,
    ProviderRegistry,
    StructureSourceKind,
    XRDPattern,
    XRDSearchSettings,
    parse_xrd_path,
    search_xrd_phases,
    simulate_xrd_on_grid,
)


def _nickel() -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m",
        Lattice.cubic(3.52),
        ["Ni"],
        [[0, 0, 0]],
    )


def _molybdenum() -> Structure:
    return Structure.from_spacegroup(
        "Im-3m",
        Lattice.cubic(3.15),
        ["Mo"],
        [[0, 0, 0]],
    )


def _registry() -> ProviderRegistry:
    return ProviderRegistry(
        (
            InMemoryStructureProvider(
                "synthetic",
                (
                    ("ni", _nickel(), StructureSourceKind.HYPOTHETICAL),
                    ("mo", _molybdenum(), StructureSourceKind.HYPOTHETICAL),
                ),
            ),
        )
    )


def _grid() -> np.ndarray:
    return np.linspace(20.0, 100.0, 1601)


def test_xrd_parser_handles_headers_comments_and_duplicate_angles(tmp_path) -> None:
    path = tmp_path / "pattern.xy"
    path.write_text(
        "two_theta intensity\n# synthetic\n20, 1\n21 2\n21 4\n22\t3\n23 2\n24 1\n25 0\n",
        encoding="utf-8",
    )

    pattern = parse_xrd_path(path)

    assert pattern.two_theta_degrees == (20.0, 21.0, 22.0, 23.0, 24.0, 25.0)
    assert pattern.intensity[1] == 3.0
    assert pattern.skipped_lines == 2


def test_single_phase_search_recovers_shifted_broadened_parent() -> None:
    x = _grid()
    observed = simulate_xrd_on_grid(
        _nickel(),
        x,
        wavelength="CuKa",
        shift_degrees=0.1,
        fwhm_degrees=0.2,
    )
    report = search_xrd_phases(
        XRDPattern(tuple(x), tuple(observed)),
        _registry(),
        allowed_elements=("Ni", "Mo"),
        required_elements=("Ni",),
        settings=XRDSearchSettings(
            shift_values_degrees=(-0.1, 0.0, 0.1),
            fwhm_values_degrees=(0.1, 0.2),
            maximum_phases=2,
            minimum_supported_score=0.8,
        ),
    )

    best = report.single_phase_matches[0]

    assert report.status == "hypotheses_found"
    assert best.reference_key == "synthetic:ni"
    assert best.shift_degrees == pytest.approx(0.1)
    assert best.fwhm_degrees == pytest.approx(0.2)
    assert best.evidence_score > 0.99
    assert not best.peak_evidence.unexplained_observed_degrees
    assert report.to_dict()["score_interpretation"].startswith("ranking")


def test_multiphase_search_uses_shared_nuisance_and_nonnegative_contributions() -> None:
    x = _grid()
    nickel = simulate_xrd_on_grid(
        _nickel(),
        x,
        wavelength="CuKa",
        shift_degrees=0.0,
        fwhm_degrees=0.2,
    )
    molybdenum = simulate_xrd_on_grid(
        _molybdenum(),
        x,
        wavelength="CuKa",
        shift_degrees=0.0,
        fwhm_degrees=0.2,
    )
    observed = 0.65 * nickel + 0.35 * molybdenum
    report = search_xrd_phases(
        XRDPattern(tuple(x), tuple(observed)),
        _registry(),
        allowed_elements=("Ni", "Mo"),
        required_elements=("Ni", "Mo"),
        settings=XRDSearchSettings(
            shift_values_degrees=(0.0,),
            fwhm_values_degrees=(0.2,),
            maximum_phases=2,
            complexity_penalty=0.0,
            minimum_supported_score=0.8,
        ),
    )

    best = report.combination_matches[0]

    assert set(best.reference_keys) == {"synthetic:ni", "synthetic:mo"}
    assert best.missing_required_elements == ()
    assert sum(best.diffraction_contributions) == pytest.approx(1.0)
    assert all(value >= 0 for value in best.diffraction_contributions)
    assert best.evidence_score > report.single_phase_matches[0].evidence_score
    assert "not mass or volume" in best.to_dict()["contribution_interpretation"]
