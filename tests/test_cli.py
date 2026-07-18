from __future__ import annotations

import json
from pathlib import Path

from catex.cli import main


def test_inspect_cli_emits_versioned_json(tmp_path, nacl_structure, capsys) -> None:
    source = tmp_path / "POSCAR"
    nacl_structure.to(filename=source, fmt="poscar")

    exit_code = main(["inspect-structure", str(source), "--format", "json"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["schema_version"] == "catex.inspection.v1"
    assert output["record"]["schema_version"] == "catex.structure.v1"
    assert output["record"]["num_sites"] == 2


def test_compare_cli_uses_nonzero_exit_for_non_equivalence(
    tmp_path, nacl_structure, capsys
) -> None:
    source_a = tmp_path / "a.cif"
    source_b = tmp_path / "b.cif"
    changed = nacl_structure.copy()
    changed.replace(0, "K")
    nacl_structure.to(filename=source_a, fmt="cif")
    changed.to(filename=source_b, fmt="cif")

    exit_code = main(["compare-structures", str(source_a), str(source_b), "--format", "json"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["equivalent"] is False
    assert output["status"] == "not_equivalent"


def test_inspect_cli_reports_missing_file_as_json(tmp_path, capsys) -> None:
    exit_code = main(["inspect-structure", str(tmp_path / "missing.cif"), "--format", "json"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["status"] == "error"
    assert output["diagnostics"][0]["code"] == "STRUCTURE_FILE_NOT_FOUND"


def test_text_cli_renders_inspection_and_equivalent_comparison(
    tmp_path, nacl_structure, capsys
) -> None:
    source = tmp_path / "POSCAR"
    nacl_structure.to(filename=source, fmt="poscar")

    inspect_exit = main(["inspect-structure", str(source)])
    inspect_output = capsys.readouterr().out
    compare_exit = main(["compare-structures", str(source), str(source)])
    compare_output = capsys.readouterr().out

    assert inspect_exit == 0
    assert "status: ok" in inspect_output
    assert "formula: Na1 Cl1" in inspect_output
    assert compare_exit == 0
    assert "equivalent: true" in compare_output
    assert "STRUCTURES_EQUIVALENT" in compare_output


def test_parse_vasp_output_cli_emits_json_and_text(capsys) -> None:
    fixture = Path(__file__).parent / "fixtures" / "synthetic" / "vasp_output" / "normal"

    json_exit = main(["parse-vasp-output", str(fixture), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    text_exit = main(["parse-vasp-output", str(fixture)])
    rendered = capsys.readouterr().out

    assert json_exit == 0
    assert payload["schema_version"] == "catex.vasp-output-parse.v1"
    assert payload["status"] == "normal"
    assert payload["scientifically_complete"] is True
    assert text_exit == 0
    assert "electronic_convergence: converged" in rendered
    assert "maximum_force_norm_eV_per_angstrom:" in rendered
    assert "projected_magnetization_components: x" in rendered


def test_parse_vasp_output_cli_rejects_unconverged_run(capsys) -> None:
    fixture = Path(__file__).parent / "fixtures" / "synthetic" / "vasp_output" / "unconverged"

    exit_code = main(["parse-vasp-output", str(fixture), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "unconverged"
    assert payload["scientifically_complete"] is False


def test_materials_studio_capability_and_plan_cli(tmp_path, capsys) -> None:
    runner = tmp_path / "RunMatScript.bat"
    runner.write_text("@echo off\n", encoding="utf-8")
    input_root = tmp_path / "inputs"
    staging_root = tmp_path / "staging"
    input_root.mkdir()
    staging_root.mkdir()
    source = input_root / "source.cif"
    fixture = (
        Path(__file__).parent / "fixtures" / "synthetic" / "materials_studio" / "nacl_input.cif"
    )
    source.write_bytes(fixture.read_bytes())

    capability_exit = main(
        ["materials-studio-capability", "--runner", str(runner), "--format", "json"]
    )
    capability = json.loads(capsys.readouterr().out)
    plan_exit = main(
        [
            "plan-ms-roundtrip",
            str(source),
            "--input-root",
            str(input_root),
            "--staging-root",
            str(staging_root),
            "--runner",
            str(runner),
            "--job-name",
            "cli-plan",
            "--format",
            "json",
        ]
    )
    plan = json.loads(capsys.readouterr().out)

    assert capability_exit == 0
    assert capability["status"] == "available_unverified"
    assert capability["arbitrary_script_supported"] is False
    assert plan_exit == 0
    assert plan["operation"] == "roundtrip_cif_via_xsd"
    assert plan["fixed_output_names"] == ["roundtrip.xsd", "roundtrip.cif"]
    assert not Path(plan["job_directory"]).exists()


def test_materials_studio_text_renderers(tmp_path, capsys) -> None:
    runner = tmp_path / "RunMatScript.bat"
    runner.write_text("@echo off\n", encoding="utf-8")

    exit_code = main(["materials-studio-capability", "--runner", str(runner)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "status: available_unverified" in output
    assert "arbitrary_script_supported: false" in output


def test_protocol_resolution_and_job_plan_cli_are_no_write(tmp_path, capsys) -> None:
    fixture = Path(__file__).parent / "fixtures" / "synthetic" / "workflow"
    common = [
        str(fixture / "POSCAR"),
        "--protocol",
        str(fixture / "protocol.json"),
        "--potcar-metadata",
        str(fixture / "potcar-metadata.json"),
        "--format",
        "json",
    ]

    resolution_exit = main(["resolve-protocol", *common])
    resolution = json.loads(capsys.readouterr().out)
    plan_exit = main(
        [
            "plan-vasp-job",
            *common[:-2],
            "--execution-profile",
            str(fixture / "execution-profile.json"),
            "--cluster-policy",
            str(fixture / "cluster-policy.json"),
            "--destination-root",
            str(tmp_path),
            "--format",
            "json",
        ]
    )
    plan = json.loads(capsys.readouterr().out)

    assert resolution_exit == 0
    assert resolution["status"] == "review_pending"
    assert resolution["resolved"]["review"]["state"] == "pending"
    assert plan_exit == 0
    assert plan["status"] == "review_pending"
    assert plan["writes_performed"] is False
    assert plan["slurm"]["submitted"] is False
    assert (
        plan["resolved_protocol"]["energy_family_id"] == resolution["resolved"]["energy_family_id"]
    )
    assert not Path(plan["job_directory"]).exists()


def test_protocol_resolution_text_renderer(capsys) -> None:
    fixture = Path(__file__).parent / "fixtures" / "synthetic" / "workflow"

    exit_code = main(
        [
            "resolve-protocol",
            str(fixture / "POSCAR"),
            "--protocol",
            str(fixture / "protocol.json"),
            "--potcar-metadata",
            str(fixture / "potcar-metadata.json"),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "status: review_pending" in output
    assert "manual_review_state: pending" in output
    assert "energy_family_id: sha256:" in output
