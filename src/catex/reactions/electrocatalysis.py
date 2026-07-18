"""Template-driven HER/OER free-energy analysis for the interactive workbench."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_KB_EV_PER_K = 8.617333262145e-5
_LN10 = math.log(10.0)


@dataclass(frozen=True, slots=True)
class FreeEnergyState:
    key: str
    label: str
    electron_count: int
    standard_free_energy_ev: float
    free_energy_ev: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "electron_count": self.electron_count,
            "standard_free_energy_eV": self.standard_free_energy_ev,
            "free_energy_eV": self.free_energy_ev,
        }


@dataclass(frozen=True, slots=True)
class ElectrocatalysisAnalysis:
    template_id: str
    temperature_kelvin: float
    potential_volts: float
    ph: float
    reference_electrode: str
    states: tuple[FreeEnergyState, ...]
    step_free_energies_ev: tuple[float, ...]
    potential_limiting_step: int
    limiting_potential_volts: float | None
    overpotential_volts: float | None
    descriptor_ev: float | None
    energy_family_id: str | None
    schema_version: str = "catex.electrocatalysis-analysis.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "template_id": self.template_id,
            "conditions": {
                "temperature_kelvin": self.temperature_kelvin,
                "potential_volts": self.potential_volts,
                "pH": self.ph,
                "reference_electrode": self.reference_electrode,
            },
            "states": [item.to_dict() for item in self.states],
            "step_free_energies_eV": list(self.step_free_energies_ev),
            "potential_limiting_step": self.potential_limiting_step,
            "limiting_potential_volts": self.limiting_potential_volts,
            "overpotential_volts": self.overpotential_volts,
            "descriptor_eV": self.descriptor_ev,
            "energy_family_id": self.energy_family_id,
            "provenance_preserved": True,
        }


def reaction_templates() -> list[dict[str, Any]]:
    return [
        {
            "template_id": "her-che",
            "name": "Hydrogen evolution reaction (CHE)",
            "state_keys": ["slab", "h_star"],
            "state_labels": ["*", "H*", "H₂"],
            "reservoir_keys": ["h2"],
        },
        {
            "template_id": "oer-aem-che",
            "name": "Oxygen evolution · adsorbate evolution mechanism (CHE)",
            "state_keys": ["slab", "oh_star", "o_star", "ooh_star"],
            "state_labels": ["*", "OH*", "O*", "OOH*", "O₂"],
            "reservoir_keys": ["h2", "h2o"],
        },
    ]


def analyze_electrocatalysis(
    template_id: str,
    state_energies_ev: Mapping[str, float],
    *,
    corrections_ev: Mapping[str, float] | None = None,
    h2_free_energy_ev: float | None = None,
    h2o_free_energy_ev: float | None = None,
    oer_equilibrium_free_energy_ev: float = 4.92,
    temperature_kelvin: float = 298.15,
    potential_volts: float = 0.0,
    ph: float = 0.0,
    reference_electrode: str = "RHE",
    energy_family_id: str | None = None,
) -> ElectrocatalysisAnalysis:
    """Analyze a configured HER or OER state set using the CHE convention."""

    if template_id not in {"her-che", "oer-aem-che"}:
        raise ValueError("template_id is not supported")
    if reference_electrode not in {"RHE", "SHE"}:
        raise ValueError("reference_electrode must be RHE or SHE")
    for name, value in {
        "temperature_kelvin": temperature_kelvin,
        "potential_volts": potential_volts,
        "pH": ph,
        "oer_equilibrium_free_energy_ev": oer_equilibrium_free_energy_ev,
    }.items():
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if temperature_kelvin <= 0 or not 0 <= ph <= 14:
        raise ValueError("temperature must be positive and pH must be between 0 and 14")

    corrections = corrections_ev or {}

    def corrected(key: str) -> float:
        if key not in state_energies_ev:
            raise ValueError(f"state energy is missing: {key}")
        value = float(state_energies_ev[key]) + float(corrections.get(key, 0.0))
        if not math.isfinite(value):
            raise ValueError(f"state energy is not finite: {key}")
        return value

    if h2_free_energy_ev is None or not math.isfinite(h2_free_energy_ev):
        raise ValueError("a finite H2 free energy is required")
    g_slab = corrected("slab")
    ph_shift = 0.0
    if reference_electrode == "SHE":
        ph_shift = _KB_EV_PER_K * temperature_kelvin * _LN10 * ph

    if template_id == "her-che":
        delta_h = corrected("h_star") - g_slab - 0.5 * h2_free_energy_ev
        standard = (0.0, delta_h, 0.0)
        labels = (("slab", "*"), ("h_star", "H*"), ("h2", "H₂"))
        # Reduction steps gain +eU in this CHE sign convention.
        shift = potential_volts + ph_shift
        adjusted = tuple(value + index * shift for index, value in enumerate(standard))
        descriptor = abs(delta_h)
        limiting = -descriptor
        overpotential = descriptor
    else:
        if h2o_free_energy_ev is None or not math.isfinite(h2o_free_energy_ev):
            raise ValueError("a finite H2O free energy is required for OER")
        delta_oh = corrected("oh_star") - g_slab - (h2o_free_energy_ev - 0.5 * h2_free_energy_ev)
        delta_o = corrected("o_star") - g_slab - (h2o_free_energy_ev - h2_free_energy_ev)
        delta_ooh = (
            corrected("ooh_star") - g_slab - (2.0 * h2o_free_energy_ev - 1.5 * h2_free_energy_ev)
        )
        standard = (0.0, delta_oh, delta_o, delta_ooh, oer_equilibrium_free_energy_ev)
        labels = (
            ("slab", "*"),
            ("oh_star", "OH*"),
            ("o_star", "O*"),
            ("ooh_star", "OOH*"),
            ("o2", "O₂"),
        )
        # Each oxidative PCET becomes more favorable by eU (and by pH on SHE).
        shift = potential_volts + ph_shift
        adjusted = tuple(value - index * shift for index, value in enumerate(standard))
        standard_steps = tuple(standard[index + 1] - standard[index] for index in range(4))
        limiting = max(standard_steps)
        overpotential = limiting - oer_equilibrium_free_energy_ev / 4.0
        descriptor = None

    steps = tuple(adjusted[index + 1] - adjusted[index] for index in range(len(adjusted) - 1))
    potential_limiting_step = max(range(len(steps)), key=lambda index: steps[index]) + 1
    states = tuple(
        FreeEnergyState(key, label, index, standard[index], adjusted[index])
        for index, (key, label) in enumerate(labels)
    )
    return ElectrocatalysisAnalysis(
        template_id=template_id,
        temperature_kelvin=temperature_kelvin,
        potential_volts=potential_volts,
        ph=ph,
        reference_electrode=reference_electrode,
        states=states,
        step_free_energies_ev=steps,
        potential_limiting_step=potential_limiting_step,
        limiting_potential_volts=limiting,
        overpotential_volts=overpotential,
        descriptor_ev=descriptor,
        energy_family_id=energy_family_id,
    )


__all__ = ["ElectrocatalysisAnalysis", "analyze_electrocatalysis", "reaction_templates"]
