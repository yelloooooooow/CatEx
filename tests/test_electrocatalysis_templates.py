from __future__ import annotations

import pytest

from catex.reactions.electrocatalysis import analyze_electrocatalysis, reaction_templates


def test_her_template_returns_descriptor_and_two_steps() -> None:
    report = analyze_electrocatalysis(
        "her-che",
        {"slab": -100.0, "h_star": -103.5},
        h2_free_energy_ev=-6.8,
    )

    assert report.descriptor_ev == pytest.approx(0.1)
    assert report.overpotential_volts == pytest.approx(0.1)
    assert report.step_free_energies_ev == pytest.approx((-0.1, 0.1))
    assert report.potential_limiting_step == 2


def test_oer_template_builds_five_state_che_landscape() -> None:
    report = analyze_electrocatalysis(
        "oer-aem-che",
        {
            "slab": -100.0,
            "oh_star": -106.0,
            "o_star": -104.0,
            "ooh_star": -107.0,
        },
        h2_free_energy_ev=-6.8,
        h2o_free_energy_ev=-14.2,
        potential_volts=1.23,
        reference_electrode="RHE",
        energy_family_id="family-1",
    )

    assert len(report.states) == 5
    assert len(report.step_free_energies_ev) == 4
    assert report.energy_family_id == "family-1"
    assert report.states[-1].free_energy_ev == pytest.approx(0.0)
    assert report.overpotential_volts is not None


def test_templates_declare_required_states_and_reservoirs() -> None:
    templates = {item["template_id"]: item for item in reaction_templates()}

    assert templates["her-che"]["state_keys"] == ["slab", "h_star"]
    assert templates["oer-aem-che"]["state_keys"] == [
        "slab",
        "oh_star",
        "o_star",
        "ooh_star",
    ]
