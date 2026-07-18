from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from catex_app.projects import ProjectStore, ProjectStoreError


def _poscar() -> bytes:
    fixture = Path(__file__).parent / "fixtures" / "synthetic" / "workflow" / "POSCAR"
    return fixture.read_bytes()


def test_project_store_persists_structure_workflow_and_audit(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")
    project = store.create_project(
        title="NaCl validation",
        purpose="training",
        description="Synthetic local project",
    )

    artifact = store.add_structure(project["project_id"], "POSCAR", _poscar())
    duplicate = store.add_structure(project["project_id"], "POSCAR", _poscar())
    saved = store.save_workflow(
        project["project_id"],
        {"schema_version": "catex.web-workflow.v1", "nodes": [], "edges": []},
    )

    assert artifact["retained"] is True
    assert artifact["inspection"]["record"]["num_sites"] == 2
    assert duplicate["artifact_id"] == artifact["artifact_id"]
    assert len(store.list_artifacts(project["project_id"])) == 1
    source = store.artifact_source(project["project_id"], artifact["artifact_id"])
    assert source["content"].encode("utf-8") == _poscar()
    assert source["sha256"] == artifact["sha256"]
    assert source["read_only"] is True
    assert store.get_workflow(project["project_id"]) == saved
    assert store.get_project(project["project_id"])["artifact_count"] == 1
    audit = (store.project_directory(project["project_id"]) / "audit.jsonl").read_text(
        encoding="utf-8"
    )
    assert "project.created" in audit
    assert "artifact.structure_added" in audit
    assert "workflow.saved" in audit


def test_project_bundle_contains_only_bounded_project_files(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")
    project = store.create_project(title="Bundle", purpose="training")
    store.add_structure(project["project_id"], "POSCAR", _poscar())

    content = store.export_bundle(project["project_id"])
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        names = bundle.namelist()

    assert "project.json" in names
    assert any(name.startswith("artifacts/structure-") and name.endswith(".json") for name in names)
    assert all("POTCAR" not in name.upper() for name in names)


def test_project_store_rejects_paths_and_unknown_purpose(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data")
    with pytest.raises(ProjectStoreError, match="purpose"):
        store.create_project(title="Invalid", purpose="unsupported")
    with pytest.raises(ProjectStoreError, match="project_id"):
        store.get_project("../outside")
