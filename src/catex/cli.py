"""Read-only command-line interface for inspection, metadata, and planning."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from catex.hpc import (
    PotcarMetadataExtractionReport,
    RestartAssessment,
    RunBindingReport,
    RunBindingStatus,
    SlurmSnapshotReport,
    assess_restart,
    extract_potcar_metadata,
    parse_slurm_snapshot_path,
    validate_run_binding,
)
from catex.materials_studio import (
    MaterialsStudioCapabilityReport,
    MaterialsStudioPathPolicy,
    MaterialsStudioRoundTripPlan,
    detect_materials_studio_capability,
    plan_materials_studio_roundtrip,
)
from catex.models import ComparisonReport, InspectionReport
from catex.structures import ComparisonSettings, compare_paths, inspect_path
from catex.vasp import (
    ValidationMode,
    VaspInputValidationReport,
    VaspOutputParseReport,
    parse_vasp_output,
    validate_vasp_input,
)
from catex.vasp.registry import Vasp544IncarRegistry, vasp544_incar_registry
from catex.workflow import (
    CalculationPlan,
    ProtocolResolutionReport,
    parse_cluster_policy,
    parse_execution_profile,
    plan_calculation,
    resolve_protocol,
)

Report = (
    InspectionReport
    | ComparisonReport
    | VaspInputValidationReport
    | VaspOutputParseReport
    | MaterialsStudioCapabilityReport
    | MaterialsStudioRoundTripPlan
    | ProtocolResolutionReport
    | CalculationPlan
    | PotcarMetadataExtractionReport
    | Vasp544IncarRegistry
    | SlurmSnapshotReport
    | RestartAssessment
    | RunBindingReport
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catex",
        description="Read-only inspection and planning tools for traceable catalysis workflows.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect-structure", help="Inspect a periodic structure file without modifying it."
    )
    inspect_parser.add_argument("path")
    inspect_parser.add_argument("--format", choices=("text", "json"), default="text")

    compare_parser = subparsers.add_parser(
        "compare-structures", help="Compare two periodic structures using explicit tolerances."
    )
    compare_parser.add_argument("path_a")
    compare_parser.add_argument("path_b")
    compare_parser.add_argument("--format", choices=("text", "json"), default="text")
    compare_parser.add_argument("--length-tolerance", type=float, default=0.2)
    compare_parser.add_argument("--site-tolerance", type=float, default=0.3)
    compare_parser.add_argument("--angle-tolerance", type=float, default=5.0)
    compare_parser.add_argument(
        "--allow-uniform-scale",
        action="store_true",
        help="Allow uniform volume scaling during matching (disabled by default).",
    )

    vasp_parser = subparsers.add_parser(
        "validate-vasp-input",
        help="Validate POSCAR, INCAR, KPOINTS, and copyright-safe POTCAR metadata.",
    )
    vasp_parser.add_argument("directory")
    vasp_parser.add_argument(
        "--mode",
        choices=(ValidationMode.STRICT.value, ValidationMode.EXPLORATION.value),
        default=ValidationMode.STRICT.value,
    )
    vasp_parser.add_argument(
        "--potcar-metadata",
        help="Optional metadata JSON path; defaults to catex-potcar-metadata.json.",
    )
    vasp_parser.add_argument("--format", choices=("text", "json"), default="text")

    output_parser = subparsers.add_parser(
        "parse-vasp-output",
        help="Parse OUTCAR and OSZICAR with explicit termination and convergence evidence.",
    )
    output_parser.add_argument("directory")
    output_parser.add_argument("--format", choices=("text", "json"), default="text")

    registry_parser = subparsers.add_parser(
        "show-vasp544-registry",
        help="Show the explicit CatEx-supported VASP 5.4.4 INCAR tag registry.",
    )
    registry_parser.add_argument("--format", choices=("text", "json"), default="text")

    potcar_parser = subparsers.add_parser(
        "extract-potcar-metadata",
        help="Stream POTCAR in an authorized HPC boundary and emit only safe metadata.",
    )
    potcar_parser.add_argument("path")
    potcar_parser.add_argument("--potential-family", required=True)
    potcar_parser.add_argument(
        "--authorized-hpc-read",
        action="store_true",
        help="Acknowledge that raw POTCAR access is licensed and remains inside the HPC boundary.",
    )
    potcar_parser.add_argument(
        "--format",
        choices=("text", "json", "metadata-json"),
        default="text",
    )

    snapshot_parser = subparsers.add_parser(
        "parse-slurm-snapshot",
        help="Parse a caller-provided fixed-column squeue or sacct snapshot without commands.",
    )
    snapshot_parser.add_argument("path")
    snapshot_parser.add_argument("--source", choices=("squeue", "sacct"), required=True)
    snapshot_parser.add_argument("--job-id", required=True)
    snapshot_parser.add_argument("--observed-at-utc", required=True)
    snapshot_parser.add_argument("--format", choices=("text", "json"), default="text")

    restart_parser = subparsers.add_parser(
        "assess-restart",
        help="Cross-check a Slurm snapshot and VASP outputs without writing or restarting.",
    )
    restart_parser.add_argument("directory")
    restart_parser.add_argument("--slurm-snapshot", required=True)
    restart_parser.add_argument("--source", choices=("squeue", "sacct"), required=True)
    restart_parser.add_argument("--job-id", required=True)
    restart_parser.add_argument("--observed-at-utc", required=True)
    restart_parser.add_argument("--format", choices=("text", "json"), default="text")

    binding_parser = subparsers.add_parser(
        "validate-run-binding",
        help="Bind a receipt, manifest, Slurm snapshot, script, and VASP outputs read-only.",
    )
    binding_parser.add_argument("directory")
    binding_parser.add_argument("--submission-receipt", required=True)
    binding_parser.add_argument("--slurm-snapshot", required=True)
    binding_parser.add_argument("--source", choices=("squeue", "sacct"), required=True)
    binding_parser.add_argument("--observed-at-utc", required=True)
    binding_parser.add_argument("--format", choices=("text", "json"), default="text")

    capability_parser = subparsers.add_parser(
        "materials-studio-capability",
        help="Inspect a configured Materials Studio runner without starting it.",
    )
    capability_parser.add_argument("--runner", required=True)
    capability_parser.add_argument("--format", choices=("text", "json"), default="text")

    ms_plan_parser = subparsers.add_parser(
        "plan-ms-roundtrip",
        help="Plan the fixed CIF-to-XSD-to-CIF operation without writing or executing.",
    )
    ms_plan_parser.add_argument("input")
    ms_plan_parser.add_argument("--input-root", action="append", required=True)
    ms_plan_parser.add_argument("--staging-root", required=True)
    ms_plan_parser.add_argument("--runner", required=True)
    ms_plan_parser.add_argument("--job-name", required=True)
    ms_plan_parser.add_argument("--format", choices=("text", "json"), default="text")

    protocol_parser = subparsers.add_parser(
        "resolve-protocol",
        help="Resolve a VASP 5.4.4 protocol without writing calculation inputs.",
    )
    protocol_parser.add_argument("poscar")
    protocol_parser.add_argument("--protocol", required=True)
    protocol_parser.add_argument("--potcar-metadata", required=True)
    protocol_parser.add_argument("--format", choices=("text", "json"), default="text")

    job_parser = subparsers.add_parser(
        "plan-vasp-job",
        help="Plan local input materialization and validate Slurm without writing or submitting.",
    )
    job_parser.add_argument("poscar")
    job_parser.add_argument("--protocol", required=True)
    job_parser.add_argument("--potcar-metadata", required=True)
    job_parser.add_argument("--execution-profile", required=True)
    job_parser.add_argument("--cluster-policy", required=True)
    job_parser.add_argument("--destination-root", required=True)
    job_parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def _render_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)


def _diagnostics_text(report: Report) -> list[str]:
    lines: list[str] = []
    for item in report.diagnostics:
        context = f" {json.dumps(dict(item.context), ensure_ascii=False, sort_keys=True)}"
        lines.append(f"[{item.severity.value.upper()}] {item.code}: {item.message}{context}")
    return lines


def _render_inspection_text(report: InspectionReport) -> str:
    lines = [f"status: {report.status}"]
    if report.record is not None:
        lines.extend(
            (
                f"formula: {report.record.formula}",
                f"sites: {report.record.num_sites}",
                f"volume_angstrom3: {report.record.volume_angstrom3:.8f}",
                f"canonical_hash: {report.record.canonical_hash}",
            )
        )
    if report.metrics and report.metrics.minimum_distance_angstrom is not None:
        lines.append(f"minimum_distance_angstrom: {report.metrics.minimum_distance_angstrom:.8f}")
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _render_comparison_text(report: ComparisonReport) -> str:
    lines = [f"status: {report.status}", f"equivalent: {str(report.equivalent).lower()}"]
    if report.structure_a is not None:
        lines.append(
            f"structure_a: {report.structure_a.formula} ({report.structure_a.num_sites} sites)"
        )
    if report.structure_b is not None:
        lines.append(
            f"structure_b: {report.structure_b.formula} ({report.structure_b.num_sites} sites)"
        )
    if report.normalized_rms_displacement is not None:
        lines.append(f"normalized_rms_displacement: {report.normalized_rms_displacement:.8g}")
    if report.normalized_max_displacement is not None:
        lines.append(f"normalized_max_displacement: {report.normalized_max_displacement:.8g}")
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _render_vasp_text(report: VaspInputValidationReport) -> str:
    lines = [
        f"status: {report.status}",
        f"mode: {report.mode.value}",
        f"target_vasp_version: {report.target_vasp_version}",
        f"directory: {report.directory}",
    ]
    if report.structure is not None:
        lines.extend(
            (
                f"formula: {report.structure.formula}",
                f"sites: {report.structure.num_sites}",
                f"poscar_species_order: {' '.join(report.poscar_species_order)}",
            )
        )
    if report.kpoints is not None:
        lines.append(f"kpoints_mode: {report.kpoints.generation_mode}")
        if report.kpoints.subdivisions is not None:
            lines.append(
                "kpoints_subdivisions: "
                + " ".join(str(value) for value in report.kpoints.subdivisions)
            )
    if report.potcar_metadata is not None:
        lines.append(f"potential_family: {report.potcar_metadata.potential_family}")
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _render_vasp_output_text(report: VaspOutputParseReport) -> str:
    lines = [
        f"status: {report.status}",
        f"scientifically_complete: {str(report.scientifically_complete).lower()}",
        f"target_vasp_version: {report.target_vasp_version}",
        f"detected_vasp_version: {report.detected_vasp_version or 'unknown'}",
        f"directory: {report.directory}",
        f"electronic_convergence: {report.convergence.electronic.value}",
        f"ionic_convergence: {report.convergence.ionic.value}",
        f"ionic_steps_completed: {report.convergence.ionic_steps_completed}",
    ]
    if report.energy is not None:
        lines.append(f"final_free_energy_eV: {report.energy.free_energy_ev}")
        lines.append(f"energy_confidence: {report.energy.confidence.value}")
    if report.forces is not None:
        lines.append(
            f"maximum_force_norm_eV_per_angstrom: {report.forces.maximum_norm_ev_per_angstrom}"
        )
    if report.magnetization is not None:
        components = " ".join(item.component for item in report.magnetization.projected_components)
        lines.append(f"projected_magnetization_components: {components or 'none'}")
        if report.magnetization.cell_moment_mub:
            values = " ".join(str(value) for value in report.magnetization.cell_moment_mub)
            lines.append(f"cell_moment_muB: {values}")
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _render_ms_capability_text(report: MaterialsStudioCapabilityReport) -> str:
    lines = [
        f"status: {report.status}",
        f"backend: {report.backend}",
        f"expected_version: {report.expected_version}",
        f"runner_available: {str(report.runner_available).lower()}",
        f"license_status: {report.license_status}",
        f"execution_status: {report.execution_status}",
        f"arbitrary_script_supported: {str(report.arbitrary_script_supported).lower()}",
    ]
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _render_ms_plan_text(report: MaterialsStudioRoundTripPlan) -> str:
    return "\n".join(
        (
            "status: planned",
            f"backend: {report.backend}",
            f"operation: {report.operation}",
            f"template_id: {report.template_id}",
            f"job_directory: {report.job_directory}",
            f"intermediate_xsd_path: {report.intermediate_xsd_path}",
            f"exported_cif_path: {report.exported_cif_path}",
            "arbitrary_script: false",
        )
    )


def _render_protocol_text(report: ProtocolResolutionReport) -> str:
    lines = [f"status: {report.status}"]
    if report.resolved is not None:
        lines.extend(
            (
                f"protocol_id: {report.resolved.protocol_id}",
                f"target_vasp_version: {report.resolved.target_vasp_version}",
                f"energy_family_id: {report.resolved.energy_family_id}",
                f"resolved_protocol_sha256: {report.resolved.resolved_protocol_sha256}",
                f"manual_review_state: {report.resolved.review.state.value}",
            )
        )
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _render_calculation_plan_text(report: CalculationPlan) -> str:
    lines = [
        f"status: {report.status}",
        f"job_name: {report.job_name}",
        f"job_directory: {report.job_directory}",
        f"energy_family_id: {report.resolved_protocol.energy_family_id}",
        f"ready_for_materialization: {str(report.ready_for_materialization).lower()}",
        f"slurm_status: {report.slurm.status}",
        "writes_performed: false",
        "submitted: false",
    ]
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _render_registry_text(report: Vasp544IncarRegistry) -> str:
    energy_tags = sum(item.energy_family_relevant for item in report.rules)
    return "\n".join(
        (
            f"target_vasp_version: {report.target_vasp_version}",
            f"registered_tags: {len(report.rules)}",
            f"energy_family_relevant_tags: {energy_tags}",
            "scope: catex-supported-tags-not-exhaustive-vasp-manual",
        )
    )


def _render_potcar_extraction_text(report: PotcarMetadataExtractionReport) -> str:
    lines = [
        f"status: {report.status}",
        f"source_name: {report.source_name}",
        f"potential_family: {report.potential_family}",
        f"datasets: {len(report.datasets)}",
        f"authorized_hpc_read: {str(report.authorized_hpc_read).lower()}",
        "raw_content_included: false",
        "writes_performed: false",
    ]
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _render_slurm_snapshot_text(report: SlurmSnapshotReport) -> str:
    lines = [
        f"status: {report.status}",
        f"source: {report.source.value}",
        f"source_name: {report.source_name}",
        f"requested_job_id: {report.requested_job_id}",
        "raw_content_included: false",
        "commands_executed: false",
    ]
    if report.observation is not None:
        lines.extend(
            (
                f"state: {report.observation.state.value}",
                f"elapsed_seconds: {report.observation.elapsed_seconds}",
                f"exit_code: {report.observation.exit_code}",
                f"terminating_signal: {report.observation.terminating_signal}",
            )
        )
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _render_restart_assessment_text(report: RestartAssessment) -> str:
    lines = [
        f"status: {report.status}",
        f"vasp_outcome: {report.vasp.outcome}",
        f"scientifically_complete: {str(report.vasp.scientifically_complete).lower()}",
        "failure_categories: " + " ".join(item.value for item in report.failure_categories),
        f"restart_authorized: {str(report.restart_authorized).lower()}",
        f"restart_inputs_materialized: {str(report.restart_inputs_materialized).lower()}",
        f"scientific_parameters_changed: {str(report.scientific_parameters_changed).lower()}",
        "writes_performed: false",
        "commands_executed: false",
        "submitted: false",
    ]
    if report.scheduler is not None:
        lines.insert(1, f"slurm_state: {report.scheduler.state.value}")
    lines.extend(f"required_review: {item}" for item in report.required_reviews)
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _render_run_binding_text(report: RunBindingReport) -> str:
    lines = [
        f"status: {report.status.value}",
        f"output_directory_name: {report.output_directory_name}",
        f"binding_valid: {str(report.binding_valid).lower()}",
        f"scheduler_success: {str(report.scheduler_success).lower()}",
        f"vasp_outcome: {report.vasp.outcome}",
        f"vasp_scientifically_complete: {str(report.vasp.scientifically_complete).lower()}",
        f"ready_for_scientific_review: {str(report.ready_for_scientific_review).lower()}",
        f"scientific_result_accepted: {str(report.scientific_result_accepted).lower()}",
        f"additional_submission_performed: {str(report.additional_submission_performed).lower()}",
        f"writes_performed: {str(report.writes_performed).lower()}",
        f"commands_executed: {str(report.commands_executed).lower()}",
    ]
    if report.scheduler is not None:
        lines.extend(
            (
                f"job_id: {report.scheduler.job_id}",
                f"slurm_state: {report.scheduler.state.value}",
            )
        )
    lines.extend(f"required_review: {item}" for item in report.required_reviews)
    lines.extend(_diagnostics_text(report))
    return "\n".join(lines)


def _emit(report: Report, output_format: str) -> None:
    if output_format == "json":
        print(_render_json(report))
    elif isinstance(report, InspectionReport):
        print(_render_inspection_text(report))
    elif isinstance(report, ComparisonReport):
        print(_render_comparison_text(report))
    elif isinstance(report, VaspInputValidationReport):
        print(_render_vasp_text(report))
    elif isinstance(report, VaspOutputParseReport):
        print(_render_vasp_output_text(report))
    elif isinstance(report, MaterialsStudioCapabilityReport):
        print(_render_ms_capability_text(report))
    elif isinstance(report, ProtocolResolutionReport):
        print(_render_protocol_text(report))
    elif isinstance(report, CalculationPlan):
        print(_render_calculation_plan_text(report))
    elif isinstance(report, Vasp544IncarRegistry):
        print(_render_registry_text(report))
    elif isinstance(report, PotcarMetadataExtractionReport):
        print(_render_potcar_extraction_text(report))
    elif isinstance(report, SlurmSnapshotReport):
        print(_render_slurm_snapshot_text(report))
    elif isinstance(report, RestartAssessment):
        print(_render_restart_assessment_text(report))
    elif isinstance(report, RunBindingReport):
        print(_render_run_binding_text(report))
    else:
        print(_render_ms_plan_text(report))


def _comparison_settings(arguments: Any) -> ComparisonSettings:
    return ComparisonSettings(
        length_tolerance=arguments.length_tolerance,
        site_tolerance=arguments.site_tolerance,
        angle_tolerance_degrees=arguments.angle_tolerance,
        allow_uniform_scale=arguments.allow_uniform_scale,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "inspect-structure":
            report = inspect_path(arguments.path)
            _emit(report, arguments.format)
            return 1 if report.has_errors else 0
        if arguments.command == "compare-structures":
            report = compare_paths(
                arguments.path_a,
                arguments.path_b,
                comparison_settings=_comparison_settings(arguments),
            )
            _emit(report, arguments.format)
            return 0 if report.equivalent and not report.has_errors else 1
        if arguments.command == "validate-vasp-input":
            report = validate_vasp_input(
                arguments.directory,
                mode=arguments.mode,
                potcar_metadata_path=arguments.potcar_metadata,
            )
            _emit(report, arguments.format)
            return 1 if report.has_errors else 0
        if arguments.command == "parse-vasp-output":
            report = parse_vasp_output(arguments.directory)
            _emit(report, arguments.format)
            return 0 if report.scientifically_complete else 1
        if arguments.command == "show-vasp544-registry":
            report = vasp544_incar_registry()
            _emit(report, arguments.format)
            return 0
        if arguments.command == "extract-potcar-metadata":
            report = extract_potcar_metadata(
                arguments.path,
                potential_family=arguments.potential_family,
                authorized_hpc_read=arguments.authorized_hpc_read,
            )
            if arguments.format == "metadata-json" and report.metadata_document is not None:
                print(
                    json.dumps(
                        report.metadata_document,
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            else:
                _emit(report, "json" if arguments.format == "metadata-json" else arguments.format)
            return 1 if report.has_errors else 0
        if arguments.command in {"parse-slurm-snapshot", "assess-restart"}:
            snapshot = parse_slurm_snapshot_path(
                arguments.slurm_snapshot
                if arguments.command == "assess-restart"
                else arguments.path,
                source=arguments.source,
                job_id=arguments.job_id,
                observed_at_utc=arguments.observed_at_utc,
            )
            report = (
                assess_restart(arguments.directory, snapshot)
                if arguments.command == "assess-restart"
                else snapshot
            )
            _emit(report, arguments.format)
            return 1 if report.has_errors else 0
        if arguments.command == "validate-run-binding":
            report = validate_run_binding(
                arguments.directory,
                submission_receipt_path=arguments.submission_receipt,
                slurm_snapshot_path=arguments.slurm_snapshot,
                source=arguments.source,
                observed_at_utc=arguments.observed_at_utc,
            )
            _emit(report, arguments.format)
            return int(
                report.has_errors or report.status is RunBindingStatus.TERMINAL_REVIEW_REQUIRED
            )
        if arguments.command == "materials-studio-capability":
            report = detect_materials_studio_capability(arguments.runner)
            _emit(report, arguments.format)
            return 1 if report.has_errors else 0
        if arguments.command == "plan-ms-roundtrip":
            policy = MaterialsStudioPathPolicy(
                tuple(arguments.input_root),
                arguments.staging_root,
            )
            report = plan_materials_studio_roundtrip(
                arguments.input,
                policy=policy,
                runner_path=arguments.runner,
                job_name=arguments.job_name,
            )
            _emit(report, arguments.format)
            return 0
        if arguments.command in {"resolve-protocol", "plan-vasp-job"}:
            resolution = resolve_protocol(
                arguments.protocol,
                poscar_path=arguments.poscar,
                potcar_metadata_path=arguments.potcar_metadata,
            )
            if arguments.command == "resolve-protocol" or resolution.resolved is None:
                _emit(resolution, arguments.format)
                return 1 if resolution.has_errors else 0
            profile_text = Path(arguments.execution_profile).read_text(encoding="utf-8-sig")
            policy_text = Path(arguments.cluster_policy).read_text(encoding="utf-8-sig")
            profile = parse_execution_profile(profile_text)
            policy = parse_cluster_policy(policy_text)
            report = plan_calculation(
                poscar_path=arguments.poscar,
                destination_root=arguments.destination_root,
                resolved_protocol=resolution.resolved,
                execution_profile=profile,
                cluster_policy=policy,
            )
            _emit(report, arguments.format)
            return 1 if report.has_errors else 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 2
