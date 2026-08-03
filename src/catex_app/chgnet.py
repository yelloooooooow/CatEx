"""Project-bound CHGNet pre-relaxation with immutable structure provenance."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from catex.mlip import (
    ChgnetPreRelaxationConfig,
    ChgnetPreRelaxationResult,
    chgnet_capabilities,
    run_chgnet_pre_relaxation,
)
from catex_app.projects import ProjectStore

ChgnetRunner = Callable[
    [str, ChgnetPreRelaxationConfig],
    ChgnetPreRelaxationResult,
]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    with path.open("xb") as stream:
        stream.write(data)


class ChgnetPreRelaxationService:
    """Run optional local CHGNet and bind its output to a project artifact."""

    def __init__(self, projects: ProjectStore, runner: ChgnetRunner | None = None):
        self.projects = projects
        self.runner = runner or run_chgnet_pre_relaxation

    def capabilities(self) -> dict[str, Any]:
        return chgnet_capabilities()

    def relax(
        self,
        project_id: str,
        artifact_id: str,
        config: ChgnetPreRelaxationConfig,
    ) -> dict[str, Any]:
        source_artifact = self.projects.get_artifact(project_id, artifact_id)
        source = self.projects.artifact_source(project_id, artifact_id)
        result = self.runner(str(source["content"]), config)
        output_artifact = self.projects.add_structure(
            project_id,
            "POSCAR_CHGNET.vasp",
            result.poscar_text.encode("utf-8"),
        )
        relaxation_id = f"chgnet-{uuid4().hex[:16]}"
        recorded_at = _utc_now()
        persisted = {
            "schema_version": "catex.web-chgnet-pre-relaxation-record.v1",
            "relaxation_id": relaxation_id,
            "project_id": project_id,
            "recorded_at_utc": recorded_at,
            "source_artifact_id": source_artifact["artifact_id"],
            "source_sha256": source_artifact["sha256"],
            "output_artifact_id": output_artifact["artifact_id"],
            "output_sha256": output_artifact["sha256"],
            "config": config.to_dict(),
            "summary": result.summary,
            "warnings": list(result.warnings),
            "hpc_contacted": False,
            "vasp_executed": False,
        }
        directory = self.projects.project_directory(project_id) / "pre-relaxations"
        directory.mkdir(exist_ok=True)
        _write_json_exclusive(directory / f"{relaxation_id}.json", persisted)
        self.projects.append_event(
            project_id,
            "structure.chgnet_pre_relaxed",
            {
                "relaxation_id": relaxation_id,
                "source_artifact_id": source_artifact["artifact_id"],
                "output_artifact_id": output_artifact["artifact_id"],
                "converged": bool(result.summary.get("converged")),
                "model_name": config.model_name,
            },
        )
        return {
            **persisted,
            "schema_version": "catex.web-chgnet-pre-relaxation.v1",
            "output_artifact": output_artifact,
            "poscar_text": result.poscar_text,
            "retained": True,
        }
