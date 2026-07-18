"""Non-Paper-4 integration benchmark for the generic scientific core."""

from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Lattice, Molecule, Structure
from test_electronic_structure import _analysis_bundle
from test_energy_compatibility import _accepted_energy

from catex.catalysis import (
    CatalystModelKind,
    SiteKind,
    SpinInitialization,
    assess_configuration_readiness,
    create_adsorbate,
    deduplicate_adsorption_configurations,
    define_site,
    generate_adsorption_configuration,
    plan_multi_spin_calculations,
    record_identity_review,
)
from catex.electronic_structure import summarize_electronic_structure
from catex.reactions import (
    ChemicalPhase,
    CorrectionSourceKind,
    ImaginaryModePolicy,
    LowFrequencyTreatment,
    ReactionPurpose,
    StandardState,
    StateStoichiometry,
    bind_state_energy,
    create_adsorbate_state,
    create_adsorption_state,
    create_catalyst_state,
    create_reference_state_set,
    create_thermochemical_correction,
    create_thermochemistry_protocol,
    define_reaction,
    derive_reaction_electronic_energy,
    derive_reaction_free_energy,
    record_definition_review,
)
from catex.transformations import (
    assess_transformation_readiness,
    record_transformation_review,
    register_transformed_catalyst,
    set_orthogonal_c_vacuum,
)
from catex.workflow import KpointsSpecification, ScientificProtocol


def _definition_approval(subject):
    return record_definition_review(
        subject,
        accepted=True,
        reviewer="reference-case-scientist",
        reviewed_at_utc="2026-07-16T10:00:00Z",
        note="Synthetic Pt/CO reference-case review.",
    )


def test_pt_co_reference_case_runs_from_model_to_reviewable_analysis(tmp_path: Path) -> None:
    initial_slab = Structure(
        Lattice.from_parameters(4.0, 4.0, 10.0, 90, 90, 90),
        ("Pt", "Pt"),
        ((0.0, 0.0, 0.4), (0.5, 0.5, 0.6)),
    )
    vacuum_product = set_orthogonal_c_vacuum(
        initial_slab,
        15.0,
        transformation_id="pt-reference-vacuum",
    )
    transformation_review = record_transformation_review(
        vacuum_product.record,
        accepted=True,
        reviewer="reference-case-scientist",
        reviewed_at_utc="2026-07-16T09:00:00Z",
        note="Synthetic vacuum transformation review.",
    )
    transformation_readiness = assess_transformation_readiness(
        vacuum_product,
        (transformation_review,),
    )
    catalyst = register_transformed_catalyst(
        vacuum_product,
        transformation_readiness,
        catalyst_id="pt-slab-reference",
        model_kind=CatalystModelKind.SLAB,
    )
    site = define_site(
        catalyst,
        vacuum_product.structure,
        site_id="pt-atop-reference",
        kind=SiteKind.ATOP,
        anchor_indices_0based=(1,),
    )
    molecule = Molecule(("C", "O"), ((0, 0, 0), (0, 0, 1.15)))
    adsorbate = create_adsorbate(
        molecule,
        adsorbate_id="co-reference",
        binding_atom_indices_0based=(0,),
    )
    generated = generate_adsorption_configuration(
        catalyst,
        vacuum_product.structure,
        site,
        adsorbate,
        molecule,
        generation_id="pt-co-atop-generation",
        configuration_id="pt-co-atop",
        binding_anchor_pairs=((0, 0),),
        height_angstrom=2.0,
    )
    deduplication = deduplicate_adsorption_configurations((generated,))

    identity_reviews = tuple(
        record_identity_review(
            subject,
            accepted=True,
            reviewer="reference-case-scientist",
            reviewed_at_utc="2026-07-16T09:30:00Z",
            note="Synthetic Pt/CO identity review.",
        )
        for subject in (catalyst, site, adsorbate, generated.configuration)
    )
    configuration_readiness = assess_configuration_readiness(
        catalyst,
        site,
        adsorbate,
        generated.configuration,
        identity_reviews,
    )
    spin_plan = plan_multi_spin_calculations(
        generated.configuration,
        configuration_readiness,
        ScientificProtocol(
            protocol_id="pt-co-reference-relax",
            target_vasp_version="5.4.4",
            incar={"ENCUT": "450", "EDIFF": "1E-5"},
            kpoints=KpointsSpecification("gamma", (3, 3, 1)),
        ),
        (
            SpinInitialization("low-spin", (0.0, 0.0, 0.0, 0.0), nupdown=0),
            SpinInitialization("spin-polarized", (1.0, -1.0, 0.0, 0.0), nupdown=0),
        ),
    )

    surface = create_catalyst_state(catalyst, state_id="pt-surface")
    gas = create_adsorbate_state(
        adsorbate,
        state_id="co-gas",
        phase=ChemicalPhase.GAS,
    )
    adsorbed = create_adsorption_state(
        catalyst,
        adsorbate,
        generated.configuration,
        state_id="co-on-pt",
    )
    references = create_reference_state_set(
        (surface, gas),
        reference_set_id="pt-co-reference-states",
    )
    definition_report = define_reaction(
        (
            StateStoichiometry(surface, -1),
            StateStoichiometry(gas, -1),
            StateStoichiometry(adsorbed, 1),
        ),
        reaction_id="pt-co-adsorption",
        purpose=ReactionPurpose.ADSORPTION,
        reference_set=references,
    )
    assert definition_report.reaction is not None
    reaction = definition_report.reaction

    surface_energy, _, _, _ = _accepted_energy(
        tmp_path / "surface-energy",
        energy_id="pt-surface-energy",
    )
    gas_energy, _, _, _ = _accepted_energy(
        tmp_path / "gas-energy",
        energy_id="co-gas-energy",
    )
    adsorbed_energy, _, _, _ = _accepted_energy(
        tmp_path / "adsorbed-energy",
        energy_id="co-on-pt-energy",
    )
    bindings = (
        bind_state_energy(surface, surface_energy, binding_id="pt-surface-binding"),
        bind_state_energy(gas, gas_energy, binding_id="co-gas-binding"),
        bind_state_energy(adsorbed, adsorbed_energy, binding_id="co-on-pt-binding"),
    )
    definition_reviews = tuple(
        _definition_approval(subject)
        for subject in (surface, gas, adsorbed, references, reaction, *bindings)
    )
    electronic_energy = derive_reaction_electronic_energy(
        reaction,
        bindings,
        definition_reviews,
    )

    thermochemistry = create_thermochemistry_protocol(
        protocol_id="pt-co-thermo-298k",
        temperature_kelvin=298.15,
        low_frequency_treatment=LowFrequencyTreatment.HARMONIC,
        imaginary_mode_policy=ImaginaryModePolicy.REJECT,
    )
    corrections = tuple(
        create_thermochemical_correction(
            state,
            thermochemistry,
            correction_id=f"{state.state_id}-correction",
            standard_state=(
                StandardState.GAS_1_BAR
                if state.phase is ChemicalPhase.GAS
                else StandardState.SURFACE_SITE
            ),
            source_kind=CorrectionSourceKind.EXPLICIT_ASSUMPTION,
            source_reference="Synthetic acceptance value; not research data.",
            source_sha256s=(f"{index:x}" * 64,),
            zero_point_energy_ev=value,
            thermal_enthalpy_ev=0.0,
            entropy_ev_per_kelvin=0.0,
        )
        for index, (state, value) in enumerate(
            ((surface, 0.0), (gas, 0.1), (adsorbed, 0.2)),
            start=1,
        )
    )
    free_energy = derive_reaction_free_energy(
        reaction,
        electronic_energy,
        thermochemistry,
        corrections,
        tuple(_definition_approval(subject) for subject in (thermochemistry, *corrections)),
    )

    dos, magnetism, charge = _analysis_bundle(generated.configuration.identity_sha256)
    electronic_summary = summarize_electronic_structure(
        generated.configuration,
        configuration_readiness,
        dos,
        magnetism,
        charge,
    )

    assert transformation_readiness.ready_for_catalyst_registration is True
    assert deduplication.representative_configuration_ids == ("pt-co-atop",)
    assert configuration_readiness.ready_for_calculation_planning is True
    assert spin_plan.status == "protocol_review_required"
    assert electronic_energy.status == "derived"
    assert free_energy.status == "derived"
    assert free_energy.value_ev == pytest.approx(electronic_energy.value_ev + 0.1)
    assert electronic_summary.manual_interpretation_required is True
    assert electronic_summary.automatic_scientific_conclusion_performed is False
    assert all(
        not item
        for item in (
            spin_plan.submitted,
            spin_plan.writes_performed,
            electronic_summary.writes_performed,
        )
    )
