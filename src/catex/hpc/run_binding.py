"""Read-only submission receipt parsing and run-evidence binding."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from catex.hpc.run_binding_models import (
    RunBindingReport,
    RunBindingStatus,
    RunProtocolIdentity,
    SubmissionReceipt,
    SubmissionReceiptParseReport,
)
from catex.hpc.slurm_models import (
    SlurmJobState,
    SlurmSnapshotSource,
    VaspRestartEvidence,
)
from catex.hpc.slurm_observation import parse_slurm_snapshot_path
from catex.models import Diagnostic, Severity
from catex.vasp.output import parse_vasp_output

_HASH = re.compile(r"^[0-9a-f]{64}$")
_ENERGY_FAMILY = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_JOB_ID = re.compile(r"^[0-9]+(?:[_+][0-9]+)?$")
_MAX_RECEIPT_BYTES = 64 * 1024
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_SLURM_SCRIPT_BYTES = 1024 * 1024
_SUBMISSION_TEMPLATE = (
    "sbatch --chdir=<authorized-job-directory> --parsable <authorized-job-directory>/slurm.sh"
)
_RECEIPT_FIELDS = {
    "schema_version",
    "submitted_at_utc",
    "job_id",
    "job_directory_name",
    "job_name",
    "plan_sha256",
    "slurm_script_sha256",
    "submission_command_template",
    "raw_submission_output_sha256",
    "submission_performed",
    "approved_scope",
    "scientific_result_eligible",
    "overwrite_performed",
    "deletion_performed",
}
_MANIFEST_FIELDS = {
    "schema_version",
    "job_name",
    "plan_sha256",
    "poscar_sha256",
    "resolved_protocol_sha256",
    "energy_family_id",
    "protocol_review",
    "execution_profile_id",
    "cluster_policy_id",
    "slurm_script_sha256",
    "potcar_required_on_hpc",
    "potcar_materialized",
    "submitted",
}


def _error(code: str, message: str, context: dict[str, object] | None = None) -> Diagnostic:
    return Diagnostic(code, Severity.ERROR, message, context or {})


def _receipt_error(
    *,
    source_name: str,
    source_sha256: str | None,
    source_size_bytes: int | None,
    code: str,
    message: str,
) -> SubmissionReceiptParseReport:
    return SubmissionReceiptParseReport(
        source_name=source_name,
        source_sha256=source_sha256,
        source_size_bytes=source_size_bytes,
        receipt=None,
        diagnostics=(_error(code, message),),
    )


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("submitted_at_utc must be a bounded ISO-8601 UTC timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("submitted_at_utc must be a valid ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("submitted_at_utc must use Z or +00:00")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_string(raw: dict[str, Any], field: str, pattern: re.Pattern[str]) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{field} has an invalid value")
    return value


def _strict_bool(raw: dict[str, Any], field: str, expected: bool) -> bool:
    value = raw.get(field)
    if not isinstance(value, bool) or value is not expected:
        raise ValueError(f"{field} must be {str(expected).lower()}")
    return value


def _boolean(raw: dict[str, Any], field: str) -> bool:
    value = raw.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def parse_submission_receipt(
    content: str | bytes,
    *,
    source_name: str = "catex-submission-receipt.json",
) -> SubmissionReceiptParseReport:
    """Parse bounded UTF-8 receipt JSON without retaining raw content or full paths."""

    raw_bytes = content.encode("utf-8") if isinstance(content, str) else content
    name = Path(source_name).name or "catex-submission-receipt.json"
    digest = hashlib.sha256(raw_bytes).hexdigest()
    size = len(raw_bytes)
    if size > _MAX_RECEIPT_BYTES:
        return _receipt_error(
            source_name=name,
            source_sha256=digest,
            source_size_bytes=size,
            code="SUBMISSION_RECEIPT_TOO_LARGE",
            message="The submission receipt exceeds the 64 KiB parser limit.",
        )
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _receipt_error(
            source_name=name,
            source_sha256=digest,
            source_size_bytes=size,
            code="SUBMISSION_RECEIPT_ENCODING_INVALID",
            message="The submission receipt must be UTF-8 JSON.",
        )
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return _receipt_error(
            source_name=name,
            source_sha256=digest,
            source_size_bytes=size,
            code="SUBMISSION_RECEIPT_JSON_INVALID",
            message="The submission receipt is not valid JSON.",
        )
    if not isinstance(raw, dict):
        return _receipt_error(
            source_name=name,
            source_sha256=digest,
            source_size_bytes=size,
            code="SUBMISSION_RECEIPT_SCHEMA_INVALID",
            message="The submission receipt root must be a JSON object.",
        )
    unknown = sorted(set(raw) - _RECEIPT_FIELDS)
    missing = sorted(_RECEIPT_FIELDS - set(raw))
    if unknown or missing or raw.get("schema_version") != "catex.submission-receipt.v1":
        return _receipt_error(
            source_name=name,
            source_sha256=digest,
            source_size_bytes=size,
            code="SUBMISSION_RECEIPT_SCHEMA_INVALID",
            message="The submission receipt fields or schema version are invalid.",
        )
    try:
        command_template = raw.get("submission_command_template")
        if command_template != _SUBMISSION_TEMPLATE:
            raise ValueError("submission_command_template is not the fixed supported template")
        receipt = SubmissionReceipt(
            job_id=_safe_string(raw, "job_id", _JOB_ID),
            job_directory_name=_safe_string(raw, "job_directory_name", _IDENTIFIER),
            job_name=_safe_string(raw, "job_name", _IDENTIFIER),
            plan_sha256=_safe_string(raw, "plan_sha256", _HASH),
            slurm_script_sha256=_safe_string(raw, "slurm_script_sha256", _HASH),
            submitted_at_utc=_timestamp(raw.get("submitted_at_utc")),
            approved_scope=_safe_string(raw, "approved_scope", _SCOPE),
            submission_command_template=command_template,
            raw_submission_output_sha256=_safe_string(raw, "raw_submission_output_sha256", _HASH),
            submission_performed=_strict_bool(raw, "submission_performed", True),
            scientific_result_eligible=_boolean(raw, "scientific_result_eligible"),
            overwrite_performed=_strict_bool(raw, "overwrite_performed", False),
            deletion_performed=_strict_bool(raw, "deletion_performed", False),
        )
    except ValueError as exc:
        return _receipt_error(
            source_name=name,
            source_sha256=digest,
            source_size_bytes=size,
            code="SUBMISSION_RECEIPT_VALUE_INVALID",
            message=str(exc),
        )
    return SubmissionReceiptParseReport(name, digest, size, receipt, ())


def parse_submission_receipt_path(path: str | Path) -> SubmissionReceiptParseReport:
    """Read one receipt with a hard size limit; never retain its full source path."""

    source = Path(path)
    name = source.name or "catex-submission-receipt.json"
    hasher = hashlib.sha256()
    buffer = bytearray()
    size = 0
    try:
        with source.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                hasher.update(chunk)
                size += len(chunk)
                if size <= _MAX_RECEIPT_BYTES:
                    buffer.extend(chunk)
                else:
                    buffer.clear()
    except OSError as exc:
        return _receipt_error(
            source_name=name,
            source_sha256=None,
            source_size_bytes=None,
            code="SUBMISSION_RECEIPT_READ_FAILED",
            message=f"The submission receipt could not be read ({type(exc).__name__}).",
        )
    if size > _MAX_RECEIPT_BYTES:
        return _receipt_error(
            source_name=name,
            source_sha256=hasher.hexdigest(),
            source_size_bytes=size,
            code="SUBMISSION_RECEIPT_TOO_LARGE",
            message="The submission receipt exceeds the 64 KiB parser limit.",
        )
    return parse_submission_receipt(bytes(buffer), source_name=name)


def _read_bounded(path: Path, maximum: int) -> tuple[bytes | None, str | None, Diagnostic | None]:
    hasher = hashlib.sha256()
    buffer = bytearray()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                hasher.update(chunk)
                size += len(chunk)
                if size <= maximum:
                    buffer.extend(chunk)
                else:
                    buffer.clear()
    except OSError as exc:
        return (
            None,
            None,
            _error(
                "RUN_BINDING_ARTIFACT_READ_FAILED",
                "A required run-binding artifact could not be read.",
                {"artifact_name": path.name, "exception_type": type(exc).__name__},
            ),
        )
    if size > maximum:
        return (
            None,
            hasher.hexdigest(),
            _error(
                "RUN_BINDING_ARTIFACT_TOO_LARGE",
                "A required run-binding artifact exceeds its parser limit.",
                {"artifact_name": path.name, "size_bytes": size},
            ),
        )
    return bytes(buffer), hasher.hexdigest(), None


def _vasp_evidence(directory: Path) -> tuple[VaspRestartEvidence, bool]:
    report = parse_vasp_output(directory)
    evidence = VaspRestartEvidence(
        output_directory_name=directory.name or "vasp-output",
        outcome=report.termination.outcome.value,
        scientifically_complete=report.scientifically_complete,
        electronic_convergence=report.convergence.electronic.value,
        ionic_convergence=report.convergence.ionic.value,
        fatal_error_codes=report.termination.fatal_error_codes,
        artifact_names_and_sha256=tuple(
            sorted((Path(item.path).name, item.sha256) for item in report.artifacts)
        ),
    )
    return evidence, report.scientifically_complete


def _manifest_values(
    content: bytes,
    diagnostics: list[Diagnostic],
) -> dict[str, Any] | None:
    try:
        raw = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        diagnostics.append(
            _error(
                "RUN_BINDING_MANIFEST_INVALID",
                "catex-manifest.json must be valid UTF-8 JSON.",
            )
        )
        return None
    if (
        not isinstance(raw, dict)
        or set(raw) != _MANIFEST_FIELDS
        or raw.get("schema_version") != "catex.materialization-manifest.v1"
    ):
        diagnostics.append(
            _error(
                "RUN_BINDING_MANIFEST_INVALID",
                "The materialization manifest fields or schema version are invalid.",
            )
        )
        return None
    required_hashes = (
        "plan_sha256",
        "poscar_sha256",
        "resolved_protocol_sha256",
        "slurm_script_sha256",
    )
    if any(
        not isinstance(raw.get(key), str) or _HASH.fullmatch(raw[key]) is None
        for key in required_hashes
    ):
        diagnostics.append(
            _error("RUN_BINDING_MANIFEST_INVALID", "The manifest contains an invalid hash.")
        )
        return None
    if not isinstance(raw.get("job_name"), str) or _IDENTIFIER.fullmatch(raw["job_name"]) is None:
        diagnostics.append(
            _error("RUN_BINDING_MANIFEST_INVALID", "The manifest job_name is invalid.")
        )
        return None
    for field in ("execution_profile_id", "cluster_policy_id"):
        if not isinstance(raw.get(field), str) or _IDENTIFIER.fullmatch(raw[field]) is None:
            diagnostics.append(
                _error(
                    "RUN_BINDING_MANIFEST_INVALID",
                    f"The manifest {field} is invalid.",
                )
            )
            return None
    if (
        not isinstance(raw.get("energy_family_id"), str)
        or _ENERGY_FAMILY.fullmatch(raw["energy_family_id"]) is None
    ):
        diagnostics.append(
            _error(
                "RUN_BINDING_MANIFEST_INVALID",
                "The manifest energy_family_id is invalid.",
            )
        )
        return None
    review = raw.get("protocol_review")
    if (
        not isinstance(review, dict)
        or set(review) != {"schema_version", "state", "reviewer", "reviewed_at_utc", "note"}
        or review.get("schema_version") != "catex.protocol-review.v1"
        or review.get("state") != "approved"
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or not isinstance(review.get("reviewed_at_utc"), str)
    ):
        diagnostics.append(
            _error(
                "RUN_BINDING_MANIFEST_INVALID",
                "The manifest must contain a complete approved protocol review.",
            )
        )
        return None
    try:
        _timestamp(review["reviewed_at_utc"])
    except ValueError:
        diagnostics.append(
            _error(
                "RUN_BINDING_MANIFEST_INVALID",
                "The manifest protocol review timestamp is invalid.",
            )
        )
        return None
    if raw.get("potcar_required_on_hpc") is not True or not isinstance(
        raw.get("potcar_materialized"), bool
    ):
        diagnostics.append(
            _error(
                "RUN_BINDING_MANIFEST_INVALID",
                "The manifest POTCAR boundary flags are invalid.",
            )
        )
        return None
    if raw.get("submitted") is not False:
        diagnostics.append(
            _error(
                "RUN_BINDING_MANIFEST_INVALID",
                "The materialization manifest must remain the pre-submission record.",
            )
        )
        return None
    return raw


def validate_run_binding(
    calculation_directory: str | Path,
    *,
    submission_receipt_path: str | Path,
    slurm_snapshot_path: str | Path,
    source: SlurmSnapshotSource | str,
    observed_at_utc: str,
) -> RunBindingReport:
    """Bind caller-provided evidence without executing commands, writing, or accepting results."""

    directory = Path(calculation_directory)
    directory_name = directory.name or "vasp-output"
    receipt_report = parse_submission_receipt_path(submission_receipt_path)
    receipt = receipt_report.receipt
    diagnostics = list(receipt_report.diagnostics)
    vasp, scientifically_complete = _vasp_evidence(directory)
    manifest_path = directory / "catex-manifest.json"
    manifest_bytes, manifest_sha256, manifest_error = _read_bounded(
        manifest_path, _MAX_MANIFEST_BYTES
    )
    if manifest_error:
        diagnostics.append(manifest_error)
    _, script_sha256, script_error = _read_bounded(directory / "slurm.sh", _MAX_SLURM_SCRIPT_BYTES)
    if script_error:
        diagnostics.append(script_error)
    manifest = _manifest_values(manifest_bytes, diagnostics) if manifest_bytes is not None else None
    protocol_identity = (
        RunProtocolIdentity(
            job_name=manifest["job_name"],
            plan_sha256=manifest["plan_sha256"],
            poscar_sha256=manifest["poscar_sha256"],
            resolved_protocol_sha256=manifest["resolved_protocol_sha256"],
            energy_family_id=manifest["energy_family_id"],
            execution_profile_id=manifest["execution_profile_id"],
            cluster_policy_id=manifest["cluster_policy_id"],
            slurm_script_sha256=manifest["slurm_script_sha256"],
            potcar_required_on_hpc=manifest["potcar_required_on_hpc"],
            potcar_materialized=manifest["potcar_materialized"],
        )
        if manifest is not None
        else None
    )
    if (
        manifest is not None
        and script_sha256 is not None
        and manifest["slurm_script_sha256"] != script_sha256
    ):
        diagnostics.append(
            _error(
                "RUN_BINDING_SCRIPT_ARTIFACT_MISMATCH",
                "The actual slurm.sh bytes do not match the materialization manifest.",
            )
        )
    scheduler_report = None
    observation = None
    if receipt is not None:
        try:
            scheduler_report = parse_slurm_snapshot_path(
                slurm_snapshot_path,
                source=source,
                job_id=receipt.job_id,
                observed_at_utc=observed_at_utc,
            )
        except (OSError, ValueError) as exc:
            diagnostics.append(
                _error(
                    "RUN_BINDING_SCHEDULER_EVIDENCE_INVALID",
                    "The scheduler snapshot could not be parsed for the receipt job.",
                    {"exception_type": type(exc).__name__},
                )
            )
        else:
            diagnostics.extend(scheduler_report.diagnostics)
            observation = scheduler_report.observation

    if receipt is not None:
        if receipt.job_directory_name != directory_name:
            diagnostics.append(
                _error(
                    "RUN_BINDING_DIRECTORY_MISMATCH",
                    "The receipt directory name does not match the VASP output directory.",
                )
            )
        if manifest is not None:
            comparisons = (
                (receipt.job_name, manifest["job_name"], "RUN_BINDING_JOB_NAME_MISMATCH"),
                (
                    receipt.plan_sha256,
                    manifest["plan_sha256"],
                    "RUN_BINDING_PLAN_HASH_MISMATCH",
                ),
                (
                    receipt.slurm_script_sha256,
                    manifest["slurm_script_sha256"],
                    "RUN_BINDING_SCRIPT_HASH_MISMATCH",
                ),
            )
            for actual, expected, code in comparisons:
                if actual != expected:
                    diagnostics.append(
                        _error(code, "The submission receipt does not match the manifest.")
                    )
        if (
            script_sha256 is not None
            and receipt.slurm_script_sha256 != script_sha256
            and not any(item.code == "RUN_BINDING_SCRIPT_ARTIFACT_MISMATCH" for item in diagnostics)
        ):
            diagnostics.append(
                _error(
                    "RUN_BINDING_SCRIPT_ARTIFACT_MISMATCH",
                    "The actual slurm.sh bytes do not match the submission receipt.",
                )
            )

    binding_valid = not any(item.severity is Severity.ERROR for item in diagnostics)
    scheduler_success = bool(
        binding_valid
        and observation is not None
        and observation.source is SlurmSnapshotSource.SACCT
        and observation.state is SlurmJobState.COMPLETED
        and observation.exit_code == 0
        and observation.terminating_signal == 0
    )
    submission_scientifically_eligible = bool(
        receipt is not None and receipt.scientific_result_eligible
    )
    ready = (
        binding_valid
        and scheduler_success
        and scientifically_complete
        and submission_scientifically_eligible
    )
    if not binding_valid:
        status = RunBindingStatus.ERROR
        required_reviews = (
            "repair_or_replace_invalid_run_binding_evidence",
            "do_not_accept_scientific_result",
        )
    elif observation is not None and observation.active:
        status = RunBindingStatus.ACTIVE
        required_reviews = ("observe_same_bound_job_after_state_change",)
    elif ready:
        status = RunBindingStatus.SCIENTIFIC_REVIEW_REQUIRED
        required_reviews = (
            "review_bound_protocol_and_energy_family",
            "review_vasp_energy_force_and_magnetization_evidence",
            "accept_or_reject_scientific_result",
        )
        diagnostics.append(
            Diagnostic(
                "SCIENTIFIC_RESULT_REVIEW_REQUIRED",
                Severity.WARNING,
                "The run is bound and complete, but scientific acceptance remains manual.",
            )
        )
    elif scheduler_success and scientifically_complete and not submission_scientifically_eligible:
        status = RunBindingStatus.TERMINAL_REVIEW_REQUIRED
        required_reviews = (
            "record_scientific_rejection_for_ineligible_run",
            "do_not_accept_scientific_result",
        )
        diagnostics.append(
            Diagnostic(
                "RUN_DECLARED_SCIENTIFICALLY_INELIGIBLE",
                Severity.WARNING,
                "The submission receipt permanently excludes this run from scientific use.",
            )
        )
    else:
        status = RunBindingStatus.TERMINAL_REVIEW_REQUIRED
        required_reviews = (
            "review_bound_scheduler_and_vasp_failure_evidence",
            "do_not_accept_scientific_result",
        )
        diagnostics.append(
            Diagnostic(
                "BOUND_RUN_NOT_SCIENTIFICALLY_COMPLETE",
                Severity.WARNING,
                "The evidence is bound, but scheduler or VASP completion is insufficient.",
            )
        )
    return RunBindingReport(
        status=status,
        output_directory_name=directory_name,
        manifest_name=manifest_path.name,
        manifest_sha256=manifest_sha256,
        protocol_identity=protocol_identity,
        receipt_report=receipt_report,
        scheduler=observation,
        vasp=vasp,
        binding_valid=binding_valid,
        scheduler_success=scheduler_success,
        ready_for_scientific_review=ready,
        required_reviews=required_reviews,
        diagnostics=tuple(diagnostics),
    )
