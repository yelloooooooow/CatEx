from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from catex.cli import main
from catex.hpc.potcar_metadata import extract_potcar_metadata, metadata_document
from catex.models import ArtifactRecord
from catex.vasp.potcar import parse_potcar_metadata

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic" / "hpc" / "synthetic-potcar.txt"


def test_authorization_gate_precedes_any_file_access(tmp_path) -> None:
    missing = tmp_path / "not-opened"

    report = extract_potcar_metadata(
        missing,
        potential_family="PAW_PBE_54",
        authorized_hpc_read=False,
    )

    assert report.status == "error"
    assert report.source_sha256 is None
    assert report.datasets == ()
    assert {item.code for item in report.diagnostics} == {"POTCAR_HPC_AUTHORIZATION_REQUIRED"}

    authorized_missing = extract_potcar_metadata(
        missing,
        potential_family="PAW_PBE_54",
        authorized_hpc_read=True,
    )
    assert {item.code for item in authorized_missing.diagnostics} == {"POTCAR_READ_FAILED"}
    assert str(tmp_path) not in json.dumps(authorized_missing.to_dict())


def test_streaming_extraction_emits_only_safe_metadata_and_exact_hashes() -> None:
    data = FIXTURE.read_bytes()
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    marker = b"End of Dataset" + newline
    first, remainder = data.split(marker, 1)
    second, trailing = remainder.split(marker, 1)
    assert trailing == b""

    report = extract_potcar_metadata(
        FIXTURE,
        potential_family="PAW_PBE_54",
        authorized_hpc_read=True,
    )
    payload = report.to_dict()

    assert report.status == "metadata_ready"
    assert report.source_name == "synthetic-potcar.txt"
    assert report.source_sha256 == hashlib.sha256(data).hexdigest()
    assert report.source_size_bytes == len(data)
    assert report.raw_content_included is False
    assert report.writes_performed is False
    assert [item.element for item in report.datasets] == ["Na", "Cl"]
    assert report.datasets[0].sha256 == hashlib.sha256(first + marker).hexdigest()
    assert report.datasets[1].sha256 == hashlib.sha256(second + marker).hexdigest()
    assert "SYNTHETIC_TABLE_VALUES" not in json.dumps(payload)
    assert str(FIXTURE.parent) not in json.dumps(payload)


def test_extracted_document_roundtrips_through_existing_metadata_parser() -> None:
    report = extract_potcar_metadata(
        FIXTURE,
        potential_family="PAW_PBE_54",
        authorized_hpc_read=True,
    )
    document = metadata_document(report)
    encoded = json.dumps(document)
    artifact = ArtifactRecord("safe-metadata.json", "f" * 64, len(encoded))

    parsed, diagnostics = parse_potcar_metadata(encoded, artifact=artifact)

    assert diagnostics == ()
    assert parsed is not None
    assert parsed.potential_family == "PAW_PBE_54"
    assert [item.potential_label for item in parsed.datasets] == ["Na_pv", "Cl"]


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", "POTCAR_EMPTY"),
        (b"TITEL = PAW_PBE Na SYNTHETIC\nEnd of Dataset\n", "POTCAR_HEADER_FIELD_MISSING"),
        (
            b"TITEL = PAW_PBE Na SYNTHETIC\nLEXCH=PE\nZVAL=1\nENMAX=1\n",
            "POTCAR_DATASET_TERMINATOR_MISSING",
        ),
    ],
)
def test_incomplete_synthetic_streams_never_emit_partial_metadata(tmp_path, content, code) -> None:
    source = tmp_path / "synthetic-input.txt"
    source.write_bytes(content)

    report = extract_potcar_metadata(
        source,
        potential_family="PAW_PBE_54",
        authorized_hpc_read=True,
    )

    assert report.has_errors
    assert report.datasets == ()
    assert report.metadata_document is None
    assert code in {item.code for item in report.diagnostics}
    with pytest.raises(ValueError):
        metadata_document(report)


def test_invalid_family_is_rejected_before_read() -> None:
    with pytest.raises(ValueError):
        extract_potcar_metadata(
            FIXTURE,
            potential_family="bad family; command",
            authorized_hpc_read=True,
        )


def test_potcar_metadata_cli_requires_gate_and_can_emit_downstream_json(capsys) -> None:
    blocked_exit = main(
        [
            "extract-potcar-metadata",
            str(FIXTURE),
            "--potential-family",
            "PAW_PBE_54",
            "--format",
            "json",
        ]
    )
    blocked = json.loads(capsys.readouterr().out)
    success_exit = main(
        [
            "extract-potcar-metadata",
            str(FIXTURE),
            "--potential-family",
            "PAW_PBE_54",
            "--authorized-hpc-read",
            "--format",
            "metadata-json",
        ]
    )
    metadata = json.loads(capsys.readouterr().out)
    text_exit = main(
        [
            "extract-potcar-metadata",
            str(FIXTURE),
            "--potential-family",
            "PAW_PBE_54",
            "--authorized-hpc-read",
        ]
    )
    text = capsys.readouterr().out

    assert blocked_exit == 1
    assert blocked["authorized_hpc_read"] is False
    assert success_exit == 0
    assert metadata["schema_version"] == "catex.potcar-metadata.v1"
    assert [item["element"] for item in metadata["datasets"]] == ["Na", "Cl"]
    assert text_exit == 0
    assert "raw_content_included: false" in text
    assert str(FIXTURE.parent) not in text
