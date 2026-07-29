from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from catex.mlip import (
    ChgnetPreRelaxationConfig,
    ChgnetPreRelaxationError,
    ChgnetPreRelaxationResult,
)
from catex_web.app import create_app


def _fake_chgnet_runner(
    poscar_text: str,
    config: ChgnetPreRelaxationConfig,
) -> ChgnetPreRelaxationResult:
    lines = poscar_text.splitlines()
    lines[0] = "CatEx fake CHGNet pre-relaxed"
    output = "\n".join(lines) + "\n"
    return ChgnetPreRelaxationResult(
        poscar_text=output,
        summary={
            "schema_version": "catex.chgnet-pre-relaxation-result.v1",
            "status": "converged",
            "converged": True,
            "n_steps": 12,
            "final_fmax_eV_per_angstrom": 0.042,
            "target_fmax_eV_per_angstrom": config.fmax_eV_per_angstrom,
            "initial_energy_eV": -10.0,
            "final_energy_eV": -10.5,
            "energy_change_eV": -0.5,
            "maximum_displacement_angstrom": 0.12,
            "rms_displacement_angstrom": 0.08,
            "fixed_atom_count": 0,
            "mobile_atom_count": 2,
            "fixed_indices_1based": [],
            "model_name": config.model_name,
            "model_version": config.model_name,
            "optimizer": config.optimizer,
            "device": "cpu",
            "relax_cell": config.relax_cell,
            "elapsed_seconds": 0.1,
            "scientific_role": "geometry_pre_relaxation_only",
        },
        warnings=("This is pre-relaxation only.",),
    )


def test_chgnet_config_rejects_unbounded_values() -> None:
    with pytest.raises(ChgnetPreRelaxationError, match="fmax"):
        ChgnetPreRelaxationConfig(fmax_eV_per_angstrom=0.0)
    with pytest.raises(ChgnetPreRelaxationError, match="max_steps"):
        ChgnetPreRelaxationConfig(max_steps=5001)
    with pytest.raises(ChgnetPreRelaxationError, match="device"):
        ChgnetPreRelaxationConfig(device="remote")


def test_project_chgnet_relaxation_creates_a_traceable_structure_artifact(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "synthetic" / "workflow" / "POSCAR"
    with TestClient(create_app(data_root=tmp_path, chgnet_runner=_fake_chgnet_runner)) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "CHGNet test", "purpose": "training"},
        ).json()["project_id"]
        source_artifact = client.post(
            f"/api/v1/projects/{project_id}/structures",
            files={"file": ("POSCAR", fixture.read_bytes(), "text/plain")},
        ).json()
        response = client.post(
            f"/api/v1/projects/{project_id}/chgnet-pre-relaxations",
            json={
                "artifact_id": source_artifact["artifact_id"],
                "model_name": "0.3.0",
                "optimizer": "FIRE",
                "fmax_eV_per_angstrom": 0.05,
                "max_steps": 500,
                "relax_cell": False,
                "device": "cpu",
            },
        )
        exported = client.get(f"/api/v1/projects/{project_id}/export")

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_artifact_id"] == source_artifact["artifact_id"]
    assert payload["output_artifact"]["artifact_id"] != source_artifact["artifact_id"]
    assert payload["output_artifact"]["original_filename"] == "POSCAR_CHGNET.vasp"
    assert payload["poscar_text"].startswith("CatEx fake CHGNet pre-relaxed")
    assert payload["summary"]["converged"] is True
    assert payload["summary"]["final_fmax_eV_per_angstrom"] == 0.042
    assert payload["hpc_contacted"] is False
    assert payload["vasp_executed"] is False
    with zipfile.ZipFile(io.BytesIO(exported.content)) as bundle:
        names = bundle.namelist()
    assert any(name.startswith("pre-relaxations/chgnet-") for name in names)


def test_chgnet_endpoint_rejects_unknown_model_before_execution(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path, chgnet_runner=_fake_chgnet_runner)) as client:
        response = client.post(
            "/api/v1/projects/project-00000000/chgnet-pre-relaxations",
            json={"artifact_id": "structure-" + "a" * 20, "model_name": "unknown"},
        )

    assert response.status_code == 422
