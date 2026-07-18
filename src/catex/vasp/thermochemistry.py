"""Small, explicit harmonic-vibration thermochemistry utilities."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_KB_EV_PER_K = 8.617333262145e-5


@dataclass(frozen=True, slots=True)
class HarmonicThermochemistryResult:
    """Harmonic correction from a declared set of VASP mode energies."""

    temperature_kelvin: float
    low_frequency_cutoff_cm1: float
    included_mode_count: int
    excluded_low_frequency_count: int
    excluded_imaginary_count: int
    zero_point_energy_ev: float
    thermal_vibrational_energy_ev: float
    entropy_ev_per_kelvin: float
    entropy_term_ev: float
    free_energy_correction_ev: float
    warnings: tuple[str, ...]
    schema_version: str = "catex.harmonic-thermochemistry.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model": "harmonic_vibration",
            "temperature_kelvin": self.temperature_kelvin,
            "low_frequency_cutoff_cm-1": self.low_frequency_cutoff_cm1,
            "included_mode_count": self.included_mode_count,
            "excluded_low_frequency_count": self.excluded_low_frequency_count,
            "excluded_imaginary_count": self.excluded_imaginary_count,
            "zero_point_energy_eV": self.zero_point_energy_ev,
            "thermal_vibrational_energy_eV": self.thermal_vibrational_energy_ev,
            "entropy_eV_per_kelvin": self.entropy_ev_per_kelvin,
            "entropy_term_eV": self.entropy_term_ev,
            "free_energy_correction_eV": self.free_energy_correction_ev,
            "warnings": list(self.warnings),
        }


def harmonic_thermochemistry(
    modes: Iterable[tuple[float, float, bool]],
    *,
    temperature_kelvin: float = 298.15,
    low_frequency_cutoff_cm1: float = 50.0,
) -> HarmonicThermochemistryResult:
    """Calculate ``ZPE + U_vib(T) - T*S_vib(T)`` from ``(cm-1, meV, imaginary)`` modes.

    Imaginary modes and real modes below the declared cutoff are excluded and counted. This
    function intentionally does not add gas translation or rotation; those require a separate
    molecular standard-state model.
    """

    if not math.isfinite(temperature_kelvin) or temperature_kelvin <= 0:
        raise ValueError("temperature_kelvin must be finite and positive")
    if not math.isfinite(low_frequency_cutoff_cm1) or low_frequency_cutoff_cm1 < 0:
        raise ValueError("low_frequency_cutoff_cm1 must be finite and non-negative")

    included: list[float] = []
    excluded_low = 0
    excluded_imaginary = 0
    for wavenumber_cm1, energy_mev, imaginary in modes:
        if not all(math.isfinite(value) for value in (wavenumber_cm1, energy_mev)):
            raise ValueError("mode values must be finite")
        if imaginary:
            excluded_imaginary += 1
            continue
        if wavenumber_cm1 < low_frequency_cutoff_cm1 or energy_mev <= 0:
            excluded_low += 1
            continue
        included.append(energy_mev / 1000.0)

    kbt = _KB_EV_PER_K * temperature_kelvin
    zpe = 0.5 * sum(included)
    thermal = 0.0
    entropy = 0.0
    for quantum_ev in included:
        x = quantum_ev / kbt
        if x < 700:
            occupation = 1.0 / math.expm1(x)
            thermal += quantum_ev * occupation
            entropy += _KB_EV_PER_K * (x * occupation - math.log1p(-math.exp(-x)))

    warnings: list[str] = []
    if excluded_imaginary:
        warnings.append("imaginary_modes_excluded")
    if excluded_low:
        warnings.append("low_frequency_modes_excluded")
    if not included:
        warnings.append("no_modes_included")
    entropy_term = temperature_kelvin * entropy
    return HarmonicThermochemistryResult(
        temperature_kelvin=temperature_kelvin,
        low_frequency_cutoff_cm1=low_frequency_cutoff_cm1,
        included_mode_count=len(included),
        excluded_low_frequency_count=excluded_low,
        excluded_imaginary_count=excluded_imaginary,
        zero_point_energy_ev=zpe,
        thermal_vibrational_energy_ev=thermal,
        entropy_ev_per_kelvin=entropy,
        entropy_term_ev=entropy_term,
        free_energy_correction_ev=zpe + thermal - entropy_term,
        warnings=tuple(warnings),
    )


__all__ = ["HarmonicThermochemistryResult", "harmonic_thermochemistry"]
