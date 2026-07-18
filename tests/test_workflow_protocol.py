from __future__ import annotations

import json
from pathlib import Path

import pytest

from catex.workflow.protocol import (
    parse_scientific_protocol,
    record_protocol_review,
    resolve_protocol,
)

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic" / "workflow"


def _resolve(protocol: Path | None = None):
    return resolve_protocol(
        protocol or FIXTURE / "protocol.json",
        poscar_path=FIXTURE / "POSCAR",
        potcar_metadata_path=FIXTURE / "potcar-metadata.json",
    )


def _protocol_payload() -> dict:
    return json.loads((FIXTURE / "protocol.json").read_text(encoding="utf-8"))


def test_resolve_protocol_is_deterministic_and_review_gated() -> None:
    first = _resolve()
    second = _resolve()

    assert not first.has_errors
    assert first.status == "review_pending"
    assert first.resolved is not None
    assert second.resolved is not None
    assert first.resolved.energy_family_id == second.resolved.energy_family_id
    assert first.resolved.resolved_protocol_sha256 == second.resolved.resolved_protocol_sha256
    assert first.resolved.incar_text.startswith("EDIFF = 1E-6\nENCUT = 500\n")
    assert first.resolved.kpoints_text.endswith("3 3 3\n0 0 0\n")
    assert [Path(item.path).name for item in first.resolved.source_artifacts] == [
        "protocol.json",
        "POSCAR",
        "potcar-metadata.json",
    ]


def test_energy_family_excludes_runtime_and_output_only_incar(tmp_path) -> None:
    baseline = _resolve().resolved
    assert baseline is not None
    payload = _protocol_payload()
    payload["incar"]["NCORE"] = "8"
    payload["incar"]["LWAVE"] = "T"
    variant_path = tmp_path / "runtime-variant.json"
    variant_path.write_text(json.dumps(payload), encoding="utf-8")

    variant = _resolve(variant_path).resolved

    assert variant is not None
    assert variant.energy_family_id == baseline.energy_family_id
    assert variant.resolved_protocol_sha256 != baseline.resolved_protocol_sha256


def test_energy_family_changes_with_scientific_setting(tmp_path) -> None:
    baseline = _resolve().resolved
    assert baseline is not None
    payload = _protocol_payload()
    payload["incar"]["ENCUT"] = "520"
    variant_path = tmp_path / "scientific-variant.json"
    variant_path.write_text(json.dumps(payload), encoding="utf-8")

    variant = _resolve(variant_path).resolved

    assert variant is not None
    assert variant.energy_family_id != baseline.energy_family_id


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unknown": "value"}),
        lambda payload: payload.update({"target_vasp_version": "6.5"}),
        lambda payload: payload["incar"].update({"ENCUT": "500; SYSTEM = injected"}),
        lambda payload: payload["kpoints"].update({"generation_mode": "automatic-length"}),
    ],
)
def test_protocol_boundary_rejects_ambiguous_or_unsupported_json(mutate) -> None:
    payload = _protocol_payload()
    mutate(payload)

    with pytest.raises(ValueError):
        parse_scientific_protocol(json.dumps(payload))


def test_potcar_species_order_mismatch_blocks_resolution(tmp_path) -> None:
    payload = json.loads((FIXTURE / "potcar-metadata.json").read_text(encoding="utf-8"))
    payload["datasets"].reverse()
    metadata = tmp_path / "wrong-order.json"
    metadata.write_text(json.dumps(payload), encoding="utf-8")

    report = resolve_protocol(
        FIXTURE / "protocol.json",
        poscar_path=FIXTURE / "POSCAR",
        potcar_metadata_path=metadata,
    )

    assert report.has_errors
    assert report.resolved is None
    assert "POTCAR_ORDER_MISMATCH" in {item.code for item in report.diagnostics}


def test_human_review_is_explicit_and_does_not_change_energy_family() -> None:
    pending = _resolve().resolved
    assert pending is not None

    approved = record_protocol_review(
        pending,
        approved=True,
        reviewer="test-reviewer",
        reviewed_at_utc="2026-07-15T12:00:00Z",
        note="Synthetic fixture reviewed.",
    )

    assert approved.approved
    assert approved.energy_family_id == pending.energy_family_id
    assert approved.resolved_protocol_sha256 == pending.resolved_protocol_sha256
    with pytest.raises(ValueError):
        record_protocol_review(
            pending,
            approved=True,
            reviewer="test-reviewer",
            reviewed_at_utc="not-a-time",
            note="",
        )
