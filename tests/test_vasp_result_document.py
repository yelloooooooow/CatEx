from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from catex.vasp import build_vasp_result_document
from catex_web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def _result_directory(tmp_path: Path) -> Path:
    root = tmp_path / "vasp-results"
    root.mkdir()
    for name in ("OUTCAR", "OSZICAR"):
        shutil.copyfile(FIXTURES / "vasp_output" / "normal" / name, root / name)
    poscar = (FIXTURES / "workflow" / "POSCAR").read_text(encoding="utf-8")
    (root / "CONTCAR").write_text(poscar, encoding="utf-8")
    (root / "vasprun.xml").write_text(
        """
<modeling>
  <calculation>
    <energy>
      <i name="e_fr_energy">-10.250</i>
      <i name="e_0_energy">-10.245</i>
    </energy>
  </calculation>
  <i name="efermi">2.125</i>
</modeling>
""".strip(),
        encoding="utf-8",
    )
    (root / "XDATCAR").write_text(
        poscar
        + "\nDirect configuration=     1\n"
        + "0 0 0\n0.5 0.5 0.5\n"
        + "Direct configuration=     2\n"
        + "0 0 0\n0.51 0.5 0.5\n",
        encoding="utf-8",
    )
    (root / "CHGCAR").write_text(poscar + "\n2 2 3\n" + "0.0 " * 12, encoding="utf-8")
    return root


def test_vasp_result_document_unifies_outputs_structures_and_large_data_metadata(
    tmp_path: Path,
) -> None:
    document = build_vasp_result_document(_result_directory(tmp_path))

    assert document["energy"]["sigma_zero_energy_eV"] == -10.245
    assert document["vasprun"]["fermi_energy_eV"] == 2.125
    assert document["final_structure"]["record"]["reduced_formula"] == "NaCl"
    assert document["trajectory"]["frame_count"] == 2
    assert document["volumetric"][0]["grid_dimensions"] == [2, 2, 3]
    assert document["raw_volumetric_values_included"] is False


def test_web_vasp_result_document_upload_is_ephemeral(tmp_path: Path) -> None:
    result_directory = _result_directory(tmp_path)
    with TestClient(create_app(data_root=tmp_path / "api")) as client:
        response = client.post(
            "/api/v1/vasp-results/parse",
            files=[
                (
                    "files",
                    ("CONTCAR", (result_directory / "CONTCAR").read_bytes(), "text/plain"),
                ),
                (
                    "files",
                    (
                        "vasprun.xml",
                        (result_directory / "vasprun.xml").read_bytes(),
                        "application/xml",
                    ),
                ),
                (
                    "files",
                    ("CHGCAR", (result_directory / "CHGCAR").read_bytes(), "text/plain"),
                ),
            ],
        )

    assert response.status_code == 200
    assert response.json()["upload"]["retained"] is False
    assert response.json()["final_structure"]["record"]["num_sites"] == 2
    assert response.json()["volumetric"][0]["grid_point_count"] == 12


def test_vasprun_dtd_is_reported_without_parsing_entities(tmp_path: Path) -> None:
    (tmp_path / "vasprun.xml").write_text(
        '<!DOCTYPE model [<!ENTITY unsafe "x">]><model>&unsafe;</model>',
        encoding="utf-8",
    )

    result = build_vasp_result_document(tmp_path)

    assert result["vasprun"]["ionic_step_count"] == 0
    assert result["diagnostics"][0]["code"] == "VASPRUN_XML_PARSE_FAILED"
