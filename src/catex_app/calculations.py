"""Project-bound protocol validation, dry-run planning, review, and local materialization."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from catex.models import ArtifactRecord
from catex.vasp.potcar import parse_potcar_metadata
from catex.workflow import (
    CalculationPlan,
    materialize_calculation,
    parse_cluster_policy,
    parse_execution_profile,
    parse_scientific_protocol,
    plan_calculation,
    record_protocol_review,
    resolve_protocol,
)
from catex.workflow.models import ProtocolResolutionReport
from catex_app.projects import ProjectStore


class CalculationServiceError(ValueError):
    """Raised when a project calculation request violates the workflow contract."""


@dataclass(frozen=True, slots=True)
class _PlanState:
    resolution: ProtocolResolutionReport
    plan: CalculationPlan | None


def _canonical_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CalculationWorkspaceService:
    """Compose CatEx planning while treating structure diagnostics as the input gate."""

    def __init__(self, projects: ProjectStore):
        self.projects = projects

    def default_bundle(self) -> dict[str, Any]:
        return {
            "schema_version": "catex.web-calculation-config.v1",
            "protocol": {
                "schema_version": "catex.scientific-protocol.v1",
                "protocol_id": "synthetic-pbe-static",
                "target_vasp_version": "5.4.4",
                "incar": {
                    "EDIFF": "1E-6",
                    "ENCUT": "500",
                    "ISMEAR": "0",
                    "ISPIN": "1",
                    "LCHARG": "F",
                    "LWAVE": "F",
                    "NCORE": "4",
                    "NSW": "0",
                    "SIGMA": "0.05",
                },
                "kpoints": {
                    "comment": "CatEx Gamma mesh",
                    "generation_mode": "gamma",
                    "subdivisions": [3, 3, 3],
                    "shift": [0, 0, 0],
                },
            },
            "potcar_metadata": {
                "schema_version": "catex.potcar-metadata.v1",
                "potential_family": "SYNTHETIC_PAW_PBE_TEST_ONLY",
                "datasets": [
                    {
                        "element": "Na",
                        "potential_label": "Na_pv",
                        "titel": "PAW_PBE Na_pv SYNTHETIC",
                        "lexch": "PE",
                        "zval": 9,
                        "enmax_eV": 400,
                        "sha256": "a" * 64,
                    },
                    {
                        "element": "Cl",
                        "potential_label": "Cl",
                        "titel": "PAW_PBE Cl SYNTHETIC",
                        "lexch": "PE",
                        "zval": 7,
                        "enmax_eV": 450,
                        "sha256": "b" * 64,
                    },
                ],
            },
            "execution_profile": {
                "schema_version": "catex.slurm-execution-profile.v1",
                "profile_id": "synthetic-64-core",
                "job_name": "nacl-static-001",
                "partition": "compute",
                "nodes": 1,
                "tasks_per_node": 64,
                "cpus_per_task": 1,
                "walltime": "01:00:00",
                "module_loads": ["intel/oneapi2023.2_impi"],
                "executable": "/opt/vasp/5.4.4/bin/vasp_std",
                "mpi_plugin": "pmi2",
                "shell_mode": "nonlogin",
            },
            "cluster_policy": {
                "schema_version": "catex.slurm-cluster-policy.v1",
                "policy_id": "synthetic-slurm-policy",
                "allowed_partitions": ["compute", "debug"],
                "allowed_modules": ["intel/oneapi2023.2_impi"],
                "allowed_executables": ["/opt/vasp/5.4.4/bin/vasp_std"],
                "allowed_mpi_plugins": ["pmi2"],
                "max_nodes": 2,
                "max_cores_per_node": 64,
                "max_walltime_minutes": 1440,
                "allowed_shell_modes": ["nonlogin"],
            },
        }

    def _config_directory(self, project_id: str) -> Path:
        directory = self.projects.project_directory(project_id) / "config"
        directory.mkdir(exist_ok=True)
        return directory

    def save_bundle(self, project_id: str, bundle: dict[str, Any]) -> dict[str, Any]:
        expected = {
            "schema_version",
            "protocol",
            "potcar_metadata",
            "execution_profile",
            "cluster_policy",
        }
        if (
            set(bundle) != expected
            or bundle.get("schema_version") != "catex.web-calculation-config.v1"
        ):
            raise CalculationServiceError("calculation config fields or schema are invalid")
        texts = {
            "protocol.json": _canonical_text(bundle["protocol"]),
            "potcar-metadata.json": _canonical_text(bundle["potcar_metadata"]),
            "execution-profile.json": _canonical_text(bundle["execution_profile"]),
            "cluster-policy.json": _canonical_text(bundle["cluster_policy"]),
        }
        parse_scientific_protocol(texts["protocol.json"])
        parse_execution_profile(texts["execution-profile.json"])
        parse_cluster_policy(texts["cluster-policy.json"])
        metadata_bytes = texts["potcar-metadata.json"].encode("utf-8")
        metadata, diagnostics = parse_potcar_metadata(
            texts["potcar-metadata.json"],
            artifact=artifact_record_from_bytes("potcar-metadata.json", metadata_bytes),
        )
        if metadata is None or any(item.severity.value == "error" for item in diagnostics):
            message = diagnostics[0].message if diagnostics else "POTCAR metadata is invalid"
            raise CalculationServiceError(message)

        directory = self._config_directory(project_id)
        for filename, text in texts.items():
            (directory / filename).write_text(text, encoding="utf-8", newline="\n")
        revision = _digest(bundle)
        (directory / "config-record.json").write_text(
            _canonical_text(
                {
                    "schema_version": "catex.web-calculation-config-record.v1",
                    "revision_sha256": revision,
                    "saved_at_utc": _utc_now(),
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        self.projects.mark_protocol_saved(project_id, revision)
        return {"bundle": bundle, "revision_sha256": revision, "saved": True}

    def get_bundle(self, project_id: str) -> dict[str, Any] | None:
        directory = self.projects.project_directory(project_id) / "config"
        paths = {
            "protocol": directory / "protocol.json",
            "potcar_metadata": directory / "potcar-metadata.json",
            "execution_profile": directory / "execution-profile.json",
            "cluster_policy": directory / "cluster-policy.json",
        }
        if not all(path.is_file() for path in paths.values()):
            return None
        return {
            "schema_version": "catex.web-calculation-config.v1",
            **{name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()},
        }

    def _build_plan(self, project_id: str, artifact_id: str) -> _PlanState:
        directory = self.projects.project_directory(project_id)
        artifact = self.projects.get_artifact(project_id, artifact_id)
        inspection = artifact.get("inspection")
        if not isinstance(inspection, dict) or inspection.get("record") is None:
            raise CalculationServiceError("structure artifact has no valid inspection record")
        if inspection.get("status") == "error":
            raise CalculationServiceError("structure diagnostics contain blocking errors")
        config = directory / "config"
        required = (
            config / "protocol.json",
            config / "potcar-metadata.json",
            config / "execution-profile.json",
            config / "cluster-policy.json",
        )
        if not all(path.is_file() for path in required):
            raise CalculationServiceError("calculation configuration has not been saved")
        poscar_path = self.projects.artifact_path(project_id, artifact_id)
        resolution = resolve_protocol(
            config / "protocol.json",
            poscar_path=poscar_path,
            potcar_metadata_path=config / "potcar-metadata.json",
        )
        resolved = resolution.resolved
        if resolved is None:
            return _PlanState(resolution, None)

        review_path = config / "protocol-review.json"
        if review_path.is_file():
            review = json.loads(review_path.read_text(encoding="utf-8"))
            if (
                review.get("resolved_protocol_sha256") == resolved.resolved_protocol_sha256
                and review.get("approved") is True
            ):
                resolved = record_protocol_review(
                    resolved,
                    approved=True,
                    reviewer=review["reviewer"],
                    reviewed_at_utc=review["reviewed_at_utc"],
                    note=review["note"],
                )
                resolution = ProtocolResolutionReport(
                    protocol=resolution.protocol,
                    resolved=resolved,
                    diagnostics=resolution.diagnostics,
                )
        profile = parse_execution_profile((config / "execution-profile.json").read_text("utf-8"))
        policy = parse_cluster_policy((config / "cluster-policy.json").read_text("utf-8"))
        plan = plan_calculation(
            poscar_path=poscar_path,
            destination_root=directory / "runs",
            resolved_protocol=resolved,
            execution_profile=profile,
            cluster_policy=policy,
        )
        return _PlanState(resolution, plan)

    def plan(self, project_id: str, artifact_id: str) -> dict[str, Any]:
        state = self._build_plan(project_id, artifact_id)
        return {
            "schema_version": "catex.web-plan-response.v1",
            "resolution": state.resolution.to_dict(),
            "plan": state.plan.to_dict() if state.plan else None,
            "writes_performed": False,
            "submitted": False,
        }

    def approve_protocol(
        self,
        project_id: str,
        artifact_id: str,
        *,
        reviewer: str,
        note: str,
    ) -> dict[str, Any]:
        state = self._build_plan(project_id, artifact_id)
        if state.resolution.resolved is None or state.resolution.has_errors:
            raise CalculationServiceError("invalid protocol cannot be approved")
        resolved = state.resolution.resolved
        reviewed_at = _utc_now()
        reviewed = record_protocol_review(
            resolved,
            approved=True,
            reviewer=reviewer,
            reviewed_at_utc=reviewed_at,
            note=note,
        )
        record = {
            "schema_version": "catex.web-protocol-review.v1",
            "resolved_protocol_sha256": reviewed.resolved_protocol_sha256,
            "approved": True,
            "reviewer": reviewed.review.reviewer,
            "reviewed_at_utc": reviewed_at,
            "note": reviewed.review.note,
        }
        config = self.projects.project_directory(project_id) / "config"
        (config / "protocol-review.json").write_text(
            _canonical_text(record), encoding="utf-8", newline="\n"
        )
        self.projects.append_event(
            project_id,
            "protocol.approved",
            {"resolved_protocol_sha256": reviewed.resolved_protocol_sha256},
        )
        return record

    def materialize(
        self,
        project_id: str,
        artifact_id: str,
        *,
        confirm_plan_sha256: str,
        approved_write: bool,
    ) -> dict[str, Any]:
        if not approved_write:
            raise PermissionError("approved_write=true is required")
        state = self._build_plan(project_id, artifact_id)
        if state.plan is None:
            raise CalculationServiceError("a valid calculation plan is required")
        if state.plan.plan_sha256 != confirm_plan_sha256:
            raise CalculationServiceError(
                "plan confirmation digest does not match the current plan"
            )
        result = materialize_calculation(state.plan, approved_write=True)
        if not result.has_errors:
            self.projects.mark_run_materialized(
                project_id,
                run_id=state.plan.job_name,
                plan_sha256=state.plan.plan_sha256,
            )
        return {
            "schema_version": "catex.web-materialization-response.v1",
            "plan": state.plan.to_dict(),
            "materialization": result.to_dict(),
            "submitted": False,
            "potcar_materialized": False,
        }


def artifact_record_from_bytes(name: str, data: bytes) -> ArtifactRecord:
    """Build the small ArtifactRecord required by the metadata parser."""

    return ArtifactRecord(path=name, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
