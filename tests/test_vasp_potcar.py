from __future__ import annotations

import json

import pytest

from catex.models import ArtifactRecord, Severity
from catex.vasp.models import ValidationMode
from catex.vasp.potcar import parse_potcar_metadata, validate_potcar_metadata


def _artifact() -> ArtifactRecord:
    return ArtifactRecord("metadata.json", "f" * 64, 100)


def _payload() -> dict:
    return {
        "schema_version": "catex.potcar-metadata.v1",
        "potential_family": "PAW_PBE",
        "datasets": [
            {
                "element": "Na",
                "potential_label": "Na_pv",
                "titel": "PAW_PBE Na_pv 01Jan2000",
                "lexch": "PE",
                "zval": 9,
                "enmax_eV": 400,
                "sha256": "a" * 64,
            },
            {
                "element": "Cl",
                "potential_label": "Cl",
                "titel": "PAW_PBE Cl 01Jan2000",
                "lexch": "PE",
                "zval": 7,
                "enmax_eV": 450,
                "sha256": "b" * 64,
            },
        ],
    }


def _codes(diagnostics) -> set[str]:
    return {item.code for item in diagnostics}


def test_parse_complete_metadata() -> None:
    metadata, diagnostics = parse_potcar_metadata(json.dumps(_payload()), artifact=_artifact())

    assert diagnostics == ()
    assert metadata is not None
    assert metadata.maximum_enmax_ev == 450
    assert metadata.to_dict()["datasets"][0]["potential_label"] == "Na_pv"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("{", "POTCAR_METADATA_JSON_INVALID"),
        ("[]", "POTCAR_METADATA_ROOT_INVALID"),
        (json.dumps({"schema_version": "wrong"}), "POTCAR_METADATA_SCHEMA_UNSUPPORTED"),
        (
            json.dumps(
                {
                    "schema_version": "catex.potcar-metadata.v1",
                    "potential_family": "PAW_PBE",
                    "datasets": [],
                }
            ),
            "POTCAR_METADATA_DATASETS_INVALID",
        ),
    ],
)
def test_metadata_root_failures(text, code) -> None:
    metadata, diagnostics = parse_potcar_metadata(text, artifact=_artifact())

    assert metadata is None
    assert code in _codes(diagnostics)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("element", "Xx"),
        ("zval", 0),
        ("enmax_eV", "bad"),
        ("sha256", "short"),
    ],
)
def test_invalid_dataset_fields_are_rejected(field, value) -> None:
    payload = _payload()
    payload["datasets"][0][field] = value

    metadata, diagnostics = parse_potcar_metadata(json.dumps(payload), artifact=_artifact())

    assert metadata is None
    assert "POTCAR_METADATA_DATASET_INVALID" in _codes(diagnostics)


def test_order_lexch_label_and_encut_rules() -> None:
    payload = _payload()
    payload["datasets"][0]["lexch"] = "CA"
    payload["datasets"][1]["potential_label"] = "Cl_h"
    metadata, _ = parse_potcar_metadata(json.dumps(payload), artifact=_artifact())
    assert metadata is not None

    diagnostics = validate_potcar_metadata(
        metadata,
        poscar_species_order=("Cl", "Na"),
        encut_ev=300,
        mode=ValidationMode.STRICT,
    )
    codes = _codes(diagnostics)

    assert "POTCAR_ORDER_MISMATCH" in codes
    assert "POTCAR_LEXCH_FAMILY_MISMATCH" in codes
    assert "POTCAR_TITEL_LABEL_MISMATCH" in codes
    assert "ENCUT_BELOW_POTCAR_ENMAX" in codes
    assert (
        next(item for item in diagnostics if item.code == "ENCUT_BELOW_POTCAR_ENMAX").severity
        is Severity.ERROR
    )
