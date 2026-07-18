from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pymatgen.io.vasp.inputs import Poscar

from catex_app.remote_potcar_builder import build
from catex_app.services import constrain_poscar, convert_cif_upload_to_poscar

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def test_cif_conversion_returns_inspectable_poscar_without_writing() -> None:
    source = FIXTURES / "materials_studio" / "nacl_input.cif"

    result = convert_cif_upload_to_poscar(source.name, source.read_bytes())

    assert result["output_filename"] == "POSCAR"
    assert result["writes_performed"] is False
    assert result["inspection"]["inspection"]["record"]["reduced_formula"] == "NaCl"
    assert "Na Cl" in result["poscar_text"]


def test_adsorbate_indices_fix_every_other_atom() -> None:
    source = (FIXTURES / "workflow" / "POSCAR").read_bytes()

    result = constrain_poscar(
        source,
        strategy="adsorbate_indices",
        mobile_indices_1based=(2,),
    )

    parsed = Poscar.from_str(result["poscar_text"])
    assert result["fixed_indices_1based"] == [1]
    assert result["mobile_indices_1based"] == [2]
    assert parsed.selective_dynamics is not None
    assert [list(item) for item in parsed.selective_dynamics] == [
        [False, False, False],
        [True, True, True],
    ]


def test_bottom_layer_strategy_leaves_an_upper_layer_mobile() -> None:
    source = (FIXTURES / "workflow" / "POSCAR").read_bytes()

    result = constrain_poscar(
        source,
        strategy="bottom_layers",
        bottom_layer_count=1,
        layer_tolerance_angstrom=0.1,
    )

    assert result["fixed_count"] == 1
    assert result["mobile_count"] == 1


def test_bundled_remote_potcar_builder_uses_exclusive_hash_checked_inputs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "potpaw_PBE.54"
    dataset = root / "Ni"
    dataset.mkdir(parents=True)
    content = b"TITEL = PAW_PBE Ni\nLEXCH = PE\n"
    (dataset / "POTCAR").write_bytes(content)
    metadata = tmp_path / "catex-potcar-metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "datasets": [
                    {
                        "potential_label": "Ni",
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "POTCAR"

    report = build(potcar_root=root, metadata_path=metadata, output_path=output)

    assert output.read_bytes() == content
    assert report["datasets"] == ["Ni"]
    assert report["overwrite_performed"] is False
