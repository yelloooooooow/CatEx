from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pymatgen.core import Lattice, Structure

from catex.catalysis import CatalystModelKind, StructureOrigin, ordered_structure_hash
from catex.hashing import structure_hash
from catex.transformations import (
    AtomMappingKind,
    StructureTransformationOperation,
    assess_transformation_readiness,
    create_vacancies,
    dope_sites,
    generate_slab_candidates,
    record_transformation_review,
    register_transformed_catalyst,
    set_orthogonal_c_vacuum,
    substitute_sites,
)


def _alloy() -> Structure:
    return Structure(
        Lattice.cubic(4.0),
        ["Pt", "Pt", "Pt"],
        [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


def _approved(record):
    return record_transformation_review(
        record,
        accepted=True,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-16T08:00:00Z",
        note="Synthetic transformation review.",
    )


def test_vacancy_preserves_exact_parent_child_lineage() -> None:
    parent = _alloy()
    product = create_vacancies(
        parent,
        (1,),
        transformation_id="pt-vacancy",
    )

    assert product.record.operation is StructureTransformationOperation.VACANCY
    assert product.record.mapping_kind is AtomMappingKind.EXACT_INDEX
    assert product.record.exact_atom_mapping_complete is True
    assert product.record.removed_parent_indices_0based == (1,)
    assert [item.child_indices_0based for item in product.record.parent_atom_lineage] == [
        (0,),
        (),
        (1,),
    ]
    assert product.structure.composition.formula == "Pt2"
    assert product.record.input_canonical_sha256 == structure_hash(parent)
    assert product.record.output_ordered_sha256 == ordered_structure_hash(product.structure)
    assert product.to_dict()["live_structure_embedded"] is False


def test_substitution_and_doping_are_distinct_provenance_operations() -> None:
    parent = _alloy()
    substitution = substitute_sites(
        parent,
        {0: "Ni"},
        transformation_id="pt-to-ni",
    )
    doping = dope_sites(
        parent,
        {0: "Ni"},
        transformation_id="pt-ni-dopant",
    )

    assert substitution.structure[0].specie.symbol == "Ni"
    assert substitution.record.operation is StructureTransformationOperation.SUBSTITUTION
    assert doping.record.operation is StructureTransformationOperation.DOPING
    assert substitution.record.identity_sha256 != doping.record.identity_sha256
    assert substitution.record.parameters["replacements"] == [
        {"index_0based": 0, "from": "Pt", "to": "Ni"}
    ]
    with pytest.raises(ValueError, match="must change"):
        substitute_sites(parent, {0: "Pt"}, transformation_id="no-change")
    with pytest.raises(ValueError, match="invalid replacement"):
        dope_sites(parent, {0: "NotAnElement"}, transformation_id="invalid-element")


def test_vacuum_is_set_from_occupied_span_and_keeps_site_order() -> None:
    slab = Structure(
        Lattice.from_parameters(4, 4, 10, 90, 90, 90),
        ["Pt", "Pt"],
        [[0, 0, 0.4], [0.5, 0.5, 0.6]],
    )
    product = set_orthogonal_c_vacuum(
        slab,
        15.0,
        transformation_id="vacuum-15a",
    )

    assert product.structure.lattice.c == pytest.approx(17.0)
    assert product.record.parameters["occupied_span_angstrom"] == pytest.approx(2.0)
    assert product.record.parameters["vacuum_angstrom"] == 15.0
    assert [site.specie.symbol for site in product.structure] == ["Pt", "Pt"]
    assert product.record.mapping_kind is AtomMappingKind.EXACT_INDEX

    tilted = Structure(
        Lattice.from_parameters(4, 4, 10, 80, 90, 90),
        ["Pt"],
        [[0, 0, 0.5]],
    )
    with pytest.raises(ValueError, match="perpendicular"):
        set_orthogonal_c_vacuum(
            tilted,
            15,
            transformation_id="unsafe-vacuum",
        )


def test_slab_generation_returns_reviewable_deterministic_candidates() -> None:
    bulk = Structure(Lattice.cubic(3.9), ["Pt"], [[0, 0, 0]])

    first = generate_slab_candidates(
        bulk,
        transformation_id_prefix="pt-100",
        miller_index=(1, 0, 0),
        minimum_slab_angstrom=7,
        minimum_vacuum_angstrom=12,
    )
    repeated = generate_slab_candidates(
        bulk,
        transformation_id_prefix="pt-100",
        miller_index=(1, 0, 0),
        minimum_slab_angstrom=7,
        minimum_vacuum_angstrom=12,
    )

    assert first
    assert [item.record.identity_sha256 for item in first] == [
        item.record.identity_sha256 for item in repeated
    ]
    assert all(item.record.mapping_kind is AtomMappingKind.BULK_EQUIVALENCE for item in first)
    assert all(not item.record.exact_atom_mapping_complete for item in first)
    assert all(item.status == "review_required" for item in first)
    assert all(
        "SLAB_TERMINATION_REVIEW_REQUIRED" in {finding.code for finding in item.diagnostics}
        for item in first
    )


def test_transformation_review_gate_rechecks_live_structure_and_conflicts() -> None:
    product = substitute_sites(
        _alloy(),
        {0: "Ni"},
        transformation_id="reviewed-substitution",
    )
    approval = _approved(product.record)
    ready = assess_transformation_readiness(product, (approval,))
    duplicate = assess_transformation_readiness(product, (approval, approval))
    changed_structure = product.structure.copy()
    changed_structure.translate_sites([0], [0.1, 0, 0], frac_coords=True)
    tampered = assess_transformation_readiness(
        replace(product, structure=changed_structure),
        (approval,),
    )

    assert ready.ready_for_catalyst_registration is True
    assert ready.accepted_review_sha256 == approval.review_sha256
    assert duplicate.status == "blocked"
    assert tampered.status == "blocked"
    assert "TRANSFORMATION_PRODUCT_INVALID" in {item.code for item in tampered.diagnostics}

    catalyst = register_transformed_catalyst(
        product,
        ready,
        catalyst_id="reviewed-alloy",
        model_kind=CatalystModelKind.BULK,
    )
    assert catalyst.structure_origin is StructureOrigin.TRANSFORMED
    assert catalyst.transformation_sha256s == (product.record.identity_sha256,)

    with pytest.raises(ValueError, match="review gate"):
        register_transformed_catalyst(
            product,
            duplicate,
            catalyst_id="blocked-alloy",
            model_kind=CatalystModelKind.BULK,
        )

    rejection = record_transformation_review(
        product.record,
        accepted=False,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-16T08:01:00Z",
        note="Rejected synthetic transformation.",
    )
    assert assess_transformation_readiness(product, (rejection,)).status == "blocked"
    with pytest.raises(ValueError, match="intact"):
        record_transformation_review(
            replace(product.record, output_canonical_sha256="f" * 64),
            accepted=True,
            reviewer="scientist",
            reviewed_at_utc="2026-07-16T08:02:00Z",
            note="Must fail.",
        )


def test_transformation_records_are_path_free_and_generic() -> None:
    product = create_vacancies(
        _alloy(),
        (2,),
        transformation_id="generic-vacancy",
    )
    payload = json.dumps(product.to_dict())

    assert "path" not in payload.lower()
    assert "NiZn" not in payload
    assert "CO2RR" not in payload
    assert product.record.writes_performed is False
    assert product.record.commands_executed is False
