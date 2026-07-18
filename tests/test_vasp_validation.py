from __future__ import annotations

import json
from pathlib import Path

from pymatgen.core import Lattice, Structure
from pymatgen.io.vasp import Poscar

from catex.cli import main
from catex.models import Severity
from catex.vasp.models import ValidationMode
from catex.vasp.validation import validate_vasp_input


def _codes(report) -> set[str]:
    return {item.code for item in report.diagnostics}


def _metadata() -> dict:
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


def _write_valid_directory(root: Path) -> Path:
    root.mkdir()
    structure = Structure(
        Lattice.from_parameters(4, 4, 20, 90, 90, 90),
        ["Na", "Cl"],
        [[0.25, 0.25, 0.45], [0.75, 0.75, 0.55]],
    )
    (root / "POSCAR").write_text(str(Poscar(structure)), encoding="utf-8")
    (root / "INCAR").write_text(
        "ENCUT=500\nEDIFF=1E-5\nISPIN=2\nMAGMOM=1 -1\nNSW=0\nLDIPOL=T\nIDIPOL=3\n",
        encoding="utf-8",
    )
    (root / "KPOINTS").write_text("mesh\n0\nGamma\n3 3 1\n", encoding="utf-8")
    (root / "catex-potcar-metadata.json").write_text(json.dumps(_metadata()), encoding="utf-8")
    return root


def test_complete_strict_directory_passes_without_errors(tmp_path) -> None:
    root = _write_valid_directory(tmp_path / "calc")

    report = validate_vasp_input(root, mode=ValidationMode.STRICT)

    assert report.status == "ok"
    assert report.structure is not None
    assert report.structure.num_sites == 2
    assert report.poscar_species_order == ("Na", "Cl")
    assert report.incar is not None
    assert report.kpoints is not None
    assert report.potcar_metadata is not None
    assert len(report.artifacts) == 4


def test_missing_metadata_is_error_in_strict_and_warning_in_exploration(tmp_path) -> None:
    root = _write_valid_directory(tmp_path / "calc")
    (root / "catex-potcar-metadata.json").unlink()

    strict = validate_vasp_input(root, mode="strict")
    exploration = validate_vasp_input(root, mode="exploration")

    strict_finding = next(
        item for item in strict.diagnostics if item.code == "POTCAR_METADATA_MISSING"
    )
    exploration_finding = next(
        item for item in exploration.diagnostics if item.code == "POTCAR_METADATA_MISSING"
    )
    assert strict_finding.severity is Severity.ERROR
    assert exploration_finding.severity is Severity.WARNING
    assert not exploration.has_errors


def test_raw_potcar_is_detected_but_never_recorded_as_artifact(tmp_path) -> None:
    root = _write_valid_directory(tmp_path / "calc")
    raw = root / "POTCAR"
    raw.write_text("synthetic test marker", encoding="utf-8")
    before = raw.read_bytes()

    report = validate_vasp_input(root)

    assert "RAW_POTCAR_PRESENT_NOT_READ" in _codes(report)
    assert raw.read_bytes() == before
    assert all(Path(item.path).name != "POTCAR" for item in report.artifacts)


def test_missing_directory_and_required_files_return_reports(tmp_path) -> None:
    missing = validate_vasp_input(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    incomplete = validate_vasp_input(empty)

    assert _codes(missing) == {"VASP_INPUT_DIRECTORY_NOT_FOUND"}
    assert {
        "POSCAR_FILE_NOT_FOUND",
        "INCAR_FILE_NOT_FOUND",
        "KPOINTS_FILE_NOT_FOUND",
        "POTCAR_METADATA_MISSING",
    } <= _codes(incomplete)


def test_invalid_poscar_and_kpoints_are_structured_failures(tmp_path) -> None:
    root = tmp_path / "broken"
    root.mkdir()
    (root / "POSCAR").write_text("broken", encoding="utf-8")
    (root / "INCAR").write_text("ENCUT=500\n", encoding="utf-8")
    (root / "KPOINTS").write_text("broken\n0\nUnknown\n", encoding="utf-8")

    report = validate_vasp_input(root, mode="exploration")

    assert "POSCAR_PARSE_FAILED" in _codes(report)
    assert "KPOINTS_PARSE_FAILED" in _codes(report)
    assert "KPOINTS_MODE_UNSUPPORTED" in _codes(report)


def test_relative_metadata_override_is_resolved_inside_directory(tmp_path) -> None:
    root = _write_valid_directory(tmp_path / "calc")
    default = root / "catex-potcar-metadata.json"
    override = root / "metadata" / "safe.json"
    override.parent.mkdir()
    override.write_bytes(default.read_bytes())
    default.unlink()

    report = validate_vasp_input(root, potcar_metadata_path="metadata/safe.json")

    assert report.potcar_metadata is not None
    assert Path(report.potcar_metadata.artifact.path) == override


def test_dipole_axis_mismatch_is_mode_dependent(tmp_path) -> None:
    root = _write_valid_directory(tmp_path / "calc")
    incar = root / "INCAR"
    incar.write_text(
        incar.read_text(encoding="utf-8").replace("IDIPOL=3", "IDIPOL=1"), encoding="utf-8"
    )

    strict = validate_vasp_input(root, mode="strict")
    exploration = validate_vasp_input(root, mode="exploration")

    assert (
        next(
            item for item in strict.diagnostics if item.code == "IDIPOL_VACUUM_AXIS_MISMATCH"
        ).severity
        is Severity.ERROR
    )
    assert (
        next(
            item for item in exploration.diagnostics if item.code == "IDIPOL_VACUUM_AXIS_MISMATCH"
        ).severity
        is Severity.WARNING
    )


def test_validate_vasp_cli_emits_json_and_text(tmp_path, capsys) -> None:
    root = _write_valid_directory(tmp_path / "calc")

    json_exit = main(["validate-vasp-input", str(root), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    text_exit = main(["validate-vasp-input", str(root), "--format", "text"])
    text = capsys.readouterr().out

    assert json_exit == 0
    assert payload["schema_version"] == "catex.vasp-input-validation.v1"
    assert payload["target_vasp_version"] == "5.4.4"
    assert text_exit == 0
    assert "status: ok" in text
    assert "kpoints_subdivisions: 3 3 1" in text


def test_paper4_nizn_inputs_pass_exploration_without_runtime_claims() -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "projects"
        / "paper4_co2rr_dac_reproduction"
        / "structures"
        / "environment_smoke_test"
        / "NiZn_NC"
    )

    report = validate_vasp_input(root, mode="exploration")

    assert report.structure is not None
    assert report.structure.num_sites == 70
    assert report.poscar_species_order == ("Ni", "Zn", "C", "N")
    assert not report.has_errors
    assert "POTCAR_METADATA_MISSING" in _codes(report)
    assert "VASPSOL_CAPABILITY_REQUIRES_RUNTIME_CHECK" in _codes(report)
