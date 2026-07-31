from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from pymatgen.core import Lattice, Structure
from pymatgen.io.vasp import Poscar

from catex_web.app import create_app


def _nimo_poscar() -> bytes:
    structure = Structure(
        Lattice.cubic(3.6),
        ["Ni", "Mo"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    return Poscar(structure).get_str().encode("utf-8")


def test_web_experimental_modeling_review_and_materialization(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        capabilities = client.get("/api/v1/experimental-modeling/capabilities")
        project_id = client.post(
            "/api/v1/projects",
            json={
                "title": "NiMo interpretation",
                "purpose": "experimental_interpretation",
            },
        ).json()["project_id"]
        structure = client.post(
            f"/api/v1/projects/{project_id}/structures",
            files={"file": ("POSCAR", _nimo_poscar(), "text/plain")},
        )
        evidence = client.post(
            f"/api/v1/projects/{project_id}/experimental-modeling/evidence",
            files={"file": ("composition.csv", b"element,at_fraction\nNi,0.6\nMo,0.4\n")},
        )
        evidence_id = evidence.json()["evidence_artifact_id"]
        saved = client.put(
            f"/api/v1/projects/{project_id}/experimental-modeling/spec",
            json={
                "schema_version": "catex.experiment-spec.v1",
                "sample_id": "electrode-1",
                "target_state": "activated",
                "material_pack": "alloy-electrocatalyst",
                "allowed_elements": ["Ni", "Mo"],
                "excluded_elements": [],
                "composition_constraints": [
                    {
                        "element": "Ni",
                        "minimum_atomic_fraction": 0.5,
                        "maximum_atomic_fraction": 0.7,
                        "scope": "bulk",
                        "evidence_ids": ["composition"],
                    },
                    {
                        "element": "Mo",
                        "minimum_atomic_fraction": 0.3,
                        "maximum_atomic_fraction": 0.5,
                        "scope": "bulk",
                        "evidence_ids": ["composition"],
                    },
                ],
                "evidence": [
                    {
                        "evidence_id": "composition",
                        "kind": "icp",
                        "sample_state": "activated",
                        "role": "hard",
                        "metadata": {"basis": "atomic_fraction"},
                        "evidence_artifact_id": evidence_id,
                        "note": "Synthetic bounded composition evidence",
                    }
                ],
            },
        )
        inferred = client.post(
            f"/api/v1/projects/{project_id}/experimental-modeling/runs",
            json={
                "planner_kind": "rule",
                "catalog_ids": [],
                "maximum_representatives": 2,
                "xrd_settings": {
                    "wavelength": "CuKa",
                    "shift_values_degrees": [0],
                    "fwhm_values_degrees": [0.2],
                    "maximum_phases": 1,
                },
            },
        )
        run = inferred.json()
        stored_run_path = (
            tmp_path
            / "projects"
            / project_id
            / "experimental-modeling"
            / "runs"
            / run["run_id"]
            / "run.json"
        )
        immutable_run_content = stored_run_path.read_bytes()
        candidate_id = run["report"]["representative_candidate_ids"][0]
        reviewed = client.post(
            (f"/api/v1/projects/{project_id}/experimental-modeling/runs/{run['run_id']}/reviews"),
            json={
                "approved_candidate_ids": [candidate_id],
                "reviewer": "test-reviewer",
                "note": "Representative for the bounded synthetic test.\nSecond review line.",
            },
        )
        materialized = client.post(
            (
                f"/api/v1/projects/{project_id}/experimental-modeling/"
                f"runs/{run['run_id']}/materializations"
            ),
            json={
                "candidate_ids": [candidate_id],
                "confirm_report_sha256": run["report"]["identity_sha256"],
                "approved_write": True,
            },
        )
        runs = client.get(f"/api/v1/projects/{project_id}/experimental-modeling/runs")
        exported = client.get(f"/api/v1/projects/{project_id}/export")

    assert capabilities.status_code == 200
    assert capabilities.json()["credentials_persisted"] is False
    assert (
        capabilities.json()["providers"]["materials_project"]["api_key_environment_variable"]
        == "MP_API_KEY"
    )
    assert "api_key_value" not in str(capabilities.json()).lower()
    assert structure.status_code == 201
    assert evidence.status_code == 201
    assert saved.status_code == 200
    assert inferred.status_code == 201
    assert run["report"]["status"] == "insufficient_evidence"
    assert run["report"]["claim_ceiling"] == "candidate_only"
    assert reviewed.status_code == 201
    assert reviewed.json()["unique_structure_claimed"] is False
    assert materialized.status_code == 201
    assert materialized.json()["approved_write"] is True
    assert len(materialized.json()["artifacts"][0]["source_candidate_cif_sha256"]) == 64
    assert runs.json()["runs"][0]["materialized"] is True
    assert stored_run_path.read_bytes() == immutable_run_content
    with zipfile.ZipFile(io.BytesIO(exported.content)) as bundle:
        names = bundle.namelist()
    assert any(name.startswith("experimental-modeling/specs/spec-") for name in names)
    assert any(name.endswith("/run.json") for name in names)
    assert all("secret" not in name.lower() and ".env" not in name.lower() for name in names)


def test_web_experimental_modeling_rejects_unreviewed_materialization(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "Gate", "purpose": "training"},
        ).json()["project_id"]
        client.post(
            f"/api/v1/projects/{project_id}/structures",
            files={"file": ("POSCAR", _nimo_poscar(), "text/plain")},
        )
        client.put(
            f"/api/v1/projects/{project_id}/experimental-modeling/spec",
            json={
                "sample_id": "gate-test",
                "target_state": "unspecified",
                "allowed_elements": ["Ni", "Mo"],
            },
        )
        run = client.post(
            f"/api/v1/projects/{project_id}/experimental-modeling/runs",
            json={"planner_kind": "rule"},
        ).json()
        candidate_id = run["report"]["representative_candidate_ids"][0]
        rejected = client.post(
            (
                f"/api/v1/projects/{project_id}/experimental-modeling/"
                f"runs/{run['run_id']}/materializations"
            ),
            json={
                "candidate_ids": [candidate_id],
                "confirm_report_sha256": run["report"]["identity_sha256"],
                "approved_write": True,
            },
        )
        client.post(
            f"/api/v1/projects/{project_id}/experimental-modeling/runs/{run['run_id']}/reviews",
            json={
                "approved_candidate_ids": [candidate_id],
                "reviewer": "tamper-reviewer",
                "note": "Approve the original immutable candidate.",
            },
        )
        candidate = next(item for item in run["candidates"] if item["candidate_id"] == candidate_id)
        candidate_path = (
            tmp_path
            / "projects"
            / project_id
            / "experimental-modeling"
            / "runs"
            / run["run_id"]
            / candidate["relative_path"]
        )
        candidate_path.write_bytes(candidate_path.read_bytes() + b"\n# tampered\n")
        tampered = client.post(
            (
                f"/api/v1/projects/{project_id}/experimental-modeling/"
                f"runs/{run['run_id']}/materializations"
            ),
            json={
                "candidate_ids": [candidate_id],
                "confirm_report_sha256": run["report"]["identity_sha256"],
                "approved_write": True,
            },
        )

    assert rejected.status_code == 400
    assert "explicitly approved" in rejected.json()["detail"]
    assert tampered.status_code == 400
    assert "immutable run" in tampered.json()["detail"]
