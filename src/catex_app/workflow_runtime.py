"""Immutable workflow revisions and append-only run evidence for CatEx."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from catex_app.projects import ProjectStore, ProjectStoreError

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ATTEMPT_STATUSES = {
    "planned",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "blocked",
}
_MAX_DOCUMENT_BYTES = 4 * 1024 * 1024


class WorkflowRuntimeError(ValueError):
    """Raised when workflow versioning or execution evidence is inconsistent."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _validate_document(payload: dict[str, Any]) -> None:
    if len(_canonical_bytes(payload)) > _MAX_DOCUMENT_BYTES:
        raise WorkflowRuntimeError("workflow document exceeds the local safety limit")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkflowRuntimeError(f"could not read workflow record: {path.name}") from error
    if not isinstance(payload, dict):
        raise WorkflowRuntimeError("workflow record root must be an object")
    return payload


def _write_json(path: Path, payload: dict[str, Any], *, exclusive: bool = True) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    if len(data) > _MAX_DOCUMENT_BYTES:
        raise WorkflowRuntimeError("workflow record exceeds the local safety limit")
    with path.open("xb" if exclusive else "wb") as stream:
        stream.write(data)


def _require_id(value: str, field: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise WorkflowRuntimeError(f"{field} has an invalid format")
    return value


class WorkflowRuntimeService:
    """Manage one mutable draft and immutable published/run records per project."""

    def __init__(self, store: ProjectStore):
        self.store = store

    def _workflow_root(self, project_id: str) -> Path:
        root = self.store.project_directory(project_id) / "workflows"
        root.mkdir(exist_ok=True)
        (root / "revisions").mkdir(exist_ok=True)
        (root / "run-graphs").mkdir(exist_ok=True)
        return root

    def get_draft(self, project_id: str) -> dict[str, Any] | None:
        workflow = self.store.get_workflow(project_id)
        if workflow is None:
            return None
        if workflow.get("schema_version") == "catex.workflow-draft.v1":
            return workflow
        graph = {
            "nodes": list(workflow.get("nodes", [])),
            "edges": list(workflow.get("edges", [])),
        }
        return {
            "schema_version": "catex.workflow-draft.v1",
            "draft_sha256": _sha256(graph),
            "generation": 1,
            "saved_at_utc": None,
            **graph,
        }

    def save_draft(
        self,
        project_id: str,
        graph: dict[str, Any],
        *,
        expected_draft_sha256: str | None = None,
    ) -> dict[str, Any]:
        normalized = {
            "nodes": list(graph.get("nodes", [])),
            "edges": list(graph.get("edges", [])),
        }
        _validate_document(normalized)
        current = self.get_draft(project_id)
        if (
            expected_draft_sha256 is not None
            and current is not None
            and current.get("draft_sha256") != expected_draft_sha256
        ):
            raise WorkflowRuntimeError(
                "workflow draft changed since it was loaded; refresh before saving"
            )
        generation = int(current.get("generation", 0)) + 1 if current else 1
        payload = {
            "schema_version": "catex.workflow-draft.v1",
            "draft_sha256": _sha256(normalized),
            "generation": generation,
            "saved_at_utc": _utc_now(),
            **normalized,
        }
        try:
            self.store.save_workflow(project_id, payload)
        except ProjectStoreError as error:
            raise WorkflowRuntimeError(str(error)) from error
        return payload

    def publish_revision(
        self,
        project_id: str,
        *,
        title: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        draft = self.get_draft(project_id)
        if draft is None:
            raise WorkflowRuntimeError("save a workflow draft before publishing")
        graph = {"nodes": draft["nodes"], "edges": draft["edges"]}
        content_sha256 = _sha256(graph)
        revision_id = f"revision-{content_sha256[:16]}"
        revisions = self._workflow_root(project_id) / "revisions"
        path = revisions / f"{revision_id}.json"
        if path.is_file():
            return _read_json(path)
        payload = {
            "schema_version": "catex.workflow-revision.v1",
            "revision_id": revision_id,
            "content_sha256": content_sha256,
            "published_at_utc": _utc_now(),
            "title": title.strip()[:120],
            "note": note.strip()[:1000],
            "workflow": graph,
        }
        _write_json(path, payload)
        self.store.append_event(
            project_id,
            "workflow.revision_published",
            {"revision_id": revision_id, "content_sha256": content_sha256},
        )
        return payload

    def list_revisions(self, project_id: str) -> list[dict[str, Any]]:
        revisions = self._workflow_root(project_id) / "revisions"
        records = [_read_json(path) for path in revisions.glob("revision-*.json")]
        return sorted(
            records,
            key=lambda item: str(item.get("published_at_utc", "")),
            reverse=True,
        )

    def get_revision(self, project_id: str, revision_id: str) -> dict[str, Any]:
        _require_id(revision_id, "revision_id")
        path = self._workflow_root(project_id) / "revisions" / f"{revision_id}.json"
        if not path.is_file():
            raise WorkflowRuntimeError("workflow revision does not exist")
        return _read_json(path)

    def create_run_graph(
        self,
        project_id: str,
        *,
        revision_id: str,
        label: str = "",
        bindings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        revision = self.get_revision(project_id, revision_id)
        run_graph_id = f"run-graph-{uuid4().hex[:16]}"
        root = self._workflow_root(project_id) / "run-graphs" / run_graph_id
        root.mkdir(exist_ok=False)
        (root / "attempts").mkdir(exist_ok=False)
        payload = {
            "schema_version": "catex.workflow-run-graph.v1",
            "run_graph_id": run_graph_id,
            "revision_id": revision_id,
            "workflow_sha256": revision["content_sha256"],
            "created_at_utc": _utc_now(),
            "label": label.strip()[:120],
            "bindings": bindings or {},
            "workflow": revision["workflow"],
            "state": "planned",
        }
        _write_json(root / "run-graph.json", payload)
        self.store.append_event(
            project_id,
            "workflow.run_graph_created",
            {"run_graph_id": run_graph_id, "revision_id": revision_id},
        )
        return payload

    def list_run_graphs(self, project_id: str) -> list[dict[str, Any]]:
        root = self._workflow_root(project_id) / "run-graphs"
        records = [
            _read_json(path) for path in root.glob("run-graph-*/run-graph.json") if path.is_file()
        ]
        return sorted(
            records,
            key=lambda item: str(item.get("created_at_utc", "")),
            reverse=True,
        )

    def get_run_graph(self, project_id: str, run_graph_id: str) -> dict[str, Any]:
        _require_id(run_graph_id, "run_graph_id")
        path = self._workflow_root(project_id) / "run-graphs" / run_graph_id / "run-graph.json"
        if not path.is_file():
            raise WorkflowRuntimeError("workflow run graph does not exist")
        return _read_json(path)

    def record_attempt(
        self,
        project_id: str,
        *,
        run_graph_id: str,
        node_id: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_graph = self.get_run_graph(project_id, run_graph_id)
        _require_id(node_id, "node_id")
        if status not in _ATTEMPT_STATUSES:
            raise WorkflowRuntimeError("node attempt status is not supported")
        workflow_nodes = {
            str(item.get("node_id")) for item in run_graph["workflow"].get("nodes", [])
        }
        if node_id not in workflow_nodes:
            raise WorkflowRuntimeError("node is not part of the immutable run graph")
        attempts_root = (
            self._workflow_root(project_id) / "run-graphs" / run_graph_id / "attempts" / node_id
        )
        attempts_root.mkdir(exist_ok=True)
        attempt_number = len(list(attempts_root.glob("attempt-*.json"))) + 1
        payload = {
            "schema_version": "catex.workflow-node-attempt.v1",
            "attempt_id": f"{node_id}-attempt-{attempt_number}",
            "attempt_number": attempt_number,
            "run_graph_id": run_graph_id,
            "node_id": node_id,
            "status": status,
            "recorded_at_utc": _utc_now(),
            "details": details or {},
        }
        _write_json(attempts_root / f"attempt-{attempt_number:04d}.json", payload)
        self.store.append_event(
            project_id,
            "workflow.node_attempt_recorded",
            {
                "run_graph_id": run_graph_id,
                "node_id": node_id,
                "attempt_number": attempt_number,
                "status": status,
            },
        )
        return payload

    def list_attempts(
        self,
        project_id: str,
        *,
        run_graph_id: str,
        node_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.get_run_graph(project_id, run_graph_id)
        attempts = self._workflow_root(project_id) / "run-graphs" / run_graph_id / "attempts"
        if node_id is not None:
            _require_id(node_id, "node_id")
            paths = attempts.glob(f"{node_id}/attempt-*.json")
        else:
            paths = attempts.glob("*/attempt-*.json")
        records = [_read_json(path) for path in paths if path.is_file()]
        return sorted(
            records,
            key=lambda item: (
                str(item.get("node_id", "")),
                int(item.get("attempt_number", 0)),
            ),
        )
