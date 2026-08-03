from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from catex_web.app import create_app


def test_web_quick_templates_are_valid_and_publishable(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "Platform", "purpose": "training"},
        ).json()["project_id"]
        catalog = client.get("/api/v1/workflows/templates").json()["templates"]
        selected = next(item for item in catalog if item["template_id"] == "vasp-relax-frequency")
        saved = client.put(
            f"/api/v1/projects/{project_id}/workflow/draft",
            json={"nodes": selected["nodes"], "edges": selected["edges"]},
        )
        published = client.post(
            f"/api/v1/projects/{project_id}/workflow/revisions",
            json={"title": "Frequency workflow"},
        )
        revision_id = published.json()["revision"]["revision_id"]
        run_graph = client.post(
            f"/api/v1/projects/{project_id}/workflow/run-graphs",
            json={"revision_id": revision_id, "label": "First run"},
        )
        execution_plan = client.get(
            f"/api/v1/projects/{project_id}/workflow/run-graphs/"
            f"{run_graph.json()['run_graph_id']}/execution-plan"
        )
        node_id = run_graph.json()["workflow"]["nodes"][0]["node_id"]
        attempt = client.post(
            (
                f"/api/v1/projects/{project_id}/workflow/run-graphs/"
                f"{run_graph.json()['run_graph_id']}/attempts"
            ),
            json={"node_id": node_id, "status": "planned"},
        )

    assert all(item["validation"]["valid"] for item in catalog)
    assert saved.status_code == 200
    assert published.status_code == 201
    assert run_graph.status_code == 201
    assert execution_plan.json()["plan"]["stage_count"] == 3
    assert attempt.status_code == 201


def test_web_campaign_lifecycle(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path)) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "Campaign", "purpose": "original_research"},
        ).json()["project_id"]
        campaign = client.post(
            f"/api/v1/projects/{project_id}/campaigns",
            json={"title": "OER design space", "objective": "Rank candidates"},
        )
        campaign_id = campaign.json()["campaign_id"]
        candidate = client.post(
            f"/api/v1/projects/{project_id}/campaigns/{campaign_id}/candidates",
            json={"label": "candidate-1", "variables": {"dopant": "Ni"}},
        )
        detail = client.get(f"/api/v1/projects/{project_id}/campaigns/{campaign_id}")

    assert campaign.status_code == 201
    assert candidate.status_code == 201
    assert detail.json()["campaign"]["candidate_count"] == 1
