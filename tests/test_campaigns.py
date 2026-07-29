from __future__ import annotations

from pathlib import Path

from catex_app.campaigns import CampaignService
from catex_app.projects import ProjectStore


def test_campaign_tracks_candidates_and_append_only_decisions(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create_project(title="Screening", purpose="original_research")
    service = CampaignService(store)

    campaign = service.create(
        project["project_id"],
        title="DAC screening",
        objective="Compare a bounded design space",
    )
    candidate = service.add_candidate(
        project["project_id"],
        campaign["campaign_id"],
        label="Ni-Zn",
        variables={"metal_1": "Ni", "metal_2": "Zn"},
    )
    decision = service.record_decision(
        project["project_id"],
        campaign["campaign_id"],
        candidate_id=candidate["candidate_id"],
        action="advance",
        rationale="Synthetic acceptance evidence",
        evidence={"source": "test"},
    )

    detail = service.get(project["project_id"], campaign["campaign_id"])
    assert detail["candidate_count"] == 1
    assert detail["decision_count"] == 1
    assert service.list_candidates(project["project_id"], campaign["campaign_id"]) == [candidate]
    assert service.list_decisions(project["project_id"], campaign["campaign_id"]) == [decision]
