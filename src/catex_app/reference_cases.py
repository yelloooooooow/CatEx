"""Read-only reference-case adapters kept outside the generic CatEx core."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from catex.readiness import (
    RequirementCategory,
    RequirementStatus,
    assess_scientific_case_readiness,
    create_scientific_case_requirement,
)
from catex_app.projects import ProjectStore


class ReferenceCaseService:
    """Expose case fixtures without treating draft evidence as production approval."""

    def __init__(self, projects: ProjectStore, repository_root: Path):
        self.projects = projects
        self.root = repository_root / "projects" / "paper4_co2rr_dac_reproduction"

    def _load(self, name: str) -> dict[str, Any]:
        path = self.root / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("reference case document is invalid")
        return payload

    def paper4_summary(self) -> dict[str, Any]:
        payload = self._load("production-readiness.json")
        requirements = tuple(
            create_scientific_case_requirement(
                requirement_id=item["requirement_id"],
                category=RequirementCategory(item["category"]),
                description=item["description"],
                required=item["required"],
                status=RequirementStatus(item["status"]),
                evidence_sha256s=tuple(item["evidence_sha256s"]),
                note=item["note"],
                assessed_by=item["assessed_by"],
                assessed_at_utc=item["assessed_at_utc"],
            )
            for item in payload["requirements"]
        )
        report = assess_scientific_case_readiness(payload["case_id"], requirements)
        return {
            "schema_version": "catex.web-reference-case.v1",
            "case_id": payload["case_id"],
            "title": "M1M2-N-C CO2RR · Paper 4 reference case",
            "role": "reference_implementation_and_scientific_acceptance_case",
            "readiness": report.to_dict(),
            "reaction_network_draft": self._load("reaction-network-draft.json"),
            "che_protocol_draft": self._load("che-protocol-draft.json"),
            "thermochemistry_requirements": self._load("thermochemistry-requirements.json"),
            "execution_authorized": False,
        }

    def create_paper4_project(self) -> dict[str, Any]:
        summary = self.paper4_summary()
        project = self.projects.create_project(
            title="Paper 4 · M1M2-N-C CO2RR 验收",
            purpose="literature_reproduction",
            description=(
                "CatEx 首个 reference implementation; 保留生产就绪阻断项, "
                "不自动授权计算或填补论文缺失参数。"
            ),
            template_id="paper4-co2rr-dac-reference",
        )
        directory = self.projects.project_directory(project["project_id"])
        self.projects._write_json(
            directory / "reference-case.json",
            {
                "schema_version": "catex.web-reference-case-binding.v1",
                "case_id": summary["case_id"],
                "readiness_report_sha256": summary["readiness"]["report_sha256"],
                "execution_authorized": False,
            },
            exclusive=True,
        )
        self.projects.append_event(
            project["project_id"],
            "reference_case.bound",
            {
                "case_id": summary["case_id"],
                "readiness_report_sha256": summary["readiness"]["report_sha256"],
            },
        )
        return self.projects.get_project(project["project_id"])


__all__ = ["ReferenceCaseService"]
