from __future__ import annotations

from pathlib import Path

import pytest

from catex_app.projects import ProjectStore
from catex_app.workflow import default_workflow_template
from catex_app.workflow_runtime import WorkflowRuntimeError, WorkflowRuntimeService


def _graph() -> dict[str, object]:
    template = default_workflow_template()
    return {
        "nodes": [item.to_dict() for item in template.nodes],
        "edges": [item.to_dict() for item in template.edges],
    }


def test_workflow_runtime_publishes_immutable_revision_and_records_attempts(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)
    project = store.create_project(title="Runtime", purpose="training")
    service = WorkflowRuntimeService(store)

    draft = service.save_draft(project["project_id"], _graph())
    revision = service.publish_revision(project["project_id"], title="Baseline")
    duplicate = service.publish_revision(project["project_id"], title="Ignored duplicate")
    run_graph = service.create_run_graph(
        project["project_id"],
        revision_id=revision["revision_id"],
        label="Acceptance",
    )
    node_id = run_graph["workflow"]["nodes"][0]["node_id"]
    first = service.record_attempt(
        project["project_id"],
        run_graph_id=run_graph["run_graph_id"],
        node_id=node_id,
        status="queued",
    )
    second = service.record_attempt(
        project["project_id"],
        run_graph_id=run_graph["run_graph_id"],
        node_id=node_id,
        status="running",
    )

    assert draft["generation"] == 1
    assert duplicate["revision_id"] == revision["revision_id"]
    assert len(service.list_revisions(project["project_id"])) == 1
    assert first["attempt_number"] == 1
    assert second["attempt_number"] == 2
    assert (
        len(
            service.list_attempts(
                project["project_id"],
                run_graph_id=run_graph["run_graph_id"],
            )
        )
        == 2
    )


def test_workflow_runtime_uses_optimistic_draft_concurrency(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create_project(title="Concurrency", purpose="training")
    service = WorkflowRuntimeService(store)
    draft = service.save_draft(project["project_id"], _graph())
    service.save_draft(
        project["project_id"],
        _graph(),
        expected_draft_sha256=draft["draft_sha256"],
    )

    with pytest.raises(WorkflowRuntimeError, match="changed since"):
        service.save_draft(
            project["project_id"],
            _graph(),
            expected_draft_sha256="0" * 64,
        )
