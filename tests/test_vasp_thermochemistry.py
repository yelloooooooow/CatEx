from __future__ import annotations

import pytest

from catex.vasp.thermochemistry import harmonic_thermochemistry


def test_harmonic_thermochemistry_reports_excluded_modes_and_components() -> None:
    result = harmonic_thermochemistry(
        (
            (333.56, 41.3567, False),
            (25.0, 3.099, False),
            (100.0, 12.398, True),
        ),
        temperature_kelvin=298.15,
        low_frequency_cutoff_cm1=50.0,
    )

    assert result.included_mode_count == 1
    assert result.excluded_low_frequency_count == 1
    assert result.excluded_imaginary_count == 1
    assert result.zero_point_energy_ev == pytest.approx(0.02067835)
    assert result.free_energy_correction_ev < result.zero_point_energy_ev
    assert result.warnings == (
        "imaginary_modes_excluded",
        "low_frequency_modes_excluded",
    )


@pytest.mark.parametrize("temperature", [0.0, -1.0, float("inf")])
def test_harmonic_thermochemistry_rejects_invalid_temperature(temperature: float) -> None:
    with pytest.raises(ValueError, match="temperature_kelvin"):
        harmonic_thermochemistry((), temperature_kelvin=temperature)
