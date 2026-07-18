from __future__ import annotations

import json
from pathlib import Path

import pytest

from catex.reactions import (
    ReferenceElectrode,
    create_computational_hydrogen_electrode_protocol,
)
from catex.readiness import (
    RequirementCategory,
    RequirementStatus,
    assess_scientific_case_readiness,
    canonical_text_evidence_sha256,
    create_scientific_case_requirement,
)

PROJECT = Path(__file__).parents[1] / "projects" / "paper4_co2rr_dac_reproduction"


def _load(name: str):
    return json.loads((PROJECT / name).read_text(encoding="utf-8"))


def _canonical_text_sha256(path: Path) -> str:
    return canonical_text_evidence_sha256(path.read_text(encoding="utf-8-sig"))


def test_text_evidence_hash_is_stable_across_git_line_endings() -> None:
    assert canonical_text_evidence_sha256("alpha\r\nbeta\r\n") == (
        canonical_text_evidence_sha256("alpha\nbeta\n")
    )


def test_paper4_production_readiness_manifest_executes_as_a_blocking_gate() -> None:
    payload = _load("production-readiness.json")
    requirements = tuple(
        create_scientific_case_requirement(
            requirement_id=item["requirement_id"],
            category=RequirementCategory(item["category"]),
            description=item["description"],
            required=item["required"],
            status=RequirementStatus(item["status"]),
            evidence_sha256s=tuple(item["evidence_sha256s"]),
            note=item["note"],
            assessed_by=item["assessed_by"],
            assessed_at_utc=item["assessed_at_utc"],
        )
        for item in payload["requirements"]
    )

    report = assess_scientific_case_readiness(payload["case_id"], requirements)

    assert report.status == "blocked"
    assert report.ready_for_production_planning is False
    assert report.execution_authorized is False
    assert len(report.satisfied_requirement_ids) == 3
    assert len(report.blocking_requirement_ids) == 10
    assert {
        "author-equivalent-production-coordinates",
        "per-state-thermochemistry",
        "production-runs-scientifically-accepted",
        "production-storage-policy",
        "table-s2-column-interpretation",
    } <= set(report.blocking_requirement_ids)
    assert all(
        not item.evidence_sha256s
        for item in requirements
        if item.status is RequirementStatus.BLOCKED
    )


def test_paper4_satisfied_evidence_hashes_are_valid_and_match_available_artifacts() -> None:
    payload = _load("production-readiness.json")
    by_id = {item["requirement_id"]: item for item in payload["requirements"]}
    evidence_artifacts = {
        "paper-si-sources-reviewed": (
            PROJECT / "references" / "paper-main-extracted.txt",
            PROJECT / "references" / "si-extracted.txt",
        ),
        "table-s2-digitized": (PROJECT / "results" / "reference_table_s2.csv",),
        "hpc-environment-smoke-verified": (PROJECT / "hpc" / "README.md",),
    }

    for requirement_id, paths in evidence_artifacts.items():
        recorded = set(by_id[requirement_id]["evidence_sha256s"])
        assert recorded
        assert all(len(item) == 64 and int(item, 16) >= 0 for item in recorded)
        # Copyright/data-policy exclusions make some source artifacts local-only.
        # Rehash every artifact available in this checkout without requiring excluded files in CI.
        available_hashes = {_canonical_text_sha256(path) for path in paths if path.is_file()}
        assert available_hashes <= recorded


def test_paper4_network_draft_keeps_both_paths_identity_blocked() -> None:
    payload = _load("reaction-network-draft.json")
    reactions = {item["reaction_id"]: item for item in payload["reactions"]}

    assert payload["network_id"] is None
    assert payload["status"] == "identity_blocked"
    assert payload["manual_review_status"] == "blocked"
    assert all(item["identity_sha256"] is None for item in payload["states"])
    assert all(item["reaction_identity_sha256"] is None for item in reactions.values())
    assert {
        "co-path-pcet-1",
        "co-path-pcet-2",
        "co-desorption",
        "hcooh-path-pcet-1",
        "hcooh-path-pcet-2",
    } <= set(reactions)
    assert reactions["co-path-pcet-1"]["proton_electron_pairs_consumed"] == 1
    assert reactions["hcooh-path-pcet-2"]["proton_electron_pairs_consumed"] == 1


def test_paper4_che_draft_refuses_to_default_missing_temperature() -> None:
    payload = _load("che-protocol-draft.json")

    assert payload["reference_electrode"] == "SHE"
    assert payload["pH"] == 0.0
    assert payload["temperature_kelvin"] is None
    assert payload["status"] == "blocked_missing_temperature"
    with pytest.raises(ValueError, match="finite"):
        create_computational_hydrogen_electrode_protocol(
            protocol_id=payload["protocol_id"],
            reference_electrode=ReferenceElectrode(payload["reference_electrode"]),
            electrode_potential_v=payload["electrode_potential_v"],
            ph=payload["pH"],
            temperature_kelvin=payload["temperature_kelvin"],
            source_reference="Paper 4 SI CHE method draft.",
            source_sha256s=tuple(payload["source_sha256s"]),
        )


def test_paper4_thermochemistry_unknowns_are_null_not_zero() -> None:
    payload = _load("thermochemistry-requirements.json")
    component_keys = (
        "zero_point_energy_eV",
        "thermal_enthalpy_eV",
        "entropy_eV_per_kelvin",
        "solvation_free_energy_eV",
        "other_free_energy_eV",
    )

    assert payload["temperature_kelvin"] is None
    assert payload["status"] == "blocked_missing_sources"
    assert {item["state_id"] for item in payload["states"]} >= {
        "co2-gas",
        "cooh-adsorbed",
        "ocho-adsorbed",
        "co-gas",
        "hcooh-liquid",
    }
    assert all(item[key] is None for item in payload["states"] for key in component_keys)
    assert all(item["source_status"].startswith("missing_") for item in payload["states"])
