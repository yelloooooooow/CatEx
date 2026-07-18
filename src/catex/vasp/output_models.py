"""Versioned records emitted by read-only VASP output parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from catex.models import ArtifactRecord, Diagnostic, Severity


class ParseConfidence(StrEnum):
    """Confidence in an observation, not in the underlying scientific method."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class VaspRunOutcome(StrEnum):
    """Artifact-level outcome inferred without consulting a scheduler."""

    NORMAL = "normal"
    UNCONVERGED = "unconverged"
    TRUNCATED = "truncated"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ConvergenceState(StrEnum):
    """Explicit convergence state for one VASP minimization loop."""

    CONVERGED = "converged"
    NOT_CONVERGED = "not_converged"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ParseEvidence:
    """Location and parser rule supporting one observation."""

    artifact_path: str
    line_start: int
    line_end: int
    parser_rule: str
    confidence: ParseConfidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "parser_rule": self.parser_rule,
            "confidence": self.confidence.value,
        }


@dataclass(frozen=True, slots=True)
class EnergySummary:
    """Final complete energy record from OUTCAR with optional OSZICAR corroboration."""

    free_energy_ev: float | None
    energy_without_entropy_ev: float | None
    sigma_zero_energy_ev: float | None
    ionic_step: int | None
    confidence: ParseConfidence
    evidence: tuple[ParseEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "free_energy_eV": self.free_energy_ev,
            "energy_without_entropy_eV": self.energy_without_entropy_ev,
            "sigma_zero_energy_eV": self.sigma_zero_energy_ev,
            "ionic_step": self.ionic_step,
            "confidence": self.confidence.value,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class ForceSummary:
    """Last complete TOTAL-FORCE block."""

    vectors_ev_per_angstrom: tuple[tuple[float, float, float], ...]
    maximum_norm_ev_per_angstrom: float
    maximum_atom_index_1based: int
    ionic_step: int | None
    confidence: ParseConfidence
    evidence: ParseEvidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "vectors_eV_per_angstrom": [list(vector) for vector in self.vectors_ev_per_angstrom],
            "maximum_norm_eV_per_angstrom": self.maximum_norm_ev_per_angstrom,
            "maximum_atom_index_1based": self.maximum_atom_index_1based,
            "ionic_step": self.ionic_step,
            "confidence": self.confidence.value,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class MagnetizationComponent:
    """One OUTCAR PAW-sphere projected magnetization component."""

    component: str
    site_projected_totals_mub: tuple[float, ...]
    projected_sum_mub: float
    ionic_step: int | None
    evidence: ParseEvidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "site_projected_totals_muB": list(self.site_projected_totals_mub),
            "projected_sum_muB": self.projected_sum_mub,
            "ionic_step": self.ionic_step,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class MagnetizationSummary:
    """Projected site moments and optional OSZICAR cell moment."""

    projected_components: tuple[MagnetizationComponent, ...]
    cell_moment_mub: tuple[float, ...] | None
    cell_moment_evidence: ParseEvidence | None
    confidence: ParseConfidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "projected_components": [item.to_dict() for item in self.projected_components],
            "cell_moment_muB": list(self.cell_moment_mub) if self.cell_moment_mub else None,
            "cell_moment_evidence": (
                self.cell_moment_evidence.to_dict() if self.cell_moment_evidence else None
            ),
            "confidence": self.confidence.value,
            "interpretation": (
                "OUTCAR site values are PAW-sphere projections; OSZICAR mag values describe "
                "the cell moment. They are not interchangeable."
            ),
        }


@dataclass(frozen=True, slots=True)
class ConvergenceSummary:
    """Electronic and ionic convergence kept separate from process termination."""

    electronic: ConvergenceState
    ionic: ConvergenceState
    ionic_steps_completed: int
    final_electronic_step: int | None
    evidence: tuple[ParseEvidence, ...]
    calculation_type: str = "unknown"
    ediff_ev: float | None = None
    ediffg_ev_per_angstrom: float | None = None
    nelm: int | None = None
    nsw: int | None = None
    ibrion: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "electronic": self.electronic.value,
            "ionic": self.ionic.value,
            "ionic_steps_completed": self.ionic_steps_completed,
            "final_electronic_step": self.final_electronic_step,
            "calculation_type": self.calculation_type,
            "criteria": {
                "EDIFF_eV": self.ediff_ev,
                "EDIFFG_eV_per_angstrom": self.ediffg_ev_per_angstrom,
                "NELM": self.nelm,
                "NSW": self.nsw,
                "IBRION": self.ibrion,
            },
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class VibrationalMode:
    """One normal mode parsed from a VASP dynamical-matrix section."""

    mode_index: int
    imaginary: bool
    frequency_thz: float
    wavenumber_cm1: float
    energy_mev: float
    evidence: ParseEvidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode_index": self.mode_index,
            "imaginary": self.imaginary,
            "frequency_THz": self.frequency_thz,
            "wavenumber_cm-1": self.wavenumber_cm1,
            "energy_meV": self.energy_mev,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class VibrationalSummary:
    """Normal modes and the unfiltered harmonic zero-point energy."""

    modes: tuple[VibrationalMode, ...]

    @property
    def real_mode_count(self) -> int:
        return sum(not item.imaginary for item in self.modes)

    @property
    def imaginary_mode_count(self) -> int:
        return sum(item.imaginary for item in self.modes)

    @property
    def zero_point_energy_ev(self) -> float:
        return 0.5 * sum(item.energy_mev for item in self.modes if not item.imaginary) / 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "modes": [item.to_dict() for item in self.modes],
            "mode_count": len(self.modes),
            "real_mode_count": self.real_mode_count,
            "imaginary_mode_count": self.imaginary_mode_count,
            "zero_point_energy_eV": self.zero_point_energy_ev,
        }


@dataclass(frozen=True, slots=True)
class TerminationSummary:
    """Evidence-backed termination classification."""

    outcome: VaspRunOutcome
    normal_footer_found: bool
    fatal_error_codes: tuple[str, ...]
    confidence: ParseConfidence
    evidence: tuple[ParseEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "normal_footer_found": self.normal_footer_found,
            "fatal_error_codes": list(self.fatal_error_codes),
            "confidence": self.confidence.value,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class VaspOutputParseReport:
    """Complete versioned report for one VASP output directory."""

    directory: str
    artifacts: tuple[ArtifactRecord, ...]
    detected_vasp_version: str | None
    termination: TerminationSummary
    convergence: ConvergenceSummary
    energy: EnergySummary | None
    forces: ForceSummary | None
    magnetization: MagnetizationSummary | None
    diagnostics: tuple[Diagnostic, ...]
    vibrations: VibrationalSummary | None = None
    target_vasp_version: str = "5.4.4"
    schema_version: str = "catex.vasp-output-parse.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def scientifically_complete(self) -> bool:
        electronic_ok = self.convergence.electronic is ConvergenceState.CONVERGED
        ionic_ok = self.convergence.ionic in {
            ConvergenceState.CONVERGED,
            ConvergenceState.NOT_APPLICABLE,
        }
        return (
            self.termination.outcome is VaspRunOutcome.NORMAL
            and electronic_ok
            and ionic_ok
            and not self.has_errors
        )

    @property
    def status(self) -> str:
        return self.termination.outcome.value

    @property
    def completion_reason(self) -> str:
        if self.termination.outcome is VaspRunOutcome.FAILED:
            return "fatal_error"
        if self.termination.outcome is VaspRunOutcome.TRUNCATED:
            return "output_truncated_or_running"
        if self.convergence.electronic is ConvergenceState.NOT_CONVERGED:
            return "electronic_step_limit_reached"
        if self.convergence.ionic is ConvergenceState.NOT_CONVERGED:
            return "ionic_step_limit_reached"
        if self.scientifically_complete:
            if self.convergence.calculation_type == "relaxation":
                return "convergence_criteria_met"
            return "requested_calculation_completed"
        if self.termination.normal_footer_found:
            return "completed_with_unknown_convergence"
        return "insufficient_evidence"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "scientifically_complete": self.scientifically_complete,
            "completion_reason": self.completion_reason,
            "target_vasp_version": self.target_vasp_version,
            "detected_vasp_version": self.detected_vasp_version,
            "directory": self.directory,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "termination": self.termination.to_dict(),
            "convergence": self.convergence.to_dict(),
            "energy": self.energy.to_dict() if self.energy else None,
            "forces": self.forces.to_dict() if self.forces else None,
            "magnetization": self.magnetization.to_dict() if self.magnetization else None,
            "vibrations": self.vibrations.to_dict() if self.vibrations else None,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
