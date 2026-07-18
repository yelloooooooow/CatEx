"""Constrained Materials Studio 2023 adapter with no arbitrary-script interface."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from pymatgen.analysis.structure_matcher import SpeciesComparator, StructureMatcher
from pymatgen.core import Structure

from catex.hashing import artifact_record
from catex.materials_studio.models import (
    ManualReviewState,
    MaterialsStudioCapabilityReport,
    MaterialsStudioExecutionReport,
    MaterialsStudioRoundTripPlan,
    MaterialsStudioRoundTripReport,
)
from catex.models import Diagnostic, Severity, TransformationRecord
from catex.structures import ComparisonSettings, compare_paths

BACKEND = "materials_script_perl_2023"
EXPECTED_VERSION = "23.1"
TEMPLATE_ID = "catex.ms.roundtrip-cif-via-xsd.v1"
_JOB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_CMD_META = frozenset('\r\n"&|<>^%!')


def _template_path() -> Path:
    return Path(__file__).parent / "templates" / "roundtrip_cif.pl"


@dataclass(frozen=True, slots=True)
class MaterialsStudioPathPolicy:
    """Trusted roots used by planning and execution boundaries."""

    input_roots: tuple[Path, ...]
    staging_root: Path

    def __post_init__(self) -> None:
        if not self.input_roots:
            raise ValueError("at least one input root is required")
        resolved_inputs: list[Path] = []
        for root in self.input_roots:
            resolved = Path(root).resolve(strict=True)
            if not resolved.is_dir():
                raise ValueError(f"input root is not a directory: {root}")
            resolved_inputs.append(resolved)
        staging = Path(self.staging_root).resolve(strict=True)
        if not staging.is_dir():
            raise ValueError("staging root must be an existing directory")
        object.__setattr__(self, "input_roots", tuple(resolved_inputs))
        object.__setattr__(self, "staging_root", staging)

    def resolve_input(self, path: str | Path) -> Path:
        source = Path(path).resolve(strict=True)
        if not source.is_file():
            raise ValueError("round-trip input must be a regular file")
        if source.suffix.lower() != ".cif":
            raise ValueError("the fixed round-trip operation accepts CIF input only")
        if not any(source.is_relative_to(root) for root in self.input_roots):
            raise ValueError("input path is outside all configured input roots")
        if any(character in str(source) for character in _CMD_META):
            raise ValueError("input path contains a command-shell metacharacter")
        return source

    def resolve_job_directory(self, job_name: str) -> Path:
        if not _JOB_NAME.fullmatch(job_name) or job_name in {".", ".."}:
            raise ValueError("job name must use 1-64 safe ASCII characters")
        job = (self.staging_root / job_name).resolve(strict=False)
        if not job.is_relative_to(self.staging_root) or job.parent != self.staging_root:
            raise ValueError("job directory escapes the configured staging root")
        return job


def detect_materials_studio_capability(
    runner_path: str | Path,
) -> MaterialsStudioCapabilityReport:
    """Inventory the configured runner without starting it or querying a license."""

    runner = Path(runner_path)
    template = _template_path()
    template_artifact = artifact_record(template)
    diagnostics: list[Diagnostic] = []
    runner_artifact = None
    if not runner.is_file():
        diagnostics.append(
            Diagnostic(
                "MS_RUNNER_NOT_FOUND",
                Severity.ERROR,
                "The configured Materials Studio runner is not a regular file.",
                {"path": str(runner)},
            )
        )
    elif runner.name.casefold() != "runmatscript.bat":
        diagnostics.append(
            Diagnostic(
                "MS_RUNNER_TYPE_UNEXPECTED",
                Severity.ERROR,
                "Materials Studio 2023 requires the configured RunMatScript batch runner.",
                {"path": str(runner)},
            )
        )
    else:
        try:
            runner_artifact = artifact_record(runner)
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    "MS_RUNNER_READ_FAILED",
                    Severity.ERROR,
                    "The configured runner could not be hashed.",
                    {"exception_type": type(exc).__name__},
                )
            )
    if not diagnostics:
        diagnostics.append(
            Diagnostic(
                "MS_LICENSE_UNVERIFIED",
                Severity.WARNING,
                "Runner presence does not prove that a Materials Studio license is available.",
            )
        )
        diagnostics.append(
            Diagnostic(
                "MS_EXECUTION_NOT_TESTED",
                Severity.INFO,
                "Capability detection did not start Materials Studio or execute a script.",
            )
        )
    return MaterialsStudioCapabilityReport(
        backend=BACKEND,
        expected_version=EXPECTED_VERSION,
        runner_available=runner_artifact is not None,
        runner_artifact=runner_artifact,
        template_artifact=template_artifact,
        license_status="unknown",
        execution_status="not_tested",
        supported_operations=("roundtrip_cif_via_xsd",),
        arbitrary_script_supported=False,
        diagnostics=tuple(diagnostics),
    )


def plan_materials_studio_roundtrip(
    input_path: str | Path,
    *,
    policy: MaterialsStudioPathPolicy,
    runner_path: str | Path,
    job_name: str,
) -> MaterialsStudioRoundTripPlan:
    """Create a no-write plan for the one registered CIF→XSD→CIF operation."""

    source = policy.resolve_input(input_path)
    job = policy.resolve_job_directory(job_name)
    if job.exists():
        raise ValueError("job directory already exists; outputs are never overwritten")
    capability = detect_materials_studio_capability(runner_path)
    if capability.runner_artifact is None or capability.has_errors:
        raise ValueError("Materials Studio runner capability is unavailable")
    return MaterialsStudioRoundTripPlan(
        input_artifact=artifact_record(source),
        runner_artifact=capability.runner_artifact,
        template_artifact=capability.template_artifact,
        staging_root=str(policy.staging_root),
        job_directory=str(job),
        intermediate_xsd_path=str(job / "roundtrip.xsd"),
        exported_cif_path=str(job / "roundtrip.cif"),
    )


def _artifact_matches(path: Path, expected_sha256: str) -> bool:
    try:
        return artifact_record(path).sha256 == expected_sha256
    except OSError:
        return False


def _execution_preflight(plan: MaterialsStudioRoundTripPlan) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    staging = Path(plan.staging_root).resolve(strict=True)
    job = Path(plan.job_directory).resolve(strict=False)
    xsd = Path(plan.intermediate_xsd_path).resolve(strict=False)
    cif = Path(plan.exported_cif_path).resolve(strict=False)
    if job.parent != staging or not job.is_relative_to(staging):
        diagnostics.append(
            Diagnostic(
                "MS_STAGING_ESCAPE",
                Severity.ERROR,
                "The planned job directory is outside the configured staging root.",
            )
        )
    if xsd.parent != job or xsd.name != "roundtrip.xsd":
        diagnostics.append(
            Diagnostic(
                "MS_XSD_OUTPUT_INVALID",
                Severity.ERROR,
                "The intermediate output must use the fixed roundtrip.xsd path.",
            )
        )
    if cif.parent != job or cif.name != "roundtrip.cif":
        diagnostics.append(
            Diagnostic(
                "MS_CIF_OUTPUT_INVALID",
                Severity.ERROR,
                "The exported output must use the fixed roundtrip.cif path.",
            )
        )
    if job.exists():
        diagnostics.append(
            Diagnostic(
                "MS_JOB_DIRECTORY_EXISTS",
                Severity.ERROR,
                "The job directory already exists; execution refuses to overwrite it.",
            )
        )
    registered_template = _template_path().resolve(strict=True)
    planned_template = Path(plan.template_artifact.path).resolve(strict=True)
    if (
        plan.backend != BACKEND
        or plan.operation != "roundtrip_cif_via_xsd"
        or plan.template_id != TEMPLATE_ID
        or planned_template != registered_template
    ):
        diagnostics.append(
            Diagnostic(
                "MS_TEMPLATE_NOT_REGISTERED",
                Severity.ERROR,
                "Execution only accepts the built-in registered round-trip template.",
            )
        )
    if Path(plan.runner_artifact.path).name.casefold() != "runmatscript.bat":
        diagnostics.append(
            Diagnostic(
                "MS_RUNNER_NOT_REGISTERED",
                Severity.ERROR,
                "Execution only accepts a configured RunMatScript.bat runner.",
            )
        )
    for label, artifact in (
        ("input", plan.input_artifact),
        ("runner", plan.runner_artifact),
        ("template", plan.template_artifact),
    ):
        if not _artifact_matches(Path(artifact.path), artifact.sha256):
            diagnostics.append(
                Diagnostic(
                    "MS_ARTIFACT_CHANGED",
                    Severity.ERROR,
                    "A planned artifact is missing or changed before execution.",
                    {"artifact_role": label},
                )
            )
    return tuple(diagnostics)


def execute_materials_studio_roundtrip(
    plan: MaterialsStudioRoundTripPlan,
    *,
    approved: bool,
    timeout_seconds: float = 180.0,
) -> MaterialsStudioExecutionReport:
    """Run the fixed template after explicit approval; never accept script text."""

    if not approved:
        raise PermissionError("Materials Studio execution requires explicit write approval")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    started = time.monotonic()
    diagnostics = list(_execution_preflight(plan))
    job = Path(plan.job_directory)
    if diagnostics:
        return MaterialsStudioExecutionReport(
            None, time.monotonic() - started, False, False, tuple(diagnostics)
        )

    job.mkdir(parents=False, exist_ok=False)
    runtime_template = job / "catex_ms_roundtrip.pl"
    shutil.copyfile(plan.template_artifact.path, runtime_template)
    if not _artifact_matches(runtime_template, plan.template_artifact.sha256):
        diagnostics.append(
            Diagnostic(
                "MS_TEMPLATE_MATERIALIZATION_FAILED",
                Severity.ERROR,
                "The fixed template copy does not match the registered template hash.",
            )
        )
        return MaterialsStudioExecutionReport(
            None, time.monotonic() - started, False, False, tuple(diagnostics)
        )
    command = [
        str(Path(plan.runner_artifact.path)),
        "catex_ms_roundtrip",
        "--",
        str(Path(plan.input_artifact.path)),
        "roundtrip.xsd",
        "roundtrip.cif",
    ]
    return_code: int | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=job,
            timeout=timeout_seconds,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return_code = int(completed.returncode)
        if return_code != 0:
            diagnostics.append(
                Diagnostic(
                    "MS_RUNNER_FAILED",
                    Severity.ERROR,
                    "The fixed Materials Studio runner returned a nonzero status.",
                    {"return_code": return_code},
                )
            )
    except subprocess.TimeoutExpired:
        diagnostics.append(
            Diagnostic(
                "MS_RUNNER_TIMEOUT",
                Severity.ERROR,
                "The fixed Materials Studio runner exceeded its approved timeout.",
                {"timeout_seconds": timeout_seconds},
            )
        )
    except OSError as exc:
        diagnostics.append(
            Diagnostic(
                "MS_RUNNER_START_FAILED",
                Severity.ERROR,
                "The fixed Materials Studio runner could not be started.",
                {"exception_type": type(exc).__name__},
            )
        )

    xsd_created = Path(plan.intermediate_xsd_path).is_file()
    cif_created = Path(plan.exported_cif_path).is_file()
    if return_code == 0 and not xsd_created:
        diagnostics.append(
            Diagnostic(
                "MS_XSD_OUTPUT_MISSING",
                Severity.ERROR,
                "The runner returned success but did not create roundtrip.xsd.",
            )
        )
    if return_code == 0 and not cif_created:
        diagnostics.append(
            Diagnostic(
                "MS_CIF_OUTPUT_MISSING",
                Severity.ERROR,
                "The runner returned success but did not create roundtrip.cif.",
            )
        )
    return MaterialsStudioExecutionReport(
        return_code,
        time.monotonic() - started,
        xsd_created,
        cif_created,
        tuple(diagnostics),
    )


def _site_mapping(
    source_path: Path,
    exported_path: Path,
    settings: ComparisonSettings,
) -> tuple[int, ...] | None:
    try:
        source = Structure.from_file(source_path)
        exported = Structure.from_file(exported_path)
        matcher = StructureMatcher(
            ltol=settings.length_tolerance,
            stol=settings.site_tolerance,
            angle_tol=settings.angle_tolerance_degrees,
            primitive_cell=False,
            scale=settings.allow_uniform_scale,
            attempt_supercell=False,
            allow_subset=False,
            comparator=SpeciesComparator(),
        )
        output_to_source = matcher.get_mapping(source, exported)
        if output_to_source is None or len(output_to_source) != len(source):
            return None
        source_to_output = [-1] * len(source)
        for output_index, source_index in enumerate(output_to_source):
            source_to_output[int(source_index)] = output_index
        if any(index < 0 for index in source_to_output):
            return None
        return tuple(source_to_output)
    except Exception:
        return None


def audit_materials_studio_roundtrip(
    plan: MaterialsStudioRoundTripPlan,
    execution: MaterialsStudioExecutionReport | None,
    *,
    manual_review_state: ManualReviewState | str = ManualReviewState.PENDING,
    comparison_settings: ComparisonSettings | None = None,
) -> MaterialsStudioRoundTripReport:
    """Independently compare generated CIF and require a human review decision."""

    review = ManualReviewState(manual_review_state)
    active = comparison_settings or ComparisonSettings()
    diagnostics: list[Diagnostic] = []
    output_artifacts = []
    comparison = None
    mapping = None
    transformation = None
    if execution is None or not execution.succeeded:
        diagnostics.append(
            Diagnostic(
                "MS_EXECUTION_NOT_SUCCEEDED",
                Severity.ERROR,
                "Round-trip audit requires a successful fixed-template execution report.",
            )
        )
    xsd = Path(plan.intermediate_xsd_path)
    cif = Path(plan.exported_cif_path)
    if xsd.is_file():
        output_artifacts.append(artifact_record(xsd))
    if cif.is_file():
        output_artifacts.append(artifact_record(cif))
        comparison = compare_paths(
            plan.input_artifact.path,
            cif,
            comparison_settings=active,
        )
        if comparison.equivalent:
            mapping = _site_mapping(Path(plan.input_artifact.path), cif, active)
            if mapping is None:
                diagnostics.append(
                    Diagnostic(
                        "MS_SITE_MAPPING_UNAVAILABLE",
                        Severity.ERROR,
                        "Equivalent structures were found but a complete atom mapping "
                        "was unavailable.",
                    )
                )
        else:
            diagnostics.append(
                Diagnostic(
                    "MS_ROUNDTRIP_NOT_EQUIVALENT",
                    Severity.ERROR,
                    "The exported CIF is not periodically equivalent to the source structure.",
                )
            )
    if len(output_artifacts) == 2 and comparison and comparison.equivalent and mapping is not None:
        transformation = TransformationRecord(
            operation="materials_studio.roundtrip_cif_via_xsd",
            input_hashes=(plan.input_artifact.sha256,),
            output_hashes=tuple(item.sha256 for item in output_artifacts),
            parameters={
                "backend": plan.backend,
                "template_id": plan.template_id,
                "source_to_exported_site_mapping": list(mapping),
            },
        )
    if review is ManualReviewState.PENDING:
        diagnostics.append(
            Diagnostic(
                "MS_MANUAL_REVIEW_REQUIRED",
                Severity.WARNING,
                "A human visual review in Materials Studio is required before downstream use.",
            )
        )
    elif review is ManualReviewState.REJECTED:
        diagnostics.append(
            Diagnostic(
                "MS_MANUAL_REVIEW_REJECTED",
                Severity.ERROR,
                "The generated structure was rejected during human visual review.",
            )
        )
    return MaterialsStudioRoundTripReport(
        plan=plan,
        execution=execution,
        output_artifacts=tuple(output_artifacts),
        comparison=comparison,
        source_to_exported_site_mapping=mapping,
        transformation=transformation,
        manual_review_state=review,
        diagnostics=tuple(diagnostics),
    )
