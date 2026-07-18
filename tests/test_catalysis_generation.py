from __future__ import annotations

import json

import pytest
from pymatgen.core import Molecule
from test_catalysis_identities import _approvals, _domain_chain

from catex.catalysis import (
    BindingAlignmentMode,
    SiteKind,
    SpinInitialization,
    assess_configuration_readiness,
    create_adsorbate,
    deduplicate_adsorption_configurations,
    define_site,
    generate_adsorption_configuration,
    plan_multi_spin_calculations,
)
from catex.workflow import KpointsSpecification, ScientificProtocol


def _generated(*, generation_id: str, configuration_id: str, height: float = 2.0):
    structure, catalyst, site, molecule, adsorbate, _, _ = _domain_chain()
    generated = generate_adsorption_configuration(
        catalyst,
        structure,
        site,
        adsorbate,
        molecule,
        generation_id=generation_id,
        configuration_id=configuration_id,
        binding_anchor_pairs=((0, 0),),
        height_angstrom=height,
    )
    return structure, catalyst, site, molecule, adsorbate, generated


def _base_protocol(**incar_overrides: str) -> ScientificProtocol:
    incar = {"ENCUT": "400", "EDIFF": "1E-5", **incar_overrides}
    return ScientificProtocol(
        protocol_id="pt-co-relax",
        target_vasp_version="5.4.4",
        incar=incar,
        kpoints=KpointsSpecification(
            generation_mode="gamma",
            subdivisions=(2, 2, 1),
        ),
    )


def test_single_binding_atom_generation_is_rigid_and_review_pending() -> None:
    _, _, _, molecule, _, generated = _generated(
        generation_id="co-atop-generation",
        configuration_id="co-atop-generated",
    )

    assert generated.generation.alignment_mode is BindingAlignmentMode.TRANSLATION_ONLY
    assert generated.generation.binding_alignment_rmsd_angstrom == pytest.approx(0.0)
    assert generated.configuration.minimum_binding_distance_angstrom == pytest.approx(2.0)
    assert generated.generation.molecule_distorted is False
    assert generated.configuration.scientific_identity_approved is False
    assert generated.to_dict()["live_structure_embedded"] is False
    adsorbate_indices = generated.configuration.adsorbate_indices_0based
    assert generated.structure.get_distance(*adsorbate_indices) == pytest.approx(
        molecule.get_distance(0, 1)
    )


def test_multi_binding_alignment_uses_explicit_pairs_without_distortion() -> None:
    structure, catalyst, _, _, _, _, _ = _domain_chain()
    bridge = define_site(
        catalyst,
        structure,
        site_id="pt-bridge",
        kind=SiteKind.BRIDGE,
        anchor_indices_0based=(0, 1),
    )
    anchor_distance = structure.get_distance(0, 1)
    molecule = Molecule(
        ["O", "O"],
        [[-anchor_distance / 2, 0, 0], [anchor_distance / 2, 0, 0]],
    )
    adsorbate = create_adsorbate(
        molecule,
        adsorbate_id="o2-bidentate",
        binding_atom_indices_0based=(0, 1),
    )

    generated = generate_adsorption_configuration(
        catalyst,
        structure,
        bridge,
        adsorbate,
        molecule,
        generation_id="o2-bridge-generation",
        configuration_id="o2-bridge",
        binding_anchor_pairs=((0, 0), (1, 1)),
        height_angstrom=1.8,
        alignment_tolerance_angstrom=1e-6,
    )

    assert generated.generation.alignment_mode is BindingAlignmentMode.TWO_POINT_RIGID
    assert generated.generation.binding_alignment_rmsd_angstrom < 1e-8
    assert generated.structure.get_distance(
        *generated.configuration.adsorbate_indices_0based
    ) == pytest.approx(anchor_distance)

    incompatible = Molecule(["O", "O"], [[0, 0, 0], [0, 0, 1.2]])
    incompatible_identity = create_adsorbate(
        incompatible,
        adsorbate_id="short-o2",
        binding_atom_indices_0based=(0, 1),
    )
    with pytest.raises(ValueError, match="exceeds"):
        generate_adsorption_configuration(
            catalyst,
            structure,
            bridge,
            incompatible_identity,
            incompatible,
            generation_id="incompatible-generation",
            configuration_id="incompatible-o2",
            binding_anchor_pairs=((0, 0), (1, 1)),
            height_angstrom=1.8,
            alignment_tolerance_angstrom=0.1,
        )


def test_generation_rejects_incomplete_binding_mapping_and_clashes() -> None:
    structure, catalyst, site, molecule, adsorbate, _, _ = _domain_chain()

    with pytest.raises(ValueError, match="declared binding atom"):
        generate_adsorption_configuration(
            catalyst,
            structure,
            site,
            adsorbate,
            molecule,
            generation_id="bad-pair",
            configuration_id="bad-pair",
            binding_anchor_pairs=((1, 0),),
            height_angstrom=2.0,
        )
    with pytest.raises(ValueError, match="clash"):
        generate_adsorption_configuration(
            catalyst,
            structure,
            site,
            adsorbate,
            molecule,
            generation_id="clashing",
            configuration_id="clashing",
            binding_anchor_pairs=((0, 0),),
            height_angstrom=0.2,
            minimum_allowed_distance_angstrom=0.6,
        )


def test_deduplication_is_order_independent_and_keeps_distinct_heights() -> None:
    *_, first = _generated(
        generation_id="same-a",
        configuration_id="same-a",
    )
    *_, second = _generated(
        generation_id="same-b",
        configuration_id="same-b",
    )
    *_, distinct = _generated(
        generation_id="higher",
        configuration_id="higher",
        height=2.3,
    )

    report = deduplicate_adsorption_configurations((first, second, distinct))
    repeated = deduplicate_adsorption_configurations((distinct, second, first))

    assert len(report.groups) == 2
    assert sorted(len(item.member_configuration_ids) for item in report.groups) == [1, 2]
    assert report.deduplication_sha256 == repeated.deduplication_sha256
    assert report.representative_configuration_ids == repeated.representative_configuration_ids


def test_multi_spin_plan_requires_reviewed_configuration_and_unique_states() -> None:
    _, catalyst, site, _, adsorbate, generated = _generated(
        generation_id="spin-generation",
        configuration_id="spin-configuration",
    )
    reviews = _approvals(catalyst, site, adsorbate, generated.configuration)
    readiness = assess_configuration_readiness(
        catalyst,
        site,
        adsorbate,
        generated.configuration,
        reviews,
    )
    states = (
        SpinInitialization("afm", (1.0, -1.0, 0.0, 0.0), nupdown=0),
        SpinInitialization("fm", (1.0, 1.0, 0.0, 0.0), nupdown=2),
    )

    plan = plan_multi_spin_calculations(
        generated.configuration,
        readiness,
        _base_protocol(),
        states,
    )

    assert plan.status == "protocol_review_required"
    assert [item.spin_initialization.label for item in plan.variants] == ["afm", "fm"]
    assert len({item.protocol_variant_sha256 for item in plan.variants}) == 2
    assert plan.variants[0].protocol.incar["ISPIN"] == "2"
    assert plan.variants[0].protocol.incar["MAGMOM"] == "1 -1 0 0"
    assert plan.variants[0].protocol.incar["NUPDOWN"] == "0"
    assert all(item.manual_protocol_review_required for item in plan.variants)
    assert plan.submitted is False
    assert plan.writes_performed is False

    with pytest.raises(ValueError, match="four-identity review gate"):
        plan_multi_spin_calculations(
            generated.configuration,
            assess_configuration_readiness(
                catalyst,
                site,
                adsorbate,
                generated.configuration,
                reviews[:-1],
            ),
            _base_protocol(),
            states,
        )
    with pytest.raises(ValueError, match="unique"):
        plan_multi_spin_calculations(
            generated.configuration,
            readiness,
            _base_protocol(),
            (states[0], SpinInitialization("copy", states[0].magnetic_moments_mu_b, 0)),
        )
    with pytest.raises(ValueError, match="LNONCOLLINEAR"):
        plan_multi_spin_calculations(
            generated.configuration,
            readiness,
            _base_protocol(LNONCOLLINEAR=".TRUE."),
            states,
        )


def test_generation_and_spin_records_are_path_free_and_generic() -> None:
    _, catalyst, site, _, adsorbate, generated = _generated(
        generation_id="generic-generation",
        configuration_id="generic-configuration",
    )
    readiness = assess_configuration_readiness(
        catalyst,
        site,
        adsorbate,
        generated.configuration,
        _approvals(catalyst, site, adsorbate, generated.configuration),
    )
    plan = plan_multi_spin_calculations(
        generated.configuration,
        readiness,
        _base_protocol(),
        (
            SpinInitialization("state-a", (1, -1, 0, 0)),
            SpinInitialization("state-b", (1, 1, 0, 0)),
        ),
    )
    payload = json.dumps({"generated": generated.to_dict(), "spin_plan": plan.to_dict()})

    assert "path" not in payload.lower()
    assert "NiZn" not in payload
    assert "CO2RR" not in payload
    assert 'submitted": false' in payload
