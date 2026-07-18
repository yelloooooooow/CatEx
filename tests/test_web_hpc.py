from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from catex_app.calculations import CalculationWorkspaceService
from catex_app.hpc import HpcWorkspaceService
from catex_app.hpc_gateway import (
    HpcConnectionProfile,
    HpcGatewayError,
    ParamikoHpcGateway,
)
from catex_app.projects import ProjectStore
from catex_web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


class _ExclusiveSftp:
    def __init__(self) -> None:
        self.modes: list[str] = []

    def open(self, remote_path: str, mode: str) -> io.BytesIO:
        assert remote_path.startswith("/approved/")
        self.modes.append(mode)
        return io.BytesIO()


def test_paramiko_upload_uses_write_plus_exclusive_create(tmp_path: Path) -> None:
    source = tmp_path / "INCAR"
    source.write_bytes(b"ENCUT = 500\n")
    sftp = _ExclusiveSftp()

    digest = ParamikoHpcGateway._write_exclusive(sftp, "/approved/INCAR", source)
    bytes_digest = ParamikoHpcGateway._write_bytes_exclusive(
        sftp, "/approved/manifest.json", b"{}\n"
    )

    assert sftp.modes == ["wx", "wx"]
    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
    assert bytes_digest == hashlib.sha256(b"{}\n").hexdigest()


def test_remote_potcar_report_must_match_approved_metadata() -> None:
    metadata = {
        "datasets": [
            {"potential_label": "Na_pv", "sha256": "a" * 64},
            {"potential_label": "Cl", "sha256": "b" * 64},
        ]
    }
    report = {
        "schema_version": "catex.remote-potcar-build.v1",
        "datasets": ["Na_pv", "Cl"],
        "dataset_sha256": ["a" * 64, "b" * 64],
        "sha256": "c" * 64,
        "overwrite_performed": False,
        "deletion_performed": False,
    }

    validated = ParamikoHpcGateway._validate_potcar_build_output(
        json.dumps(report).encode(), metadata
    )
    assert validated["sha256"] == "c" * 64

    report["dataset_sha256"][0] = "d" * 64
    with pytest.raises(HpcGatewayError, match="does not match"):
        ParamikoHpcGateway._validate_potcar_build_output(json.dumps(report).encode(), metadata)


def test_remote_potcar_hash_stays_in_stage_record_not_strict_manifest() -> None:
    manifest = {
        "schema_version": "catex.materialization-manifest.v1",
        "job_name": "nacl-static-001",
        "potcar_materialized": False,
        "submitted": False,
    }

    updated = ParamikoHpcGateway._mark_potcar_materialized(manifest)

    assert updated["potcar_materialized"] is True
    assert set(updated) == set(manifest)
    assert "remote_potcar_sha256" not in updated
    assert manifest["potcar_materialized"] is False


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def probe(self, profile: HpcConnectionProfile) -> dict[str, Any]:
        self.calls.append("probe")
        return {
            "schema_version": "catex.hpc-probe.v1",
            "connected": True,
            "writes_performed": False,
            "credentials_retained": False,
        }

    def inspect_potcar_metadata(
        self, profile: HpcConnectionProfile, labels: list[str]
    ) -> dict[str, Any]:
        self.calls.append("potcar-metadata")
        return {
            "schema_version": "catex.potcar-metadata.v1",
            "potential_family": "PAW_PBE",
            "datasets": [
                {
                    "potential_label": label,
                    "titel": f"PAW_PBE {label}",
                    "lexch": "PE",
                    "zval": 1.0,
                    "enmax_ev": 300.0,
                    "sha256": hashlib.sha256(label.encode()).hexdigest(),
                }
                for label in labels
            ],
            "raw_potcar_returned": False,
            "writes_performed": False,
        }

    def stage(self, profile: HpcConnectionProfile, local_run: Path, run_id: str) -> dict[str, Any]:
        self.calls.append("stage")
        return {
            "schema_version": "catex.hpc-stage.v1",
            "run_id": run_id,
            "potcar_materialized_on_hpc": True,
            "potcar_sha256": hashlib.sha256(b"POTCAR test\n").hexdigest(),
            "potcar_downloaded": False,
            "overwrite_performed": False,
            "deletion_performed": False,
        }

    def download_potcar(self, profile: HpcConnectionProfile, run_id: str) -> dict[str, Any]:
        self.calls.append("potcar")
        content = b"POTCAR test\n"
        return {
            "schema_version": "catex.hpc-potcar-copy.v1",
            "run_id": run_id,
            "filename": "POTCAR",
            "content_base64": base64.b64encode(content).decode("ascii"),
            "sha256": hashlib.sha256(content).hexdigest(),
            "writes_performed_remotely": False,
        }

    def submit(
        self, profile: HpcConnectionProfile, run_id: str, plan_sha256: str
    ) -> dict[str, Any]:
        self.calls.append("submit")
        return {
            "job_id": "12345",
            "raw_submission_output_sha256": "e" * 64,
        }

    def observe(self, profile: HpcConnectionProfile, run_id: str, job_id: str) -> dict[str, Any]:
        self.calls.append("observe")
        return {
            "source": "sacct",
            "snapshot": f"{job_id}|COMPLETED|0:0|41\n",
        }

    def download_results(
        self, profile: HpcConnectionProfile, run_id: str, destination: Path
    ) -> dict[str, Any]:
        self.calls.append("download")
        destination.mkdir(exist_ok=False)
        for source in (FIXTURES / "vasp_output" / "normal").iterdir():
            shutil.copyfile(source, destination / source.name)
        local_run = destination.parents[2]
        shutil.copyfile(local_run / "POSCAR", destination / "CONTCAR")
        shutil.copyfile(local_run / "slurm.sh", destination / "slurm.sh")
        manifest = json.loads((local_run / "catex-manifest.json").read_text(encoding="utf-8"))
        manifest["potcar_materialized"] = True
        (destination / "catex-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return {
            "schema_version": "catex.hpc-download.v1",
            "run_id": run_id,
            "downloaded_sha256": {"OUTCAR": "a" * 64, "OSZICAR": "b" * 64},
            "potcar_downloaded": False,
            "overwrite_performed": False,
            "deletion_performed": False,
        }


def _prepared_workspace(tmp_path: Path) -> tuple[ProjectStore, dict[str, Any], str]:
    store = ProjectStore(tmp_path / "data")
    calculations = CalculationWorkspaceService(store)
    project = store.create_project(title="HPC lifecycle", purpose="training")
    artifact = store.add_structure(
        project["project_id"],
        "POSCAR",
        (FIXTURES / "workflow" / "POSCAR").read_bytes(),
    )
    store.record_structure_review(
        project["project_id"],
        artifact["artifact_id"],
        approved=True,
        reviewer="structure-reviewer",
        note="Synthetic structure approved for workflow testing.",
    )
    calculations.save_bundle(project["project_id"], calculations.default_bundle())
    calculations.approve_protocol(
        project["project_id"], artifact["artifact_id"], reviewer="reviewer", note="approved"
    )
    plan = calculations.plan(project["project_id"], artifact["artifact_id"])["plan"]
    calculations.materialize(
        project["project_id"],
        artifact["artifact_id"],
        confirm_plan_sha256=plan["plan_sha256"],
        approved_write=True,
    )
    return store, project, plan["plan_sha256"]


def _profile() -> HpcConnectionProfile:
    return HpcConnectionProfile(
        host="cluster.example",
        port=6666,
        username="user_1",
        private_key_path="C:/private/key",
        allowed_root="/approved/project/test",
        potcar_builder="/approved/bin/make_potcar.sh",
    )


def test_hpc_lifecycle_uses_independent_gates_and_never_downloads_potcar(tmp_path: Path) -> None:
    store, project, plan_sha256 = _prepared_workspace(tmp_path)
    gateway = FakeGateway()
    service = HpcWorkspaceService(store, gateway)

    with pytest.raises(PermissionError, match="approved_remote_write"):
        service.stage(
            project["project_id"],
            "nacl-static-001",
            _profile(),
            confirm_plan_sha256=plan_sha256,
            approved_remote_write=False,
        )
    stage = service.stage(
        project["project_id"],
        "nacl-static-001",
        _profile(),
        confirm_plan_sha256=plan_sha256,
        approved_remote_write=True,
    )
    staged_run = store.list_runs(project["project_id"])[0]
    receipt = service.submit(
        project["project_id"],
        "nacl-static-001",
        _profile(),
        confirm_plan_sha256=plan_sha256,
        approved_submit=True,
    )
    observation = service.observe(project["project_id"], "nacl-static-001", _profile())
    result = service.pull_results(
        project["project_id"],
        "nacl-static-001",
        _profile(),
        approved_local_write=True,
    )
    review = service.review_result(
        project["project_id"],
        "nacl-static-001",
        accepted=False,
        reviewer="scientific-reviewer",
        note="Synthetic evidence is rejected for scientific use.",
    )

    assert stage["credentials_retained"] is False
    assert staged_run["potcar_materialized"] is True
    assert receipt["job_id"] == "12345"
    assert receipt["scientific_result_eligible"] is False
    assert observation["report"]["observation"]["state"] == "COMPLETED"
    assert result["vasp"]["scientifically_complete"] is True
    assert result["binding"]["binding_valid"] is True
    assert result["scientific_result_accepted"] is False
    assert result["human_review_required"] is False
    assert result["analysis_eligible"] is True
    assert result["final_structure"]["viewer"]["species"] == ["Na", "Cl"]
    assert result["download"]["potcar_downloaded"] is False
    assert review["decision"] == "rejected"
    assert review["scientific_result_accepted"] is False
    assert gateway.calls == ["stage", "submit", "observe", "download"]


def test_potcar_copy_requires_explicit_gate_and_matches_stage_hash(tmp_path: Path) -> None:
    store, project, plan_sha256 = _prepared_workspace(tmp_path)
    gateway = FakeGateway()
    service = HpcWorkspaceService(store, gateway)
    service.stage(
        project["project_id"],
        "nacl-static-001",
        _profile(),
        confirm_plan_sha256=plan_sha256,
        approved_remote_write=True,
    )

    with pytest.raises(PermissionError, match="approved_local_write"):
        service.copy_potcar(
            project["project_id"],
            "nacl-static-001",
            _profile(),
            approved_local_write=False,
        )
    copied = service.copy_potcar(
        project["project_id"],
        "nacl-static-001",
        _profile(),
        approved_local_write=True,
    )

    assert base64.b64decode(copied["content_base64"]) == b"POTCAR test\n"
    assert gateway.calls == ["stage", "potcar"]


def test_hpc_api_does_not_echo_or_persist_connection_secrets(tmp_path: Path) -> None:
    gateway = FakeGateway()
    client = TestClient(create_app(data_root=tmp_path / "api", hpc_gateway=gateway))
    key_path = "C:/private/do-not-retain-key"
    response = client.post(
        "/api/v1/hpc/probe",
        json={
            "profile": {
                "host": "cluster.example",
                "port": 6666,
                "username": "user_1",
                "private_key_path": key_path,
                "allowed_root": "/approved/project/test",
                "potcar_builder": "/approved/bin/make_potcar.sh",
                "host_key_sha256": "",
            }
        },
    )

    assert response.status_code == 200
    assert key_path not in response.text
    stored = "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (tmp_path / "api").rglob("*")
        if path.is_file()
    )
    assert key_path not in stored


def test_hpc_api_reads_only_sanitized_potcar_metadata(tmp_path: Path) -> None:
    gateway = FakeGateway()
    client = TestClient(create_app(data_root=tmp_path / "api", hpc_gateway=gateway))
    response = client.post(
        "/api/v1/hpc/potcar-metadata",
        json={
            "profile": {
                "host": "cluster.example",
                "port": 6666,
                "username": "user_1",
                "private_key_path": "C:/private/do-not-retain-key",
                "allowed_root": "/approved/project/test",
                "potcar_root": "/approved/potpaw_PBE.54",
            },
            "labels": ["Na_pv", "Cl"],
        },
    )

    assert response.status_code == 200
    assert response.json()["raw_potcar_returned"] is False
    assert [item["potential_label"] for item in response.json()["datasets"]] == [
        "Na_pv",
        "Cl",
    ]
    assert "do-not-retain-key" not in response.text
    assert gateway.calls == ["potcar-metadata"]
