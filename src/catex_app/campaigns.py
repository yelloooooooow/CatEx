"""Append-oriented campaign records for long-running catalyst research."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from catex_app.projects import ProjectStore

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CAMPAIGN_STATUSES = {"active", "paused", "completed", "archived"}
_CANDIDATE_STATUSES = {
    "proposed",
    "prepared",
    "running",
    "succeeded",
    "failed",
    "excluded",
}


class CampaignError(ValueError):
    """Raised when campaign state violates its append-oriented contract."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CampaignError(f"could not read campaign record: {path.name}") from error
    if not isinstance(payload, dict):
        raise CampaignError("campaign record root must be an object")
    return payload


def _write_json(path: Path, payload: dict[str, Any], *, exclusive: bool = True) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    if len(data) > 4 * 1024 * 1024:
        raise CampaignError("campaign record exceeds the local safety limit")
    with path.open("xb" if exclusive else "wb") as stream:
        stream.write(data)


def _require_id(value: str, field: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise CampaignError(f"{field} has an invalid format")
    return value


class CampaignService:
    """Persist campaigns independently from a particular reaction or paper."""

    def __init__(self, store: ProjectStore):
        self.store = store

    def _root(self, project_id: str) -> Path:
        root = self.store.project_directory(project_id) / "campaigns"
        root.mkdir(exist_ok=True)
        return root

    def create(
        self,
        project_id: str,
        *,
        title: str,
        objective: str = "",
        workflow_revision_id: str | None = None,
    ) -> dict[str, Any]:
        title = title.strip()
        if not title or len(title) > 120:
            raise CampaignError("campaign title must contain 1 to 120 characters")
        if len(objective) > 2000:
            raise CampaignError("campaign objective must not exceed 2000 characters")
        campaign_id = f"campaign-{uuid4().hex[:12]}"
        root = self._root(project_id) / campaign_id
        root.mkdir(exist_ok=False)
        (root / "candidates").mkdir(exist_ok=False)
        (root / "decisions").mkdir(exist_ok=False)
        payload = {
            "schema_version": "catex.campaign.v1",
            "campaign_id": campaign_id,
            "project_id": project_id,
            "title": title,
            "objective": objective.strip(),
            "workflow_revision_id": workflow_revision_id,
            "status": "active",
            "created_at_utc": _utc_now(),
            "candidate_count": 0,
            "decision_count": 0,
        }
        _write_json(root / "campaign.json", payload)
        self.store.append_event(
            project_id,
            "campaign.created",
            {"campaign_id": campaign_id},
        )
        return payload

    def list(self, project_id: str) -> list[dict[str, Any]]:
        records = [
            _read_json(path)
            for path in self._root(project_id).glob("campaign-*/campaign.json")
            if path.is_file()
        ]
        return sorted(
            records,
            key=lambda item: str(item.get("created_at_utc", "")),
            reverse=True,
        )

    def _directory(self, project_id: str, campaign_id: str) -> Path:
        _require_id(campaign_id, "campaign_id")
        root = self._root(project_id)
        path = root / campaign_id
        if path.parent != root or not path.is_dir():
            raise CampaignError("campaign does not exist")
        return path

    def get(self, project_id: str, campaign_id: str) -> dict[str, Any]:
        return _read_json(self._directory(project_id, campaign_id) / "campaign.json")

    def set_status(
        self,
        project_id: str,
        campaign_id: str,
        *,
        status: str,
    ) -> dict[str, Any]:
        if status not in _CAMPAIGN_STATUSES:
            raise CampaignError("campaign status is not supported")
        path = self._directory(project_id, campaign_id) / "campaign.json"
        payload = _read_json(path)
        payload["status"] = status
        payload["updated_at_utc"] = _utc_now()
        _write_json(path, payload, exclusive=False)
        self.store.append_event(
            project_id,
            "campaign.status_changed",
            {"campaign_id": campaign_id, "status": status},
        )
        return payload

    def add_candidate(
        self,
        project_id: str,
        campaign_id: str,
        *,
        label: str,
        structure_artifact_id: str | None = None,
        variables: dict[str, Any] | None = None,
        status: str = "proposed",
    ) -> dict[str, Any]:
        if status not in _CANDIDATE_STATUSES:
            raise CampaignError("candidate status is not supported")
        label = label.strip()
        if not label or len(label) > 120:
            raise CampaignError("candidate label must contain 1 to 120 characters")
        root = self._directory(project_id, campaign_id)
        candidate_id = f"candidate-{uuid4().hex[:12]}"
        payload = {
            "schema_version": "catex.campaign-candidate.v1",
            "candidate_id": candidate_id,
            "campaign_id": campaign_id,
            "label": label,
            "structure_artifact_id": structure_artifact_id,
            "variables": variables or {},
            "status": status,
            "created_at_utc": _utc_now(),
        }
        _write_json(root / "candidates" / f"{candidate_id}.json", payload)
        campaign_path = root / "campaign.json"
        campaign = _read_json(campaign_path)
        campaign["candidate_count"] = int(campaign.get("candidate_count", 0)) + 1
        campaign["updated_at_utc"] = _utc_now()
        _write_json(campaign_path, campaign, exclusive=False)
        self.store.append_event(
            project_id,
            "campaign.candidate_added",
            {"campaign_id": campaign_id, "candidate_id": candidate_id},
        )
        return payload

    def list_candidates(self, project_id: str, campaign_id: str) -> list[dict[str, Any]]:
        root = self._directory(project_id, campaign_id) / "candidates"
        records = [_read_json(path) for path in root.glob("candidate-*.json")]
        return sorted(records, key=lambda item: str(item.get("created_at_utc", "")))

    def record_decision(
        self,
        project_id: str,
        campaign_id: str,
        *,
        action: str,
        rationale: str,
        candidate_id: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        root = self._directory(project_id, campaign_id)
        action = action.strip()
        rationale = rationale.strip()
        if not action or len(action) > 80:
            raise CampaignError("decision action must contain 1 to 80 characters")
        if not rationale or len(rationale) > 2000:
            raise CampaignError("decision rationale must contain 1 to 2000 characters")
        if candidate_id is not None:
            _require_id(candidate_id, "candidate_id")
            if not (root / "candidates" / f"{candidate_id}.json").is_file():
                raise CampaignError("decision candidate does not exist")
        decision_id = f"decision-{uuid4().hex[:12]}"
        payload = {
            "schema_version": "catex.campaign-decision.v1",
            "decision_id": decision_id,
            "campaign_id": campaign_id,
            "candidate_id": candidate_id,
            "action": action,
            "rationale": rationale,
            "evidence": evidence or {},
            "recorded_at_utc": _utc_now(),
        }
        _write_json(root / "decisions" / f"{decision_id}.json", payload)
        campaign_path = root / "campaign.json"
        campaign = _read_json(campaign_path)
        campaign["decision_count"] = int(campaign.get("decision_count", 0)) + 1
        campaign["updated_at_utc"] = _utc_now()
        _write_json(campaign_path, campaign, exclusive=False)
        self.store.append_event(
            project_id,
            "campaign.decision_recorded",
            {"campaign_id": campaign_id, "decision_id": decision_id},
        )
        return payload

    def list_decisions(self, project_id: str, campaign_id: str) -> list[dict[str, Any]]:
        root = self._directory(project_id, campaign_id) / "decisions"
        records = [_read_json(path) for path in root.glob("decision-*.json")]
        return sorted(records, key=lambda item: str(item.get("recorded_at_utc", "")))
