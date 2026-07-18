from __future__ import annotations

import json
from pathlib import Path

from catex.structures import inspect_path
from catex.workflow.protocol import resolve_protocol


def test_paper4_nizn_fixture_is_readable_without_errors() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (
        root
        / "projects"
        / "paper4_co2rr_dac_reproduction"
        / "structures"
        / "environment_smoke_test"
        / "NiZn_NC"
        / "POSCAR"
    )

    report = inspect_path(source)

    assert report.record is not None
    assert report.record.num_sites == 70
    assert report.record.reduced_formula == "ZnNi(C31N3)2"
    assert not report.has_errors


def test_paper4_nonproduction_environment_smoke_protocol_resolves_with_synthetic_metadata(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    project = root / "projects" / "paper4_co2rr_dac_reproduction"
    protocol = project / "hpc" / "environment-smoke-protocol.json"
    poscar = project / "structures" / "environment_smoke_test" / "NiZn_NC" / "POSCAR"
    datasets = []
    for index, (element, zval, enmax) in enumerate(
        (("Ni", 10.0, 270.0), ("Zn", 12.0, 280.0), ("C", 4.0, 400.0), ("N", 5.0, 400.0))
    ):
        datasets.append(
            {
                "element": element,
                "potential_label": element,
                "titel": f"PAW_PBE {element} SYNTHETIC-NOT-A-REAL-POTENTIAL",
                "lexch": "PE",
                "zval": zval,
                "enmax_eV": enmax,
                "sha256": f"{index + 1:064x}",
            }
        )
    metadata = tmp_path / "synthetic-potcar-metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "schema_version": "catex.potcar-metadata.v1",
                "potential_family": "PAW_PBE_54_SYNTHETIC",
                "datasets": datasets,
            }
        ),
        encoding="utf-8",
    )

    report = resolve_protocol(protocol, poscar_path=poscar, potcar_metadata_path=metadata)

    assert not report.has_errors
    assert report.resolved is not None
    assert report.resolved.protocol_id == "paper4-nizn-environment-smoke-v1-nonproduction"
    assert report.resolved.kpoints.subdivisions == (1, 1, 1)
    assert report.resolved.incar_values["LSOL"] == "T"
    assert report.resolved.incar_values["NELM"] == "4"
    assert report.resolved.incar_values["LWAVE"] == "F"
    assert report.resolved.incar_values["LCHARG"] == "F"
