"""Plan and explicitly materialize local VASP inputs without POTCAR or submission."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from catex.hashing import artifact_record
from catex.models import ArtifactRecord, Diagnostic, Severity
from catex.vasp.validation import validate_vasp_input
from catex.workflow.models import (
    CalculationPlan,
    MaterializationResult,
    ResolvedProtocol,
    SlurmClusterPolicy,
    SlurmExecutionProfile,
)
from catex.workflow.slurm import plan_slurm_script

_JOB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _canonical_json(data: Any) -> bytes:
    return json.dumps(
        data,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _plan_payload(
    *,
    job_name: str,
    job_directory: str,
    poscar_sha256: str,
    resolved_protocol_sha256: str,
    slurm_script_sha256: str,
) -> dict[str, str]:
    return {
        "schema": "catex.calculation-plan-digest.v1",
        "job_name": job_name,
        "job_directory": job_directory,
        "poscar_sha256": poscar_sha256,
        "resolved_protocol_sha256": resolved_protocol_sha256,
        "slurm_script_sha256": slurm_script_sha256,
    }


def _digest(data: Any) -> str:
    return hashlib.sha256(_canonical_json(data)).hexdigest()


def plan_calculation(
    *,
    poscar_path: str | Path,
    destination_root: str | Path,
    resolved_protocol: ResolvedProtocol,
    execution_profile: SlurmExecutionProfile,
    cluster_policy: SlurmClusterPolicy,
) -> CalculationPlan:
    """Create an in-memory plan. No directory or file is created."""

    diagnostics: list[Diagnostic] = []
    job_name = execution_profile.job_name
    if not _JOB_NAME.fullmatch(job_name):
        raise ValueError("job_name must be a safe 1-64 character identifier")
    try:
        root = Path(destination_root).resolve(strict=True)
    except OSError as exc:
        raise ValueError("destination_root must be a pre-existing directory") from exc
    if not root.is_dir():
        raise ValueError("destination_root must be a pre-existing directory")
    job_directory = root / job_name
    if job_directory.exists():
        diagnostics.append(
            Diagnostic(
                "MATERIALIZATION_DESTINATION_EXISTS",
                Severity.ERROR,
                "The planned job directory already exists and will not be reused.",
                {"job_directory": str(job_directory)},
            )
        )
    poscar_artifact = artifact_record(Path(poscar_path))
    if len(resolved_protocol.source_artifacts) != 3:
        raise ValueError("resolved_protocol must contain protocol, POSCAR, and metadata artifacts")
    expected_poscar = resolved_protocol.source_artifacts[1]
    if poscar_artifact.sha256 != expected_poscar.sha256:
        diagnostics.append(
            Diagnostic(
                "MATERIALIZATION_POSCAR_CHANGED",
                Severity.ERROR,
                "The POSCAR no longer matches the artifact used for protocol resolution.",
            )
        )
    if not resolved_protocol.approved:
        diagnostics.append(
            Diagnostic(
                "PROTOCOL_MANUAL_REVIEW_PENDING",
                Severity.WARNING,
                "Materialization remains blocked until the resolved protocol is approved.",
                {"resolved_protocol_sha256": resolved_protocol.resolved_protocol_sha256},
            )
        )
    slurm = plan_slurm_script(execution_profile, cluster_policy)
    diagnostics.extend(slurm.diagnostics)
    plan_payload = _plan_payload(
        job_name=job_name,
        job_directory=str(job_directory),
        poscar_sha256=poscar_artifact.sha256,
        resolved_protocol_sha256=resolved_protocol.resolved_protocol_sha256,
        slurm_script_sha256=slurm.script_sha256,
    )
    return CalculationPlan(
        job_name=job_name,
        job_directory=str(job_directory),
        destination_root=str(root),
        poscar_artifact=poscar_artifact,
        resolved_protocol=resolved_protocol,
        slurm=slurm,
        plan_sha256=_digest(plan_payload),
        diagnostics=tuple(diagnostics),
    )


def _metadata_document(resolved: ResolvedProtocol) -> dict[str, Any]:
    metadata = resolved.potcar_metadata
    return {
        "schema_version": metadata.schema_version,
        "potential_family": metadata.potential_family,
        "datasets": [item.to_dict() for item in metadata.datasets],
    }


def _write_text_exclusive(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _preflight(plan: CalculationPlan) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    payload = _plan_payload(
        job_name=plan.job_name,
        job_directory=plan.job_directory,
        poscar_sha256=plan.poscar_artifact.sha256,
        resolved_protocol_sha256=plan.resolved_protocol.resolved_protocol_sha256,
        slurm_script_sha256=plan.slurm.script_sha256,
    )
    if _digest(payload) != plan.plan_sha256:
        diagnostics.append(
            Diagnostic(
                "MATERIALIZATION_PLAN_DIGEST_MISMATCH",
                Severity.ERROR,
                "The calculation plan fields no longer match its digest.",
            )
        )
    source = Path(plan.poscar_artifact.path)
    try:
        current = artifact_record(source)
    except OSError as exc:
        diagnostics.append(
            Diagnostic(
                "MATERIALIZATION_POSCAR_READ_FAILED",
                Severity.ERROR,
                "The planned POSCAR could not be re-read.",
                {"exception_type": type(exc).__name__},
            )
        )
    else:
        changed = (
            current.sha256 != plan.poscar_artifact.sha256
            or current.size_bytes != plan.poscar_artifact.size_bytes
        )
        if changed:
            diagnostics.append(
                Diagnostic(
                    "MATERIALIZATION_POSCAR_CHANGED",
                    Severity.ERROR,
                    "The POSCAR changed after planning; a new plan is required.",
                )
            )
    job_directory = Path(plan.job_directory)
    root = Path(plan.destination_root)
    try:
        current_root = root.resolve(strict=True)
        resolved_job_parent = job_directory.resolve(strict=False).parent
    except OSError:
        diagnostics.append(
            Diagnostic(
                "MATERIALIZATION_DESTINATION_ROOT_CHANGED",
                Severity.ERROR,
                "The destination root is no longer the directory recorded by the plan.",
            )
        )
    else:
        if str(current_root) != plan.destination_root or resolved_job_parent != current_root:
            diagnostics.append(
                Diagnostic(
                    "MATERIALIZATION_DESTINATION_ROOT_CHANGED",
                    Severity.ERROR,
                    "The destination root resolution changed after planning.",
                )
            )
    if job_directory.parent != root or job_directory.name != plan.job_name:
        diagnostics.append(
            Diagnostic(
                "MATERIALIZATION_PATH_POLICY_VIOLATION",
                Severity.ERROR,
                "The job directory must be one direct, safely named child of destination_root.",
            )
        )
    if job_directory.exists():
        diagnostics.append(
            Diagnostic(
                "MATERIALIZATION_DESTINATION_EXISTS",
                Severity.ERROR,
                "The job directory already exists and will not be overwritten.",
            )
        )
    if not plan.resolved_protocol.approved:
        diagnostics.append(
            Diagnostic(
                "PROTOCOL_MANUAL_REVIEW_REQUIRED",
                Severity.ERROR,
                "The resolved protocol has not been approved by a human reviewer.",
            )
        )
    if plan.slurm.has_errors:
        diagnostics.append(
            Diagnostic(
                "SLURM_STATIC_VALIDATION_REQUIRED",
                Severity.ERROR,
                "A Slurm script with static-validation errors cannot be materialized.",
            )
        )
    return tuple(diagnostics)


def materialize_calculation(
    plan: CalculationPlan,
    *,
    approved_write: bool = False,
) -> MaterializationResult:
    """Write fixed local inputs into one new directory; never write POTCAR or submit."""

    if not approved_write:
        raise PermissionError("approved_write=True is required for local materialization")
    diagnostics = list(_preflight(plan))
    if any(item.severity is Severity.ERROR for item in diagnostics):
        return MaterializationResult(plan.job_directory, (), tuple(diagnostics))

    destination = Path(plan.job_directory)
    artifacts: list[ArtifactRecord] = []
    try:
        destination.mkdir(exist_ok=False)
        source = Path(plan.poscar_artifact.path)
        with (
            source.open("rb") as input_stream,
            (destination / "POSCAR").open("xb") as output_stream,
        ):
            while chunk := input_stream.read(1024 * 1024):
                output_stream.write(chunk)
        _write_text_exclusive(destination / "INCAR", plan.resolved_protocol.incar_text)
        _write_text_exclusive(destination / "KPOINTS", plan.resolved_protocol.kpoints_text)
        _write_text_exclusive(
            destination / "catex-potcar-metadata.json",
            json.dumps(_metadata_document(plan.resolved_protocol), indent=2, sort_keys=True) + "\n",
        )
        _write_text_exclusive(destination / "slurm.sh", plan.slurm.script_text)
        manifest = {
            "schema_version": "catex.materialization-manifest.v1",
            "job_name": plan.job_name,
            "plan_sha256": plan.plan_sha256,
            "poscar_sha256": plan.poscar_artifact.sha256,
            "resolved_protocol_sha256": plan.resolved_protocol.resolved_protocol_sha256,
            "energy_family_id": plan.resolved_protocol.energy_family_id,
            "protocol_review": plan.resolved_protocol.review.to_dict(),
            "execution_profile_id": plan.slurm.profile.profile_id,
            "cluster_policy_id": plan.slurm.policy_id,
            "slurm_script_sha256": plan.slurm.script_sha256,
            "potcar_required_on_hpc": True,
            "potcar_materialized": False,
            "submitted": False,
        }
        _write_text_exclusive(
            destination / "catex-manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
    except OSError as exc:
        diagnostics.append(
            Diagnostic(
                "MATERIALIZATION_WRITE_FAILED",
                Severity.ERROR,
                "Local materialization failed; any partial directory is preserved for audit.",
                {"exception_type": type(exc).__name__},
            )
        )
        for name in (
            "POSCAR",
            "INCAR",
            "KPOINTS",
            "catex-potcar-metadata.json",
            "slurm.sh",
            "catex-manifest.json",
        ):
            path = destination / name
            if path.is_file():
                artifacts.append(artifact_record(path))
        return MaterializationResult(str(destination), tuple(artifacts), tuple(diagnostics))

    for name in (
        "POSCAR",
        "INCAR",
        "KPOINTS",
        "catex-potcar-metadata.json",
        "slurm.sh",
        "catex-manifest.json",
    ):
        artifacts.append(artifact_record(destination / name))
    validation = validate_vasp_input(destination, mode="strict")
    diagnostics.extend(validation.diagnostics)
    diagnostics.append(
        Diagnostic(
            "CALCULATION_NOT_SUBMITTED",
            Severity.INFO,
            "Inputs were materialized locally; no scheduler command was invoked.",
        )
    )
    return MaterializationResult(str(destination), tuple(artifacts), tuple(diagnostics))
