from __future__ import annotations

import json
import math
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from test_reaction_thermochemistry import _approved, _electronic_chain, _thermochemistry

from catex.reactions import (
    ChemicalPhase,
    ReactionPurpose,
    ReferenceElectrode,
    StateStoichiometry,
    apply_computational_hydrogen_electrode,
    assess_reaction_network_readiness,
    create_computational_hydrogen_electrode_protocol,
    create_external_reference_state,
    create_reaction_network,
    create_reference_state_set,
    define_reaction,
    derive_reaction_free_energy,
    is_intact_computational_hydrogen_electrode_report,
    record_definition_review,
    record_reaction_network_review,
)
from catex.readiness import (
    RequirementCategory,
    RequirementStatus,
    assess_scientific_case_readiness,
    create_scientific_case_requirement,
)


def _reference_state(state_id: str, formula: str, marker: str):
    return create_external_reference_state(
        state_id=state_id,
        reference_id=f"{state_id}-reference",
        provenance_sha256=marker * 64,
        formula=formula,
        formal_charge_e=0,
        phase=ChemicalPhase.GAS,
    )


def _water_network():
    hydrogen = _reference_state("hydrogen", "H2", "1")
    oxygen = _reference_state("oxygen", "O2", "2")
    water = _reference_state("water", "H2O", "3")
    peroxide = _reference_state("peroxide", "H2O2", "4")
    water_references = create_reference_state_set(
        (hydrogen, oxygen),
        reference_set_id="water-references",
    )
    peroxide_references = create_reference_state_set(
        (water, oxygen),
        reference_set_id="peroxide-references",
    )
    water_report = define_reaction(
        (
            StateStoichiometry(hydrogen, -1),
            StateStoichiometry(oxygen, "-1/2"),
            StateStoichiometry(water, 1),
        ),
        reaction_id="water-formation",
        purpose=ReactionPurpose.FORMATION,
        reference_set=water_references,
    )
    peroxide_report = define_reaction(
        (
            StateStoichiometry(water, -1),
            StateStoichiometry(oxygen, "-1/2"),
            StateStoichiometry(peroxide, 1),
        ),
        reaction_id="peroxide-formation",
        purpose=ReactionPurpose.FORMATION,
        reference_set=peroxide_references,
    )
    assert water_report.reaction is not None
    assert peroxide_report.reaction is not None
    return hydrogen, oxygen, water, peroxide, water_report.reaction, peroxide_report.reaction


def _base_free_energy(tmp_path: Path):
    states, _, reaction, _, _, electronic = _electronic_chain(tmp_path)
    protocol, corrections, reviews = _thermochemistry(states)
    base = derive_reaction_free_energy(reaction, electronic, protocol, corrections, reviews)
    assert base.status == "derived"
    return base


def _che_protocol(reference: ReferenceElectrode = ReferenceElectrode.SHE):
    return create_computational_hydrogen_electrode_protocol(
        protocol_id=f"synthetic-che-{reference.value.lower()}",
        reference_electrode=reference,
        electrode_potential_v=-0.8,
        ph=7.0,
        temperature_kelvin=298.15,
        source_reference="Synthetic CHE convention for tests.",
        source_sha256s=("b" * 64, "a" * 64),
    )


def test_reaction_network_is_deterministic_connected_and_review_gated() -> None:
    hydrogen, _, _, peroxide, first, second = _water_network()
    report = create_reaction_network(
        (second, first),
        network_id="water-oxidation-network",
        required_start_state_ids=(hydrogen.state_id,),
        required_terminal_state_ids=(peroxide.state_id,),
    )
    repeated = create_reaction_network(
        (first, second),
        network_id="water-oxidation-network",
        required_start_state_ids=(hydrogen.state_id,),
        required_terminal_state_ids=(peroxide.state_id,),
    )

    assert report.status == "review_required"
    assert report.network is not None
    assert repeated.network == report.network
    assert report.network.connected_component_count == 1
    assert [item.reaction_id for item in report.network.reactions] == [
        "peroxide-formation",
        "water-formation",
    ]
    review = record_reaction_network_review(
        report.network,
        accepted=True,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-16T11:00:00Z",
        note="Synthetic pathway review.",
    )
    readiness = assess_reaction_network_readiness(report.network, (review,))

    assert readiness.ready_for_pathway_planning is True
    assert readiness.execution_authorized is False
    assert readiness.accepted_review_sha256 == review.review_sha256
    assert assess_reaction_network_readiness(report.network, (review, review)).status == "blocked"


def test_reaction_network_rejects_disconnected_or_unreachable_paths() -> None:
    hydrogen, oxygen, water, peroxide, first, second = _water_network()
    nitrogen = _reference_state("nitrogen", "N2", "5")
    atom = _reference_state("nitrogen-atom", "N", "6")
    dissociation_report = define_reaction(
        (StateStoichiometry(nitrogen, -1), StateStoichiometry(atom, 2)),
        reaction_id="nitrogen-dissociation",
        purpose=ReactionPurpose.GENERIC,
    )
    assert dissociation_report.reaction is not None

    disconnected = create_reaction_network(
        (first, second, dissociation_report.reaction),
        network_id="disconnected",
    )
    unreachable = create_reaction_network(
        (first, second),
        network_id="unreachable",
        required_start_state_ids=(water.state_id,),
        required_terminal_state_ids=(hydrogen.state_id, peroxide.state_id),
    )

    assert disconnected.network is None
    assert "REACTION_NETWORK_DISCONNECTED" in {item.code for item in disconnected.diagnostics}
    assert unreachable.network is None
    assert "REACTION_NETWORK_TERMINAL_UNREACHABLE" in {
        item.code for item in unreachable.diagnostics
    }
    assert oxygen and nitrogen and atom


def test_she_che_applies_explicit_potential_and_ph_terms(tmp_path: Path) -> None:
    base = _base_free_energy(tmp_path)
    protocol = _che_protocol(ReferenceElectrode.SHE)
    review = record_definition_review(
        protocol,
        accepted=True,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-16T11:30:00Z",
        note="Synthetic CHE protocol review.",
    )

    report = apply_computational_hydrogen_electrode(
        base,
        protocol,
        proton_electron_pairs_consumed=Fraction(1, 1),
        reviews=(review,),
    )
    expected_ph = 8.617333262145e-5 * 298.15 * math.log(10.0) * 7.0

    assert report.status == "derived"
    assert report.potential_correction_ev == pytest.approx(-0.8)
    assert report.ph_correction_ev == pytest.approx(expected_ph)
    assert report.electrochemical_correction_ev == pytest.approx(-0.8 + expected_ph)
    assert report.value_ev == pytest.approx(base.value_ev - 0.8 + expected_ph)
    assert report.source_sha256s == ("a" * 64, "b" * 64)
    assert report.computational_hydrogen_electrode_applied is True
    assert report.positive_pairs_consumed_negative_potential_lowers_free_energy is True
    assert report.uncertainty_model_applied is False
    assert is_intact_computational_hydrogen_electrode_report(report) is True
    assert (
        is_intact_computational_hydrogen_electrode_report(
            replace(report, value_ev=report.value_ev + 1.0)
        )
        is False
    )


def test_rhe_absorbs_ph_term_and_missing_review_blocks_derivation(tmp_path: Path) -> None:
    base = _base_free_energy(tmp_path)
    protocol = _che_protocol(ReferenceElectrode.RHE)
    review = _approved(protocol)

    report = apply_computational_hydrogen_electrode(
        base,
        protocol,
        proton_electron_pairs_consumed="2",
        reviews=(review,),
    )
    blocked = apply_computational_hydrogen_electrode(
        base,
        protocol,
        proton_electron_pairs_consumed=1,
        reviews=(),
    )

    assert report.ph_correction_ev == 0.0
    assert report.potential_correction_ev == pytest.approx(-1.6)
    assert blocked.status == "not_derived"
    assert blocked.electrochemical_correction_included is False
    assert blocked.computational_hydrogen_electrode_applied is False
    assert blocked.value_ev is None
    assert "SCIENTIFIC_DEFINITION_APPROVAL_MISSING_OR_AMBIGUOUS" in {
        item.code for item in blocked.diagnostics
    }


def test_che_rejects_unknown_temperature_zero_pairs_and_tampered_base(tmp_path: Path) -> None:
    base = _base_free_energy(tmp_path)
    with pytest.raises(ValueError, match="finite"):
        create_computational_hydrogen_electrode_protocol(
            protocol_id="missing-temperature",
            reference_electrode=ReferenceElectrode.SHE,
            electrode_potential_v=0.0,
            ph=0.0,
            temperature_kelvin=None,  # type: ignore[arg-type]
            source_reference="Missing value must not default.",
            source_sha256s=("a" * 64,),
        )
    protocol = _che_protocol()
    review = _approved(protocol)
    with pytest.raises(ValueError, match="non-zero"):
        apply_computational_hydrogen_electrode(
            base,
            protocol,
            proton_electron_pairs_consumed=0,
            reviews=(review,),
        )
    with pytest.raises(ValueError, match="intact"):
        apply_computational_hydrogen_electrode(
            replace(base, value_ev=base.value_ev + 1.0),
            protocol,
            proton_electron_pairs_consumed=1,
            reviews=(review,),
        )


def _requirement(
    requirement_id: str,
    status: RequirementStatus,
    *,
    required: bool = True,
):
    return create_scientific_case_requirement(
        requirement_id=requirement_id,
        category=RequirementCategory.STRUCTURE,
        description=f"Synthetic requirement {requirement_id}.",
        required=required,
        status=status,
        evidence_sha256s=("a" * 64,) if status is RequirementStatus.SATISFIED else (),
        note="Synthetic explicit assessment.",
        assessed_by="synthetic-scientist",
        assessed_at_utc="2026-07-16T12:00:00Z",
    )


def test_scientific_case_readiness_is_fail_closed_and_non_authorizing() -> None:
    satisfied = _requirement("source-reviewed", RequirementStatus.SATISFIED)
    blocked = _requirement("coordinates-missing", RequirementStatus.BLOCKED)

    report = assess_scientific_case_readiness("synthetic-case", (blocked, satisfied))
    ready = assess_scientific_case_readiness(
        "synthetic-case",
        (satisfied, _requirement("coordinates-ready", RequirementStatus.SATISFIED)),
    )

    assert report.status == "blocked"
    assert report.blocking_requirement_ids == ("coordinates-missing",)
    assert report.execution_authorized is False
    assert ready.status == "ready"
    assert ready.execution_authorized is False
    assert len(ready.report_sha256) == 64
    with pytest.raises(ValueError, match="intact"):
        assess_scientific_case_readiness(
            "synthetic-case",
            (replace(satisfied, note="Changed after assessment."),),
        )


def test_readiness_requirement_never_defaults_missing_evidence_to_satisfied() -> None:
    with pytest.raises(ValueError, match="evidence"):
        create_scientific_case_requirement(
            requirement_id="missing-evidence",
            category=RequirementCategory.RESULTS,
            description="Missing evidence must remain blocked.",
            required=True,
            status=RequirementStatus.SATISFIED,
            evidence_sha256s=(),
            note="No evidence supplied.",
            assessed_by="synthetic-scientist",
            assessed_at_utc="2026-07-16T12:00:00Z",
        )
    optional = _requirement(
        "optional-not-applicable",
        RequirementStatus.NOT_APPLICABLE,
        required=False,
    )
    assert optional.status is RequirementStatus.NOT_APPLICABLE
    assert "path" not in json.dumps(optional.to_dict()).lower()
