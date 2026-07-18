from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from test_catalysis_identities import _domain_chain
from test_energy_compatibility import _accepted_energy

from catex.energetics import VaspEnergyKind
from catex.reactions import (
    ChemicalPhase,
    CorrectionSourceKind,
    DefinitionSubjectKind,
    ImaginaryModePolicy,
    LowFrequencyTreatment,
    ReactionPurpose,
    StandardState,
    StateStoichiometry,
    bind_state_energy,
    create_adsorbate_state,
    create_adsorption_state,
    create_catalyst_state,
    create_external_reference_state,
    create_reference_state_set,
    create_thermochemical_correction,
    create_thermochemistry_protocol,
    define_reaction,
    derive_reaction_electronic_energy,
    derive_reaction_free_energy,
    record_definition_review,
)


def _approved(subject):
    return record_definition_review(
        subject,
        accepted=True,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-16T07:00:00Z",
        note="Synthetic definition review.",
    )


def _electronic_chain(tmp_path: Path, *, gas_family: str = "d"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    _, catalyst, _, _, adsorbate, _, configuration = _domain_chain()
    surface = create_catalyst_state(catalyst, state_id="surface")
    gas = create_adsorbate_state(
        adsorbate,
        state_id="co-gas",
        phase=ChemicalPhase.GAS,
    )
    adsorbed = create_adsorption_state(
        catalyst,
        adsorbate,
        configuration,
        state_id="co-adsorbed",
    )
    references = create_reference_state_set(
        (surface, gas),
        reference_set_id="adsorption-references",
    )
    definition = define_reaction(
        (
            StateStoichiometry(surface, -1),
            StateStoichiometry(gas, -1),
            StateStoichiometry(adsorbed, 1),
        ),
        reaction_id="co-adsorption",
        purpose=ReactionPurpose.ADSORPTION,
        reference_set=references,
    )
    assert definition.reaction is not None
    surface_energy, _, _, _ = _accepted_energy(
        tmp_path / "surface-energy",
        energy_id="surface-energy",
    )
    gas_energy, _, _, _ = _accepted_energy(
        tmp_path / "gas-energy",
        energy_id="gas-energy",
        family_hex=gas_family,
    )
    adsorbed_energy, _, _, _ = _accepted_energy(
        tmp_path / "adsorbed-energy",
        energy_id="adsorbed-energy",
    )
    bindings = (
        bind_state_energy(surface, surface_energy, binding_id="surface-binding"),
        bind_state_energy(gas, gas_energy, binding_id="gas-binding"),
        bind_state_energy(adsorbed, adsorbed_energy, binding_id="adsorbed-binding"),
    )
    reviews = tuple(
        _approved(item)
        for item in (
            surface,
            gas,
            adsorbed,
            references,
            definition.reaction,
            *bindings,
        )
    )
    electronic = derive_reaction_electronic_energy(
        definition.reaction,
        bindings,
        reviews,
    )
    return (
        (surface, gas, adsorbed),
        references,
        definition.reaction,
        bindings,
        reviews,
        electronic,
    )


def _thermochemistry(states):
    surface, gas, adsorbed = states
    protocol = create_thermochemistry_protocol(
        protocol_id="thermo-298k",
        temperature_kelvin=298.15,
        low_frequency_treatment=LowFrequencyTreatment.HARMONIC,
        imaginary_mode_policy=ImaginaryModePolicy.REJECT,
    )
    corrections = (
        create_thermochemical_correction(
            surface,
            protocol,
            correction_id="surface-correction",
            standard_state=StandardState.SURFACE_SITE,
            source_kind=CorrectionSourceKind.EXPLICIT_ASSUMPTION,
            source_reference="Synthetic zero surface correction.",
            source_sha256s=("1" * 64,),
            zero_point_energy_ev=0.0,
            thermal_enthalpy_ev=0.0,
            entropy_ev_per_kelvin=0.0,
        ),
        create_thermochemical_correction(
            gas,
            protocol,
            correction_id="gas-correction",
            standard_state=StandardState.GAS_1_BAR,
            source_kind=CorrectionSourceKind.TABULATED,
            source_reference="Synthetic gas thermochemistry.",
            source_sha256s=("2" * 64,),
            zero_point_energy_ev=0.1,
            thermal_enthalpy_ev=0.05,
            entropy_ev_per_kelvin=0.001,
        ),
        create_thermochemical_correction(
            adsorbed,
            protocol,
            correction_id="adsorbed-correction",
            standard_state=StandardState.SURFACE_SITE,
            source_kind=CorrectionSourceKind.FREQUENCY_ANALYSIS,
            source_reference="Synthetic adsorbate frequencies.",
            source_sha256s=("3" * 64,),
            zero_point_energy_ev=0.2,
            thermal_enthalpy_ev=0.02,
            entropy_ev_per_kelvin=0.0002,
        ),
    )
    reviews = tuple(_approved(item) for item in (protocol, *corrections))
    return protocol, corrections, reviews


def test_adsorption_reaction_uses_shared_balanced_core_and_explicit_references(
    tmp_path: Path,
) -> None:
    states, references, reaction, bindings, reviews, electronic = _electronic_chain(tmp_path)
    reordered_definition = define_reaction(
        tuple(
            StateStoichiometry(state, coefficient)
            for state, coefficient in reversed(tuple(zip(states, (-1, -1, 1), strict=True)))
        ),
        reaction_id="co-adsorption",
        purpose=ReactionPurpose.ADSORPTION,
        reference_set=references,
    )
    reordered_electronic = derive_reaction_electronic_energy(
        reaction,
        tuple(reversed(bindings)),
        tuple(reversed(reviews)),
    )

    assert reaction.purpose is ReactionPurpose.ADSORPTION
    assert reaction.element_and_charge_balanced is True
    assert reaction.reference_set_identity_sha256 == references.identity_sha256
    assert {item.state_id: item.coefficient.fraction for item in reaction.terms} == {
        "surface": -1,
        "co-gas": -1,
        "co-adsorbed": 1,
    }
    assert reordered_definition.reaction == reaction
    assert reordered_electronic.derivation_sha256 == electronic.derivation_sha256
    assert electronic.status == "derived"
    assert electronic.property_kind == "adsorption_electronic_energy"
    assert electronic.value_ev == pytest.approx(10.25)
    assert electronic.energy_family_id == bindings[0].reviewed_energy.energy_family_id
    assert electronic.kind is VaspEnergyKind.FREE_ENERGY_TOTEN
    assert electronic.stoichiometry_reviewed is True
    assert electronic.reference_states_reviewed is True
    assert electronic.thermochemical_corrections_included is False
    assert len(electronic.accepted_review_sha256s) == 8
    assert {item.state_id for item in states} == {"surface", "co-gas", "co-adsorbed"}
    assert "path" not in json.dumps(electronic.to_dict()).lower()
    assert reviews


def test_unbalanced_reactions_never_emit_a_reaction_definition() -> None:
    _, catalyst, _, _, adsorbate, _, configuration = _domain_chain()
    surface = create_catalyst_state(catalyst, state_id="surface")
    adsorbed = create_adsorption_state(
        catalyst,
        adsorbate,
        configuration,
        state_id="adsorbed",
    )

    report = define_reaction(
        (StateStoichiometry(surface, -1), StateStoichiometry(adsorbed, 1)),
        reaction_id="missing-adsorbate",
        purpose=ReactionPurpose.GENERIC,
    )

    assert report.status == "error"
    assert report.reaction is None
    assert "REACTION_ELEMENT_UNBALANCED" in {item.code for item in report.diagnostics}


def test_charge_balance_supports_explicit_proton_and_electron_states() -> None:
    proton = create_external_reference_state(
        state_id="proton",
        reference_id="proton-reference",
        provenance_sha256="a" * 64,
        formula="H",
        formal_charge_e=1,
        phase=ChemicalPhase.SOLVATED,
    )
    electron = create_external_reference_state(
        state_id="electron",
        reference_id="electron-reference",
        provenance_sha256="b" * 64,
        formula="",
        formal_charge_e=-1,
        phase=ChemicalPhase.ELECTRON,
    )
    hydrogen = create_external_reference_state(
        state_id="hydrogen-atom",
        reference_id="hydrogen-reference",
        provenance_sha256="c" * 64,
        formula="H",
        formal_charge_e=0,
        phase=ChemicalPhase.GAS,
    )

    balanced = define_reaction(
        (
            StateStoichiometry(proton, -1),
            StateStoichiometry(electron, -1),
            StateStoichiometry(hydrogen, 1),
        ),
        reaction_id="proton-electron",
        purpose=ReactionPurpose.ELEMENTARY_STEP,
    )
    unbalanced = define_reaction(
        (StateStoichiometry(proton, -1), StateStoichiometry(hydrogen, 1)),
        reaction_id="missing-electron",
        purpose=ReactionPurpose.ELEMENTARY_STEP,
    )

    assert balanced.status == "validated"
    assert unbalanced.reaction is None
    assert "REACTION_CHARGE_UNBALANCED" in {item.code for item in unbalanced.diagnostics}


def test_formation_reaction_uses_exact_fractional_stoichiometry() -> None:
    hydrogen = create_external_reference_state(
        state_id="hydrogen-gas",
        reference_id="hydrogen-gas-reference",
        provenance_sha256="d" * 64,
        formula="H2",
        formal_charge_e=0,
        phase=ChemicalPhase.GAS,
    )
    oxygen = create_external_reference_state(
        state_id="oxygen-gas",
        reference_id="oxygen-gas-reference",
        provenance_sha256="e" * 64,
        formula="O2",
        formal_charge_e=0,
        phase=ChemicalPhase.GAS,
    )
    water = create_external_reference_state(
        state_id="water-gas",
        reference_id="water-gas-reference",
        provenance_sha256="f" * 64,
        formula="H2O",
        formal_charge_e=0,
        phase=ChemicalPhase.GAS,
    )
    references = create_reference_state_set(
        (oxygen, hydrogen),
        reference_set_id="water-formation-references",
    )

    exact = define_reaction(
        (
            StateStoichiometry(hydrogen, -1),
            StateStoichiometry(oxygen, "-1/2"),
            StateStoichiometry(water, 1),
        ),
        reaction_id="water-formation",
        purpose=ReactionPurpose.FORMATION,
        reference_set=references,
    )
    inexact = define_reaction(
        (
            StateStoichiometry(hydrogen, -1),
            StateStoichiometry(oxygen, -0.5),
            StateStoichiometry(water, 1),
        ),
        reaction_id="water-formation-float",
        purpose=ReactionPurpose.FORMATION,
        reference_set=references,
    )

    assert exact.status == "validated"
    assert exact.reaction is not None
    assert {item.state_id: item.coefficient.fraction for item in exact.reaction.terms} == {
        "hydrogen-gas": -1,
        "oxygen-gas": Fraction(-1, 2),
        "water-gas": 1,
    }
    assert inexact.reaction is None
    assert "REACTION_COEFFICIENT_INVALID" in {item.code for item in inexact.diagnostics}


def test_adsorption_and_formation_require_reference_states() -> None:
    _, catalyst, _, _, adsorbate, _, configuration = _domain_chain()
    surface = create_catalyst_state(catalyst, state_id="surface")
    gas = create_adsorbate_state(adsorbate, state_id="gas", phase=ChemicalPhase.GAS)
    adsorbed = create_adsorption_state(
        catalyst,
        adsorbate,
        configuration,
        state_id="adsorbed",
    )

    report = define_reaction(
        (
            StateStoichiometry(surface, -1),
            StateStoichiometry(gas, -1),
            StateStoichiometry(adsorbed, 1),
        ),
        reaction_id="no-references",
        purpose=ReactionPurpose.ADSORPTION,
    )

    assert report.reaction is None
    assert {item.code for item in report.diagnostics} == {"REFERENCE_STATE_SET_REQUIRED"}

    incomplete_references = create_reference_state_set(
        (surface,),
        reference_set_id="incomplete-references",
    )
    incomplete = define_reaction(
        (
            StateStoichiometry(surface, -1),
            StateStoichiometry(gas, -1),
            StateStoichiometry(adsorbed, 1),
        ),
        reaction_id="incomplete-references",
        purpose=ReactionPurpose.ADSORPTION,
        reference_set=incomplete_references,
    )

    assert incomplete.reaction is None
    assert "REFERENCE_STATE_COVERAGE_INCOMPLETE" in {item.code for item in incomplete.diagnostics}


def test_cross_energy_family_and_missing_approvals_block_electronic_derivation(
    tmp_path: Path,
) -> None:
    _, _, reaction, bindings, reviews, cross_family = _electronic_chain(
        tmp_path / "cross-family",
        gas_family="e",
    )
    states, references, same_reaction, same_bindings, same_reviews, _ = _electronic_chain(
        tmp_path / "missing-review",
    )
    missing_review = derive_reaction_electronic_energy(
        same_reaction,
        same_bindings,
        same_reviews[:-1],
    )
    missing_binding = derive_reaction_electronic_energy(
        same_reaction,
        same_bindings[:-1],
        same_reviews,
    )

    assert cross_family.value_ev is None
    assert "ENERGY_FAMILY_MISMATCH" in {item.code for item in cross_family.diagnostics}
    assert missing_review.value_ev is None
    assert "SCIENTIFIC_DEFINITION_APPROVAL_MISSING_OR_AMBIGUOUS" in {
        item.code for item in missing_review.diagnostics
    }
    assert missing_binding.value_ev is None
    assert "REACTION_STATE_ENERGY_BINDINGS_INCOMPLETE" in {
        item.code for item in missing_binding.diagnostics
    }
    assert reaction and bindings and reviews and states and references


def test_conflicting_definition_review_blocks_electronic_derivation(tmp_path: Path) -> None:
    _, _, reaction, bindings, reviews, _ = _electronic_chain(tmp_path)
    conflict = record_definition_review(
        reaction,
        accepted=False,
        reviewer="second-scientist",
        reviewed_at_utc="2026-07-16T07:01:00Z",
        note="Conflicting reaction review.",
    )

    report = derive_reaction_electronic_energy(
        reaction,
        bindings,
        (*reviews, conflict),
    )

    assert report.value_ev is None
    assert "SCIENTIFIC_DEFINITION_APPROVAL_MISSING_OR_AMBIGUOUS" in {
        item.code for item in report.diagnostics
    }


def test_reviewed_thermochemistry_produces_component_resolved_free_energy(
    tmp_path: Path,
) -> None:
    states, _, reaction, _, _, electronic = _electronic_chain(tmp_path)
    protocol, corrections, thermo_reviews = _thermochemistry(states)

    report = derive_reaction_free_energy(
        reaction,
        electronic,
        protocol,
        corrections,
        thermo_reviews,
    )
    repeated = derive_reaction_free_energy(
        reaction,
        electronic,
        protocol,
        tuple(reversed(corrections)),
        tuple(reversed(thermo_reviews)),
    )

    assert report.status == "derived"
    assert report.property_kind == "adsorption_free_energy"
    assert report.electronic_energy_ev == pytest.approx(10.25)
    assert report.electronic_derivation_sha256 == electronic.derivation_sha256
    assert report.energy_family_id == electronic.energy_family_id
    assert report.electronic_energy_kind is electronic.kind
    assert report.delta_zero_point_energy_ev == pytest.approx(0.1)
    assert report.delta_thermal_enthalpy_ev == pytest.approx(-0.03)
    assert report.negative_t_delta_entropy_ev == pytest.approx(0.23852)
    assert report.delta_solvation_free_energy_ev == pytest.approx(0.0)
    assert report.delta_other_free_energy_ev == pytest.approx(0.0)
    assert report.value_ev == pytest.approx(10.55852)
    assert report.derivation_sha256 == repeated.derivation_sha256
    assert report.standard_states_explicit is True
    assert report.thermochemical_corrections_included is True
    assert report.electrochemical_correction_included is False
    assert report.computational_hydrogen_electrode_applied is False
    assert report.electrode_potential_v is None
    assert report.ph is None
    assert report.uncertainty_model_applied is False


def test_missing_mixed_or_unreviewed_corrections_fail_closed(tmp_path: Path) -> None:
    states, _, reaction, _, _, electronic = _electronic_chain(tmp_path)
    protocol, corrections, thermo_reviews = _thermochemistry(states)
    another_protocol = create_thermochemistry_protocol(
        protocol_id="thermo-310k",
        temperature_kelvin=310.0,
        low_frequency_treatment=LowFrequencyTreatment.HARMONIC,
        imaginary_mode_policy=ImaginaryModePolicy.REJECT,
    )
    mixed = create_thermochemical_correction(
        states[-1],
        another_protocol,
        correction_id="mixed-adsorbed",
        standard_state=StandardState.SURFACE_SITE,
        source_kind=CorrectionSourceKind.EXPLICIT_ASSUMPTION,
        source_reference="Wrong protocol for this reaction.",
        source_sha256s=("4" * 64,),
        zero_point_energy_ev=0.0,
        thermal_enthalpy_ev=0.0,
        entropy_ev_per_kelvin=0.0,
    )

    missing = derive_reaction_free_energy(
        reaction,
        electronic,
        protocol,
        corrections[:-1],
        thermo_reviews,
    )
    mixed_report = derive_reaction_free_energy(
        reaction,
        electronic,
        protocol,
        (*corrections[:-1], mixed),
        (*thermo_reviews[:-1], _approved(mixed)),
    )
    unreviewed = derive_reaction_free_energy(
        reaction,
        electronic,
        protocol,
        corrections,
        thermo_reviews[:-1],
    )

    assert missing.value_ev is None
    assert "THERMOCHEMICAL_CORRECTIONS_INCOMPLETE" in {item.code for item in missing.diagnostics}
    assert mixed_report.value_ev is None
    assert "THERMOCHEMICAL_CORRECTION_IDENTITY_MISMATCH" in {
        item.code for item in mixed_report.diagnostics
    }
    assert unreviewed.value_ev is None
    assert "SCIENTIFIC_DEFINITION_APPROVAL_MISSING_OR_AMBIGUOUS" in {
        item.code for item in unreviewed.diagnostics
    }


def test_standard_state_source_and_entropy_are_strict() -> None:
    _, catalyst, _, _, adsorbate, _, _ = _domain_chain()
    surface = create_catalyst_state(catalyst, state_id="surface")
    gas = create_adsorbate_state(adsorbate, state_id="gas", phase=ChemicalPhase.GAS)
    protocol = create_thermochemistry_protocol(
        protocol_id="thermo",
        temperature_kelvin=298.15,
        low_frequency_treatment=LowFrequencyTreatment.EXPLICIT,
        imaginary_mode_policy=ImaginaryModePolicy.MANUAL_REVIEW,
    )

    with pytest.raises(ValueError, match="incompatible"):
        create_thermochemical_correction(
            gas,
            protocol,
            correction_id="wrong-standard",
            standard_state=StandardState.SURFACE_SITE,
            source_kind=CorrectionSourceKind.TABULATED,
            source_reference="Synthetic.",
            source_sha256s=("a" * 64,),
            zero_point_energy_ev=0,
            thermal_enthalpy_ev=0,
            entropy_ev_per_kelvin=0,
        )
    with pytest.raises(ValueError, match="cannot be negative"):
        create_thermochemical_correction(
            surface,
            protocol,
            correction_id="negative-entropy",
            standard_state=StandardState.SURFACE_SITE,
            source_kind=CorrectionSourceKind.EXPLICIT_ASSUMPTION,
            source_reference="Synthetic.",
            source_sha256s=("b" * 64,),
            zero_point_energy_ev=0,
            thermal_enthalpy_ev=0,
            entropy_ev_per_kelvin=-0.1,
        )
    with pytest.raises(ValueError, match="provenance hashes"):
        create_thermochemical_correction(
            surface,
            protocol,
            correction_id="no-source",
            standard_state=StandardState.SURFACE_SITE,
            source_kind=CorrectionSourceKind.EXPLICIT_ASSUMPTION,
            source_reference="Synthetic.",
            source_sha256s=(),
            zero_point_energy_ev=0,
            thermal_enthalpy_ev=0,
            entropy_ev_per_kelvin=0,
        )
    with pytest.raises(ValueError, match="external references"):
        create_external_reference_state(
            state_id="invalid-external-surface",
            reference_id="invalid-external-surface",
            provenance_sha256="c" * 64,
            formula="Pt",
            formal_charge_e=0,
            phase=ChemicalPhase.SURFACE,
        )


def test_tampered_state_binding_and_correction_cannot_be_reviewed(tmp_path: Path) -> None:
    states, _, reaction, bindings, _, electronic = _electronic_chain(tmp_path)
    protocol, corrections, thermo_reviews = _thermochemistry(states)

    with pytest.raises(ValueError, match="intact reaction-domain"):
        record_definition_review(
            replace(bindings[0], state_id="another-state"),
            accepted=True,
            reviewer="scientist",
            reviewed_at_utc="2026-07-16T07:00:00Z",
            note="Must fail.",
        )
    with pytest.raises(ValueError, match="intact reaction-domain"):
        record_definition_review(
            replace(corrections[0], zero_point_energy_ev=99.0),
            accepted=True,
            reviewer="scientist",
            reviewed_at_utc="2026-07-16T07:00:00Z",
            note="Must fail.",
        )
    with pytest.raises(ValueError, match="identities do not match"):
        corrections[0].total_correction_ev(replace(protocol, protocol_id="another-protocol"))

    tampered_electronic = replace(
        electronic,
        linear_derivation=replace(
            electronic.linear_derivation,
            derivation_id="tampered-linear-derivation",
        ),
    )
    blocked = derive_reaction_free_energy(
        reaction,
        tampered_electronic,
        protocol,
        corrections,
        thermo_reviews,
    )
    assert blocked.value_ev is None
    assert "REACTION_ELECTRONIC_ENERGY_INVALID" in {item.code for item in blocked.diagnostics}


def test_reaction_workflow_uses_no_paper4_specific_constants(tmp_path: Path) -> None:
    states, references, reaction, bindings, _, electronic = _electronic_chain(tmp_path)
    payload = json.dumps(
        {
            "states": [item.to_dict() for item in states],
            "references": references.to_dict(),
            "reaction": reaction.to_dict(),
            "bindings": [item.to_dict() for item in bindings],
            "electronic": electronic.to_dict(),
        }
    )

    assert DefinitionSubjectKind.REFERENCE_STATE_SET.value in {
        item.value for item in DefinitionSubjectKind
    }
    assert "NiZn" not in payload
    assert "CO2RR" not in payload
    assert "13 metals" not in payload
