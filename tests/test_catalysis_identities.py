from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pymatgen.core import Lattice, Molecule, Structure

from catex.catalysis import (
    AdsorptionPlacementKind,
    CatalystModelKind,
    IdentitySubjectKind,
    SiteKind,
    StructureOrigin,
    assess_configuration_readiness,
    create_adsorbate,
    create_adsorption_configuration,
    create_catalyst_system,
    define_site,
    ordered_structure_hash,
    record_identity_review,
)
from catex.hashing import structure_hash
from catex.structures import inspect_structure


def _catalyst_structure() -> Structure:
    return Structure(
        Lattice.from_parameters(5.0, 5.0, 15.0, 90, 90, 90),
        ["Pt", "Pt"],
        [[0.0, 0.0, 0.4], [0.5, 0.5, 0.4]],
    )


def _domain_chain():
    structure = _catalyst_structure()
    inspection = inspect_structure(structure)
    assert inspection.record is not None
    catalyst = create_catalyst_system(
        inspection.record,
        structure,
        catalyst_id="pt-slab",
        model_kind=CatalystModelKind.SLAB,
        structure_origin=StructureOrigin.GENERATED,
    )
    site = define_site(
        catalyst,
        structure,
        site_id="pt-atop-0",
        kind=SiteKind.ATOP,
        anchor_indices_0based=(0,),
    )
    molecule = Molecule(
        ["C", "O"],
        [[0.0, 0.0, 0.0], [0.0, 0.0, 1.15]],
        charge=0,
        spin_multiplicity=1,
    )
    adsorbate = create_adsorbate(
        molecule,
        adsorbate_id="co",
        binding_atom_indices_0based=(0,),
    )
    combined = structure.copy()
    combined.append("C", [0.0, 0.0, 0.55], coords_are_cartesian=False)
    combined.append("O", [0.0, 0.0, 0.6266666667], coords_are_cartesian=False)
    configuration = create_adsorption_configuration(
        catalyst,
        structure,
        site,
        adsorbate,
        combined,
        configuration_id="co-atop",
        placement_kind=AdsorptionPlacementKind.RULE_BASED,
        substrate_indices_0based=(0, 1),
        adsorbate_indices_0based=(2, 3),
    )
    return structure, catalyst, site, molecule, adsorbate, combined, configuration


def _approvals(catalyst, site, adsorbate, configuration):
    return tuple(
        record_identity_review(
            subject,
            accepted=True,
            reviewer="synthetic-scientist",
            reviewed_at_utc="2026-07-16T06:00:00Z",
            note="Synthetic scientific identity review.",
        )
        for subject in (catalyst, site, adsorbate, configuration)
    )


def test_ordered_hash_protects_index_mapping_without_replacing_canonical_hash() -> None:
    structure = _catalyst_structure()
    reordered = Structure.from_sites(list(reversed(structure.sites)))

    assert structure_hash(reordered) == structure_hash(structure)
    assert ordered_structure_hash(reordered) != ordered_structure_hash(structure)


def test_generic_catalyst_identity_is_deterministic_and_path_sanitized() -> None:
    structure = _catalyst_structure()
    inspection = inspect_structure(structure)
    assert inspection.record is not None

    first = create_catalyst_system(
        inspection.record,
        structure,
        catalyst_id="generic-slab",
        model_kind=CatalystModelKind.SLAB,
        structure_origin=StructureOrigin.GENERATED,
    )
    repeated = create_catalyst_system(
        inspection.record,
        structure,
        catalyst_id="generic-slab",
        model_kind=CatalystModelKind.SLAB,
        structure_origin=StructureOrigin.GENERATED,
    )

    assert first.identity_sha256 == repeated.identity_sha256
    assert first.canonical_structure_sha256 == structure_hash(structure)
    assert first.manual_review_required is True
    assert first.writes_performed is False
    assert "path" not in json.dumps(first.to_dict()).lower()


def test_catalyst_requires_matching_ordered_structure_and_origin_provenance() -> None:
    structure = _catalyst_structure()
    inspection = inspect_structure(structure)
    assert inspection.record is not None
    changed = structure.copy()
    changed.translate_sites([0], [0.1, 0, 0], frac_coords=True)

    with pytest.raises(ValueError, match="does not match"):
        create_catalyst_system(
            replace(inspection.record, formula="Wrong1"),
            structure,
            catalyst_id="wrong-summary",
            model_kind=CatalystModelKind.SLAB,
            structure_origin=StructureOrigin.GENERATED,
        )

    with pytest.raises(ValueError, match="does not match"):
        create_catalyst_system(
            inspection.record,
            changed,
            catalyst_id="changed",
            model_kind=CatalystModelKind.SLAB,
            structure_origin=StructureOrigin.GENERATED,
        )
    with pytest.raises(ValueError, match="source artifact"):
        create_catalyst_system(
            inspection.record,
            structure,
            catalyst_id="external",
            model_kind=CatalystModelKind.SLAB,
            structure_origin=StructureOrigin.EXTERNAL_IMPORT,
        )
    with pytest.raises(ValueError, match="transformation provenance"):
        create_catalyst_system(
            inspection.record,
            structure,
            catalyst_id="transformed",
            model_kind=CatalystModelKind.SLAB,
            structure_origin=StructureOrigin.TRANSFORMED,
        )


def test_site_definition_is_index_bound_and_pbc_centroid_aware() -> None:
    structure = Structure(
        Lattice.cubic(10),
        ["Pt", "Pt"],
        [[0.98, 0.5, 0.5], [0.02, 0.5, 0.5]],
    )
    inspection = inspect_structure(structure)
    assert inspection.record is not None
    catalyst = create_catalyst_system(
        inspection.record,
        structure,
        catalyst_id="boundary-slab",
        model_kind=CatalystModelKind.SLAB,
        structure_origin=StructureOrigin.GENERATED,
    )

    site = define_site(
        catalyst,
        structure,
        site_id="boundary-bridge",
        kind=SiteKind.BRIDGE,
        anchor_indices_0based=(0, 1),
    )

    assert site.anchor_species == ("Pt", "Pt")
    assert site.fractional_centroid_wrapped[0] == pytest.approx(0.0)
    assert site.ordered_structure_sha256 == catalyst.ordered_structure_sha256
    with pytest.raises(ValueError, match="exactly two"):
        define_site(
            catalyst,
            structure,
            site_id="invalid-bridge",
            kind=SiteKind.BRIDGE,
            anchor_indices_0based=(0,),
        )


def test_adsorbate_geometry_hash_is_translation_rotation_invariant_but_ordered() -> None:
    molecule = Molecule(["C", "O"], [[0, 0, 0], [0, 0, 1.15]])
    moved = molecule.copy()
    moved.translate_sites(range(len(moved)), [3.0, -2.0, 1.0])
    moved.rotate_sites(range(len(moved)), theta=0.7, axis=[1, 1, 0])
    reordered = Molecule(["O", "C"], [[0, 0, 1.15], [0, 0, 0]])

    first = create_adsorbate(
        molecule,
        adsorbate_id="co",
        binding_atom_indices_0based=(0,),
    )
    transformed = create_adsorbate(
        moved,
        adsorbate_id="co",
        binding_atom_indices_0based=(0,),
    )
    reversed_order = create_adsorbate(
        reordered,
        adsorbate_id="co-reordered",
        binding_atom_indices_0based=(1,),
    )

    assert first.geometry_sha256 == transformed.geometry_sha256
    assert first.identity_sha256 == transformed.identity_sha256
    assert first.geometry_sha256 != reversed_order.geometry_sha256
    assert first.charge_e == 0
    assert first.spin_multiplicity == 1


def test_configuration_requires_disjoint_exhaustive_and_species_correct_mapping() -> None:
    structure, catalyst, site, _, adsorbate, combined, configuration = _domain_chain()

    assert configuration.substrate_indices_0based == (0, 1)
    assert configuration.adsorbate_indices_0based == (2, 3)
    assert configuration.minimum_binding_distance_angstrom == pytest.approx(2.25)
    assert configuration.scientific_identity_approved is False
    assert configuration.single_adsorbate_only is True

    with pytest.raises(ValueError, match="disjoint and exhaustive"):
        create_adsorption_configuration(
            catalyst,
            structure,
            site,
            adsorbate,
            combined,
            configuration_id="bad-map",
            placement_kind=AdsorptionPlacementKind.MANUAL,
            substrate_indices_0based=(0, 1),
            adsorbate_indices_0based=(1, 3),
        )
    with pytest.raises(ValueError, match="adsorbate species"):
        create_adsorption_configuration(
            catalyst,
            structure,
            site,
            adsorbate,
            combined,
            configuration_id="bad-order",
            placement_kind=AdsorptionPlacementKind.MANUAL,
            substrate_indices_0based=(0, 1),
            adsorbate_indices_0based=(3, 2),
        )


def test_configuration_readiness_requires_four_unique_bound_human_approvals() -> None:
    _, catalyst, site, _, adsorbate, _, configuration = _domain_chain()
    approvals = _approvals(catalyst, site, adsorbate, configuration)

    ready = assess_configuration_readiness(
        catalyst,
        site,
        adsorbate,
        configuration,
        approvals,
    )
    missing = assess_configuration_readiness(
        catalyst,
        site,
        adsorbate,
        configuration,
        approvals[:-1],
    )
    duplicate = assess_configuration_readiness(
        catalyst,
        site,
        adsorbate,
        configuration,
        (*approvals, approvals[-1]),
    )

    assert ready.status == "ready"
    assert ready.ready_for_calculation_planning is True
    assert len(ready.accepted_review_sha256s) == 4
    assert ready.writes_performed is False
    assert missing.status == "blocked"
    assert duplicate.status == "blocked"
    assert {item.code for item in missing.diagnostics} == {
        "CATALYSIS_IDENTITY_APPROVAL_MISSING_OR_AMBIGUOUS"
    }


def test_rejection_tampering_and_cross_subject_review_fail_closed() -> None:
    _, catalyst, site, _, adsorbate, _, configuration = _domain_chain()
    approvals = list(_approvals(catalyst, site, adsorbate, configuration))
    approvals[1] = record_identity_review(
        site,
        accepted=False,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-16T06:00:00Z",
        note="Site rejected.",
    )
    rejected = assess_configuration_readiness(
        catalyst,
        site,
        adsorbate,
        configuration,
        approvals,
    )
    conflict_reviews = [*_approvals(catalyst, site, adsorbate, configuration)]
    conflict_reviews.append(
        record_identity_review(
            site,
            accepted=False,
            reviewer="second-scientist",
            reviewed_at_utc="2026-07-16T06:01:00Z",
            note="Conflicting site review.",
        )
    )
    conflict = assess_configuration_readiness(
        catalyst,
        site,
        adsorbate,
        configuration,
        conflict_reviews,
    )
    altered_configuration = replace(configuration, site_id="another-site")
    altered = assess_configuration_readiness(
        catalyst,
        site,
        adsorbate,
        altered_configuration,
        _approvals(catalyst, site, adsorbate, configuration),
    )

    assert rejected.ready_for_calculation_planning is False
    assert conflict.ready_for_calculation_planning is False
    assert altered.ready_for_calculation_planning is False
    assert "CATALYSIS_IDENTITY_LINK_INVALID" in {item.code for item in altered.diagnostics}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"accepted": 1}, "accepted must be"),
        ({"reviewer": ""}, "reviewer must be"),
        ({"reviewer": "bad\nreviewer"}, "one line"),
        ({"note": ""}, "note must be"),
        ({"reviewed_at_utc": "2026-02-30T00:00:00Z"}, "valid UTC"),
    ],
)
def test_identity_review_metadata_is_strict(
    overrides: dict[str, object],
    message: str,
) -> None:
    _, catalyst, _, _, _, _, _ = _domain_chain()
    arguments: dict[str, object] = {
        "accepted": True,
        "reviewer": "scientist",
        "reviewed_at_utc": "2026-07-16T06:00:00Z",
        "note": "Reviewed.",
    }
    arguments.update(overrides)

    with pytest.raises(ValueError, match=message):
        record_identity_review(catalyst, **arguments)  # type: ignore[arg-type]


def test_domain_models_are_generic_not_paper4_specific() -> None:
    _, catalyst, site, _, adsorbate, _, configuration = _domain_chain()
    payload = json.dumps(
        {
            "catalyst": catalyst.to_dict(),
            "site": site.to_dict(),
            "adsorbate": adsorbate.to_dict(),
            "configuration": configuration.to_dict(),
        }
    )

    assert catalyst.formula == "Pt2"
    assert site.kind is SiteKind.ATOP
    assert adsorbate.formula == "C1 O1"
    assert IdentitySubjectKind.ADSORPTION_CONFIGURATION.value in {
        item.value for item in IdentitySubjectKind
    }
    assert "NiZn" not in payload
    assert "CO2RR" not in payload
