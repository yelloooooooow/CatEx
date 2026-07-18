"""Local, append-oriented project and artifact persistence for CatEx Workbench."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from catex_app.services import _validate_upload, inspect_structure_upload

_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{7,47}$")
_PURPOSES = {
    "literature_reproduction",
    "original_research",
    "experimental_interpretation",
    "training",
}
_MAX_JSON_BYTES = 4 * 1024 * 1024


class ProjectStoreError(ValueError):
    """Raised when project persistence input violates a bounded local contract."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _one_line(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(char in normalized for char in "\r\n"):
        raise ProjectStoreError(
            f"{field} must be one non-empty line of at most {maximum} characters"
        )
    return normalized


class ProjectStore:
    """Filesystem repository that never deletes projects or overwrites artifacts."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.projects_root = self.root / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def _project_directory(self, project_id: str, *, must_exist: bool = True) -> Path:
        if not _PROJECT_ID.fullmatch(project_id):
            raise ProjectStoreError("project_id has an invalid format")
        directory = self.projects_root / project_id
        if directory.parent != self.projects_root:
            raise ProjectStoreError("project path escaped the configured root")
        if must_exist and not directory.is_dir():
            raise ProjectStoreError("project does not exist")
        return directory

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        data = path.read_bytes()
        if len(data) > _MAX_JSON_BYTES:
            raise ProjectStoreError("stored JSON exceeds the local safety limit")
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ProjectStoreError("stored JSON root must be an object")
        return payload

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any], *, exclusive: bool = False) -> None:
        mode = "xb" if exclusive else "wb"
        with path.open(mode) as stream:
            stream.write(_json_bytes(payload))

    def create_project(
        self,
        *,
        title: str,
        purpose: str,
        description: str = "",
        template_id: str = "structure-to-results",
    ) -> dict[str, Any]:
        title = _one_line(title, field="title", maximum=120)
        if purpose not in _PURPOSES:
            raise ProjectStoreError("project purpose is not supported")
        if len(description) > 2000:
            raise ProjectStoreError("description must not exceed 2000 characters")
        if any(ord(char) < 32 and char not in "\n\t" for char in description):
            raise ProjectStoreError("description contains unsupported control characters")
        template_id = _one_line(template_id, field="template_id", maximum=100)

        project_id = f"project-{uuid4().hex[:12]}"
        directory = self._project_directory(project_id, must_exist=False)
        directory.mkdir(exist_ok=False)
        (directory / "artifacts").mkdir(exist_ok=False)
        (directory / "runs").mkdir(exist_ok=False)
        created = _utc_now()
        payload = {
            "schema_version": "catex.web-project.v1",
            "project_id": project_id,
            "title": title,
            "purpose": purpose,
            "description": description,
            "template_id": template_id,
            "created_at_utc": created,
            "updated_at_utc": created,
            "artifact_count": 0,
            "run_count": 0,
            "workflow_saved": False,
            "protocol_saved": False,
            "remote_submission_count": 0,
        }
        self._write_json(directory / "project.json", payload, exclusive=True)
        self.append_event(project_id, "project.created", {"template_id": template_id})
        return payload

    def get_project(self, project_id: str) -> dict[str, Any]:
        directory = self._project_directory(project_id)
        return self._read_json(directory / "project.json")

    def list_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        for path in sorted(self.projects_root.glob("project-*/project.json")):
            try:
                projects.append(self._read_json(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return sorted(projects, key=lambda item: str(item.get("updated_at_utc", "")), reverse=True)

    def _update_project(self, project_id: str, **changes: Any) -> dict[str, Any]:
        directory = self._project_directory(project_id)
        project = self._read_json(directory / "project.json")
        project.update(changes)
        project["updated_at_utc"] = _utc_now()
        self._write_json(directory / "project.json", project)
        return project

    def append_event(self, project_id: str, event_type: str, details: dict[str, Any]) -> None:
        directory = self._project_directory(project_id)
        event = {
            "schema_version": "catex.web-audit-event.v1",
            "event_id": f"event-{uuid4().hex}",
            "event_type": _one_line(event_type, field="event_type", maximum=100),
            "recorded_at_utc": _utc_now(),
            "details": details,
        }
        with (directory / "audit.jsonl").open("ab") as stream:
            stream.write(
                json.dumps(event, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
            )

    def add_structure(self, project_id: str, filename: str, content: bytes) -> dict[str, Any]:
        safe_name = _validate_upload(filename, content)
        inspection = inspect_structure_upload(safe_name, content)
        if inspection["inspection"]["record"] is None:
            raise ProjectStoreError("structure inspection did not produce a valid structure record")
        directory = self._project_directory(project_id)
        digest = hashlib.sha256(content).hexdigest()
        artifact_id = f"structure-{digest[:20]}"
        metadata_path = directory / "artifacts" / f"{artifact_id}.json"
        if metadata_path.exists():
            return self._read_json(metadata_path)

        suffix = Path(safe_name).suffix.lower()
        if safe_name.upper() in {"POSCAR", "CONTCAR"}:
            suffix = ".vasp"
        stored_name = f"{digest}{suffix}"
        stored_path = directory / "artifacts" / stored_name
        with stored_path.open("xb") as stream:
            stream.write(content)
        created = _utc_now()
        artifact = {
            "schema_version": "catex.web-artifact.v1",
            "artifact_id": artifact_id,
            "project_id": project_id,
            "artifact_type": "structure",
            "original_filename": safe_name,
            "stored_filename": stored_name,
            "sha256": digest,
            "size_bytes": len(content),
            "created_at_utc": created,
            "retained": True,
            "inspection": inspection["inspection"],
            "viewer": inspection["viewer"],
        }
        self._write_json(metadata_path, artifact, exclusive=True)
        count = len(list((directory / "artifacts").glob("structure-*.json")))
        self._update_project(project_id, artifact_count=count)
        self.append_event(
            project_id,
            "artifact.structure_added",
            {"artifact_id": artifact_id, "sha256": digest, "size_bytes": len(content)},
        )
        return artifact

    def list_artifacts(self, project_id: str) -> list[dict[str, Any]]:
        directory = self._project_directory(project_id)
        return [self._read_json(path) for path in sorted((directory / "artifacts").glob("*.json"))]

    def get_artifact(self, project_id: str, artifact_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"structure-[0-9a-f]{20}", artifact_id):
            raise ProjectStoreError("artifact_id has an invalid format")
        directory = self._project_directory(project_id)
        path = directory / "artifacts" / f"{artifact_id}.json"
        if not path.is_file():
            raise ProjectStoreError("artifact does not exist")
        return self._read_json(path)

    def get_structure_review(self, project_id: str, artifact_id: str) -> dict[str, Any] | None:
        artifact = self.get_artifact(project_id, artifact_id)
        directory = self._project_directory(project_id) / "reviews"
        path = directory / f"{artifact_id}.json"
        if not path.is_file():
            return None
        review = self._read_json(path)
        if review.get("artifact_sha256") != artifact["sha256"]:
            raise ProjectStoreError("structure review does not match the immutable artifact")
        return review

    def record_structure_review(
        self,
        project_id: str,
        artifact_id: str,
        *,
        approved: bool,
        reviewer: str,
        note: str,
    ) -> dict[str, Any]:
        if not isinstance(approved, bool):
            raise ProjectStoreError("approved must be a boolean")
        reviewer = _one_line(reviewer, field="reviewer", maximum=100)
        note = _one_line(note, field="note", maximum=500)
        artifact = self.get_artifact(project_id, artifact_id)
        directory = self._project_directory(project_id) / "reviews"
        directory.mkdir(exist_ok=True)
        path = directory / f"{artifact_id}.json"
        if path.exists():
            raise ProjectStoreError("this structure artifact already has a review")
        payload = {
            "schema_version": "catex.web-structure-review.v1",
            "artifact_id": artifact_id,
            "artifact_sha256": artifact["sha256"],
            "approved": approved,
            "reviewer": reviewer,
            "reviewed_at_utc": _utc_now(),
            "note": note,
        }
        self._write_json(path, payload, exclusive=True)
        self.append_event(
            project_id,
            "artifact.structure_reviewed",
            {"artifact_id": artifact_id, "approved": approved},
        )
        return payload

    def artifact_path(self, project_id: str, artifact_id: str) -> Path:
        artifact = self.get_artifact(project_id, artifact_id)
        directory = self._project_directory(project_id)
        path = directory / "artifacts" / str(artifact["stored_filename"])
        if path.parent != directory / "artifacts" or not path.is_file():
            raise ProjectStoreError("stored artifact is unavailable")
        return path

    def artifact_source(self, project_id: str, artifact_id: str) -> dict[str, Any]:
        """Return one verified UTF-8 structure source for local Web preview."""

        artifact = self.get_artifact(project_id, artifact_id)
        path = self.artifact_path(project_id, artifact_id)
        data = path.read_bytes()
        if (
            len(data) != artifact["size_bytes"]
            or hashlib.sha256(data).hexdigest() != artifact["sha256"]
        ):
            raise ProjectStoreError("stored artifact no longer matches its immutable record")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProjectStoreError("stored structure artifact is not valid UTF-8") from exc
        return {
            "schema_version": "catex.web-artifact-source.v1",
            "artifact_id": artifact_id,
            "filename": artifact["original_filename"],
            "sha256": artifact["sha256"],
            "content": content,
            "read_only": True,
        }

    def save_workflow(self, project_id: str, workflow: dict[str, Any]) -> dict[str, Any]:
        data = _json_bytes(workflow)
        if len(data) > _MAX_JSON_BYTES:
            raise ProjectStoreError("workflow exceeds the local JSON safety limit")
        directory = self._project_directory(project_id)
        self._write_json(directory / "workflow.json", workflow)
        self._update_project(project_id, workflow_saved=True)
        self.append_event(project_id, "workflow.saved", {"size_bytes": len(data)})
        return workflow

    def mark_protocol_saved(self, project_id: str, revision_sha256: str) -> dict[str, Any]:
        project = self._update_project(project_id, protocol_saved=True)
        self.append_event(
            project_id,
            "protocol.saved",
            {"revision_sha256": revision_sha256},
        )
        return project

    def mark_run_materialized(
        self, project_id: str, *, run_id: str, plan_sha256: str
    ) -> dict[str, Any]:
        directory = self._project_directory(project_id)
        run_count = len([path for path in (directory / "runs").iterdir() if path.is_dir()])
        project = self._update_project(project_id, run_count=run_count)
        self.append_event(
            project_id,
            "run.materialized",
            {"run_id": run_id, "plan_sha256": plan_sha256},
        )
        return project

    def mark_remote_submission(
        self, project_id: str, *, run_id: str, job_id: str, plan_sha256: str
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        count = int(project.get("remote_submission_count", 0)) + 1
        updated = self._update_project(project_id, remote_submission_count=count)
        self.append_event(
            project_id,
            "run.remote_submitted",
            {"run_id": run_id, "job_id": job_id, "plan_sha256": plan_sha256},
        )
        return updated

    def list_runs(self, project_id: str) -> list[dict[str, Any]]:
        directory = self._project_directory(project_id) / "runs"
        runs: list[dict[str, Any]] = []
        for run_directory in sorted(path for path in directory.iterdir() if path.is_dir()):
            manifest_path = run_directory / "catex-manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = self._read_json(manifest_path)
            stage_path = run_directory / "catex-remote-stage.json"
            stage = self._read_json(stage_path) if stage_path.is_file() else None
            receipt_path = run_directory / "catex-submission-receipt.json"
            receipt = self._read_json(receipt_path) if receipt_path.is_file() else None
            result_records = (
                sorted((run_directory / "results").glob("pull-*/*/result.json"))
                if (run_directory / "results").is_dir()
                else []
            )
            runs.append(
                {
                    "schema_version": "catex.web-run-summary.v1",
                    "run_id": run_directory.name,
                    "plan_sha256": manifest.get("plan_sha256"),
                    "resolved_protocol_sha256": manifest.get("resolved_protocol_sha256"),
                    "energy_family_id": manifest.get("energy_family_id"),
                    "local_materialized": True,
                    "potcar_materialized": bool(manifest.get("potcar_materialized"))
                    or bool(stage and stage.get("potcar_materialized_on_hpc") is True),
                    "submitted": receipt is not None,
                    "job_id": receipt.get("job_id") if receipt else None,
                    "result_count": len(result_records),
                }
            )
        return runs

    def run_directory(self, project_id: str, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
            raise ProjectStoreError("run_id has an invalid format")
        runs = self._project_directory(project_id) / "runs"
        directory = runs / run_id
        if directory.parent != runs or not directory.is_dir():
            raise ProjectStoreError("run does not exist")
        return directory

    def get_workflow(self, project_id: str) -> dict[str, Any] | None:
        path = self._project_directory(project_id) / "workflow.json"
        return self._read_json(path) if path.is_file() else None

    def export_bundle(self, project_id: str) -> bytes:
        directory = self._project_directory(project_id)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for relative in (
                "project.json",
                "workflow.json",
                "reference-case.json",
                "audit.jsonl",
            ):
                path = directory / relative
                if path.is_file():
                    bundle.write(path, relative)
            for path in sorted((directory / "artifacts").iterdir()):
                if path.is_file():
                    bundle.write(path, f"artifacts/{path.name}")
            for folder in ("reviews", "config", "runs", "analysis"):
                root = directory / folder
                if not root.is_dir():
                    continue
                for path in sorted(item for item in root.rglob("*") if item.is_file()):
                    if path.name.upper() in {"POTCAR", "WAVECAR", "CHGCAR"}:
                        continue
                    bundle.write(path, path.relative_to(directory).as_posix())
        self.append_event(project_id, "project.exported", {"bundle_size_bytes": stream.tell()})
        return stream.getvalue()

    def project_directory(self, project_id: str) -> Path:
        """Return the validated local project directory for application services."""

        return self._project_directory(project_id)
