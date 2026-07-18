from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from catex_web.app import create_app


def test_web_capabilities_and_default_template(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        capabilities = client.get("/api/v1/capabilities")
        template = client.get("/api/v1/workflows/templates/default")

    assert capabilities.status_code == 200
    assert capabilities.json()["hpc_enabled"] is True
    assert capabilities.json()["ssh_enabled"] is True
    assert capabilities.json()["hpc_default_active"] is False
    assert capabilities.json()["credentials_persisted"] is False
    assert capabilities.json()["project_persistence_enabled"] is True
    assert template.status_code == 200
    assert template.json()["validation"]["valid"] is True


def test_web_structure_upload(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "synthetic" / "workflow" / "POSCAR"
    with TestClient(create_app(data_root=tmp_path)) as client:
        response = client.post(
            "/api/v1/structures/inspect",
            files={"file": ("POSCAR", fixture.read_bytes(), "text/plain")},
        )

    assert response.status_code == 200
    assert response.json()["inspection"]["record"]["num_sites"] == 2


def test_web_synthetic_vasp_metrics_match_public_contract(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        response = client.get("/api/v1/demo/vasp-output")

    assert response.status_code == 200
    payload = response.json()
    assert payload["energy"]["free_energy_eV"] == -10.25
    assert payload["forces"]["maximum_norm_eV_per_angstrom"] == 0.03605551275463989
    assert payload["demo"] == {
        "synthetic": True,
        "scientific_result_eligible": False,
        "commands_executed": False,
        "hpc_contacted": False,
    }


def test_web_thermochemistry_and_oer_analysis_endpoints(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        templates = client.get("/api/v1/reaction-analysis/templates")
        thermochemistry = client.post(
            "/api/v1/thermochemistry/harmonic",
            json={
                "modes": [
                    {"wavenumber_cm1": 333.56, "energy_mev": 41.3567, "imaginary": False},
                    {"wavenumber_cm1": 20.0, "energy_mev": 2.48, "imaginary": False},
                ],
                "temperature_kelvin": 298.15,
                "low_frequency_cutoff_cm1": 50.0,
            },
        )
        analysis = client.post(
            "/api/v1/reaction-analysis",
            json={
                "template_id": "oer-aem-che",
                "states": {
                    "slab": {"energy_eV": -100.0, "energy_family_id": "pbe"},
                    "oh_star": {"energy_eV": -106.0, "energy_family_id": "pbe"},
                    "o_star": {"energy_eV": -104.0, "energy_family_id": "pbe"},
                    "ooh_star": {"energy_eV": -107.0, "energy_family_id": "pbe"},
                },
                "h2_free_energy_eV": -6.8,
                "h2o_free_energy_eV": -14.2,
                "temperature_kelvin": 298.15,
                "potential_volts": 1.23,
                "pH": 0.0,
                "reference_electrode": "RHE",
            },
        )

    assert templates.status_code == 200
    assert {item["template_id"] for item in templates.json()["templates"]} == {
        "her-che",
        "oer-aem-che",
    }
    assert thermochemistry.status_code == 200
    assert thermochemistry.json()["included_mode_count"] == 1
    assert analysis.status_code == 200
    assert len(analysis.json()["states"]) == 5
    assert analysis.json()["energy_family_id"] == "pbe"


def test_web_project_lifecycle(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "synthetic" / "workflow" / "POSCAR"
    with TestClient(create_app(data_root=tmp_path)) as client:
        created = client.post(
            "/api/v1/projects",
            json={
                "title": "NaCl full flow",
                "purpose": "training",
                "description": "Synthetic acceptance",
            },
        )
        project_id = created.json()["project_id"]
        uploaded = client.post(
            f"/api/v1/projects/{project_id}/structures",
            files={"file": ("POSCAR", fixture.read_bytes(), "text/plain")},
        )
        source = client.get(
            f"/api/v1/projects/{project_id}/artifacts/{uploaded.json()['artifact_id']}/source"
        )
        template = client.get("/api/v1/workflows/templates/default").json()["template"]
        saved = client.post(
            f"/api/v1/projects/{project_id}/workflow",
            json={"nodes": template["nodes"], "edges": template["edges"]},
        )
        listed = client.get("/api/v1/projects").json()["projects"]
        exported = client.get(f"/api/v1/projects/{project_id}/export")

    assert created.status_code == 201
    assert uploaded.status_code == 201
    assert uploaded.json()["retained"] is True
    assert source.status_code == 200
    assert source.json()["content"].encode("utf-8") == fixture.read_bytes()
    assert source.json()["read_only"] is True
    assert saved.status_code == 200
    assert listed[0]["project_id"] == project_id
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"


def test_web_calculation_dry_run_review_and_materialization(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "synthetic" / "workflow" / "POSCAR"
    with TestClient(create_app(data_root=tmp_path)) as client:
        project_id = client.post(
            "/api/v1/projects", json={"title": "Dry run", "purpose": "training"}
        ).json()["project_id"]
        artifact_id = client.post(
            f"/api/v1/projects/{project_id}/structures",
            files={"file": ("POSCAR", fixture.read_bytes(), "text/plain")},
        ).json()["artifact_id"]
        structure_review = client.post(
            f"/api/v1/projects/{project_id}/structure-reviews",
            json={
                "artifact_id": artifact_id,
                "approved": True,
                "reviewer": "api-structure-reviewer",
                "note": "Structure checked",
            },
        )
        config = client.get("/api/v1/calculation-config/default").json()
        saved = client.post(f"/api/v1/projects/{project_id}/calculation-config", json=config)
        pending = client.post(
            f"/api/v1/projects/{project_id}/calculation-plan",
            json={"artifact_id": artifact_id},
        )
        reviewed = client.post(
            f"/api/v1/projects/{project_id}/protocol-review",
            json={
                "artifact_id": artifact_id,
                "reviewer": "api-reviewer",
                "note": "checked",
            },
        )
        approved = client.post(
            f"/api/v1/projects/{project_id}/calculation-plan",
            json={"artifact_id": artifact_id},
        )
        materialized = client.post(
            f"/api/v1/projects/{project_id}/materializations",
            json={
                "artifact_id": artifact_id,
                "confirm_plan_sha256": approved.json()["plan"]["plan_sha256"],
                "approved_write": True,
            },
        )

    assert saved.status_code == 200
    assert structure_review.status_code == 201
    assert pending.json()["plan"]["ready_for_materialization"] is False
    assert reviewed.json()["approved"] is True
    assert approved.json()["plan"]["ready_for_materialization"] is True
    assert materialized.status_code == 201
    assert materialized.json()["potcar_materialized"] is False
