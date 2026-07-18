from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from catex_web.app import create_app


def test_paper4_reference_case_stays_blocked_and_can_seed_a_project(tmp_path: Path) -> None:
    client = TestClient(create_app(data_root=tmp_path / "data"))

    summary = client.get("/api/v1/reference-cases/paper4")
    created = client.post("/api/v1/projects/from-reference/paper4")

    assert summary.status_code == 200
    payload = summary.json()
    assert payload["readiness"]["status"] == "blocked"
    assert payload["readiness"]["ready_for_production_planning"] is False
    assert len(payload["readiness"]["blocking_requirement_ids"]) == 10
    assert payload["che_protocol_draft"]["temperature_kelvin"] is None
    assert payload["execution_authorized"] is False
    assert created.status_code == 201
    assert created.json()["template_id"] == "paper4-co2rr-dac-reference"
    binding = tmp_path / "data" / "projects" / created.json()["project_id"] / "reference-case.json"
    assert binding.is_file()
