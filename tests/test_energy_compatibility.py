from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_hpc_run_binding import _bound_run, _validate

from catex.energetics import (
    EnergyTerm,
    VaspEnergyKind,
    assess_energy_compatibility,
    bind_reviewed_vasp_energy,
    derive_linear_energy,
)
from catex.results import record_scientific_result_review
from catex.vasp import parse_vasp_output


def _accepted_energy(
    parent: Path,
    *,
    energy_id: str,
    kind: VaspEnergyKind = VaspEnergyKind.FREE_ENERGY_TOTEN,
    family_hex: str = "d",
):
    parent.mkdir()
    directory, receipt, snapshot = _bound_run(parent)
    manifest_path = directory / "catex-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["energy_family_id"] = f"sha256:{family_hex * 64}"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    binding = _validate(directory, receipt, snapshot)
    review = record_scientific_result_review(
        binding,
        accepted=True,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="Synthetic energy review.",
    )
    report = parse_vasp_output(directory)
    record = bind_reviewed_vasp_energy(
        review,
        report,
        energy_id=energy_id,
        kind=kind,
    )
    return record, review, report, directory


@pytest.mark.parametrize(
    ("kind", "expected", "expected_evidence"),
    [
        (VaspEnergyKind.FREE_ENERGY_TOTEN, -10.25, {"OUTCAR", "OSZICAR"}),
        (VaspEnergyKind.ENERGY_WITHOUT_ENTROPY, -10.24, {"OUTCAR"}),
        (VaspEnergyKind.SIGMA_ZERO, -10.245, {"OUTCAR", "OSZICAR"}),
    ],
)
def test_bind_reviewed_energy_keeps_vasp_fields_explicit_and_sanitized(
    tmp_path: Path,
    kind: VaspEnergyKind,
    expected: float,
    expected_evidence: set[str],
) -> None:
    record, _, _, directory = _accepted_energy(
        tmp_path / kind.value,
        energy_id=f"energy-{kind.value}",
        kind=kind,
    )
    serialized = json.dumps(record.to_dict())

    assert record.value_ev == pytest.approx(expected)
    assert record.kind is kind
    assert record.scientific_result_accepted is True
    assert record.eligible_for_same_energy_family_derivation is True
    assert len(record.record_sha256) == 64
    assert {item.artifact_name for item in record.evidence} == expected_evidence
    assert str(directory.parent) not in serialized
    assert record.writes_performed is False
    assert record.commands_executed is False


def test_rejected_review_cannot_create_reviewed_energy(tmp_path: Path) -> None:
    directory, receipt, snapshot = _bound_run(tmp_path)
    binding = _validate(directory, receipt, snapshot)
    review = record_scientific_result_review(
        binding,
        accepted=False,
        reviewer="synthetic-scientist",
        reviewed_at_utc="2026-07-15T13:00:00Z",
        note="Rejected after manual inspection.",
    )

    with pytest.raises(ValueError, match="explicit human acceptance"):
        bind_reviewed_vasp_energy(
            review,
            parse_vasp_output(directory),
            energy_id="rejected",
            kind=VaspEnergyKind.FREE_ENERGY_TOTEN,
        )


def test_reviewed_energy_rechecks_artifact_hashes_and_directory(tmp_path: Path) -> None:
    _, review, report, directory = _accepted_energy(
        tmp_path / "original",
        energy_id="original",
    )
    with (directory / "OSZICAR").open("ab") as stream:
        stream.write(b"\n")
    changed = parse_vasp_output(directory)

    with pytest.raises(ValueError, match="artifact hashes"):
        bind_reviewed_vasp_energy(
            review,
            changed,
            energy_id="changed",
            kind=VaspEnergyKind.FREE_ENERGY_TOTEN,
        )
    with pytest.raises(ValueError, match="directory"):
        bind_reviewed_vasp_energy(
            review,
            replace(report, directory=str(tmp_path / "another-directory")),
            energy_id="wrong-directory",
            kind=VaspEnergyKind.FREE_ENERGY_TOTEN,
        )
    with pytest.raises(ValueError, match=r"VASP 5\.4\.4"):
        bind_reviewed_vasp_energy(
            review,
            replace(report, detected_vasp_version="6.4.3"),
            energy_id="wrong-version",
            kind=VaspEnergyKind.FREE_ENERGY_TOTEN,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"note": "Changed after the recorded decision."},
        {"vasp_artifact_names_and_sha256": ()},
        {"scheduler_elapsed_seconds": 42},
    ],
)
def test_modified_review_content_or_binding_identity_cannot_bind_energy(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    _, review, report, _ = _accepted_energy(tmp_path / "record", energy_id="record")

    with pytest.raises(ValueError, match="provenance identity"):
        bind_reviewed_vasp_energy(
            replace(review, **mutation),
            report,
            energy_id="altered-review",
            kind=VaspEnergyKind.FREE_ENERGY_TOTEN,
        )


def test_same_family_and_kind_are_compatible_and_derive_deterministically(
    tmp_path: Path,
) -> None:
    first, _, _, _ = _accepted_energy(tmp_path / "first", energy_id="surface")
    second, _, _, _ = _accepted_energy(tmp_path / "second", energy_id="adsorbate")

    compatibility = assess_energy_compatibility((first, second))
    derivation = derive_linear_energy(
        (EnergyTerm(2, first), EnergyTerm(-1, second)),
        derivation_id="generic-difference",
    )
    repeated = derive_linear_energy(
        (EnergyTerm(2, first), EnergyTerm(-1, second)),
        derivation_id="generic-difference",
    )

    assert compatibility.compatible is True
    assert compatibility.common_energy_family_id == first.energy_family_id
    assert compatibility.common_kind is VaspEnergyKind.FREE_ENERGY_TOTEN
    assert derivation.status == "derived"
    assert derivation.value_ev == pytest.approx(-10.25)
    assert derivation.derivation_sha256 == repeated.derivation_sha256
    assert derivation.scientific_interpretation_approved is False
    assert derivation.reference_state_reviewed is False
    assert derivation.thermochemical_corrections_included is False


def test_cross_family_and_mixed_energy_kinds_fail_closed(tmp_path: Path) -> None:
    first, _, _, _ = _accepted_energy(tmp_path / "first", energy_id="first")
    other_family, _, _, _ = _accepted_energy(
        tmp_path / "other-family",
        energy_id="other-family",
        family_hex="e",
    )
    other_kind, _, _, _ = _accepted_energy(
        tmp_path / "other-kind",
        energy_id="other-kind",
        kind=VaspEnergyKind.SIGMA_ZERO,
    )

    family_report = derive_linear_energy(
        (EnergyTerm(1, first), EnergyTerm(-1, other_family)),
        derivation_id="cross-family",
    )
    kind_report = derive_linear_energy(
        (EnergyTerm(1, first), EnergyTerm(-1, other_kind)),
        derivation_id="mixed-kind",
    )

    assert family_report.value_ev is None
    assert family_report.derivation_sha256 is None
    assert "ENERGY_FAMILY_MISMATCH" in {item.code for item in family_report.diagnostics}
    assert kind_report.value_ev is None
    assert "ENERGY_KIND_MISMATCH" in {item.code for item in kind_report.diagnostics}


@pytest.mark.parametrize(
    "mutation",
    [
        {"scientific_result_accepted": False},
        {"automatic_acceptance_performed": True},
        {"value_ev": -999.0},
        {"energy_family_id": f"sha256:{'e' * 64}"},
        {"schema_version": "catex.reviewed-energy.v999"},
    ],
)
def test_modified_or_ineligible_reviewed_record_is_rejected(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    record, _, _, _ = _accepted_energy(tmp_path / "record", energy_id="record")
    altered = replace(record, **mutation)

    compatibility = assess_energy_compatibility((altered,))

    assert compatibility.compatible is False
    assert {item.code for item in compatibility.diagnostics} == {"ENERGY_INPUT_NOT_ACCEPTED"}


def test_empty_duplicate_and_invalid_coefficients_do_not_derive(tmp_path: Path) -> None:
    record, _, _, _ = _accepted_energy(tmp_path / "record", energy_id="record")

    empty = derive_linear_energy((), derivation_id="empty")
    duplicate = derive_linear_energy(
        (EnergyTerm(1, record), EnergyTerm(-1, record)),
        derivation_id="duplicate",
    )
    zero = derive_linear_energy((EnergyTerm(0, record),), derivation_id="zero")
    nonfinite = derive_linear_energy(
        (EnergyTerm(float("nan"), record),),
        derivation_id="nonfinite",
    )
    overflow = derive_linear_energy(
        (EnergyTerm(1.7e308, record),),
        derivation_id="overflow",
    )

    assert empty.value_ev is None
    assert "ENERGY_INPUTS_EMPTY" in {item.code for item in empty.diagnostics}
    assert duplicate.value_ev is None
    assert "ENERGY_ID_DUPLICATED" in {item.code for item in duplicate.diagnostics}
    assert zero.value_ev is None
    assert "ENERGY_COEFFICIENT_INVALID" in {item.code for item in zero.diagnostics}
    assert nonfinite.value_ev is None
    assert "ENERGY_COEFFICIENT_INVALID" in {item.code for item in nonfinite.diagnostics}
    assert overflow.value_ev is None
    assert "ENERGY_ARITHMETIC_NONFINITE" in {item.code for item in overflow.diagnostics}


@pytest.mark.parametrize("identifier", ["", "bad/id", "bad\\id", "x" * 101])
def test_energy_and_derivation_identifiers_are_restricted(
    tmp_path: Path,
    identifier: str,
) -> None:
    record, review, report, _ = _accepted_energy(tmp_path / "record", energy_id="valid")

    with pytest.raises(ValueError, match="safe identifier"):
        bind_reviewed_vasp_energy(
            review,
            report,
            energy_id=identifier,
            kind=VaspEnergyKind.FREE_ENERGY_TOTEN,
        )
    with pytest.raises(ValueError, match="safe identifier"):
        derive_linear_energy((EnergyTerm(1, record),), derivation_id=identifier)
